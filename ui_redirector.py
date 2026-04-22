"""
Output capture and redirection for UI integration.
Captures stdout, stderr, and subprocess output for display in the blessed UI.
"""

import sys
import re
import threading
import subprocess
from queue import Queue, Empty
from typing import Optional, Callable
from io import StringIO


class PrintRedirector:
    """
    Redirects stdout/stderr to the UI scrollback area.
    Implements file-like interface for compatibility.
    """

    def __init__(self, ui_manager, tee_to_original: bool = False):
        self.ui = ui_manager
        self.tee = tee_to_original
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        self._buffer = ""
        self._lock = threading.Lock()

    def start(self):
        """Begin redirecting stdout/stderr."""
        sys.stdout = self
        sys.stderr = self

    def stop(self):
        """Restore original stdout/stderr."""
        # Flush any remaining buffer
        self.flush()
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr

    def write(self, text: str):
        """Capture write operations."""
        with self._lock:
            self._buffer += text

            # Process complete lines
            while '\n' in self._buffer:
                line, self._buffer = self._buffer.split('\n', 1)
                self._output_line(line)

        # If tee is enabled, also write to original
        if self.tee:
            self._original_stdout.write(text)

    def flush(self):
        """Flush the buffer."""
        with self._lock:
            if self._buffer:
                self._output_line(self._buffer)
                self._buffer = ""

        if self.tee:
            self._original_stdout.flush()

    def _output_line(self, line: str):
        """Send a completed line to the UI."""
        self.ui.log(line)

    def isatty(self):
        """Report as not a tty (for compatibility)."""
        return False


class FFmpegOutputHandler:
    """
    Runs a subprocess and streams its output to the UI, parsing ffmpeg's
    legacy `-stats` progress lines (e.g. "frame= 175 fps=37 q=25.0
    size=2976KiB time=00:00:07.17 bitrate=3397.9kbits/s speed=1.53x").
    """

    # Matches "key=value" pairs; value is any run of non-space chars.
    _KV_RE = re.compile(r'(\w+)=\s*(\S+)')
    # A line is a progress/stats line if it contains at least these keys.
    _STATS_KEYS = {'time', 'speed'}

    def __init__(self, ui_manager, episode_duration_ms: float = 0):
        self.ui = ui_manager
        self.episode_duration_ms = episode_duration_ms
        self._status_callback: Optional[Callable[[str], None]] = None

    def set_status_callback(self, callback: Callable[[str], None]):
        self._status_callback = callback

    def run_command(self, command: list, shell: bool = False, **kwargs) -> int:
        """Run `command`, stream output to UI, return exit code.

        On KeyboardInterrupt the child process is terminated (and killed if
        it doesn't exit promptly) before the exception propagates.
        """
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
            shell=shell,
            **kwargs,
        )
        try:
            # ffmpeg emits progress on \r; read char-by-char, split on \r or \n.
            buf = []
            assert proc.stdout is not None
            while True:
                ch = proc.stdout.read(1)
                if not ch:
                    break
                if ch in ('\r', '\n'):
                    if buf:
                        self._handle_line(''.join(buf).rstrip())
                        buf.clear()
                else:
                    buf.append(ch)
            if buf:
                self._handle_line(''.join(buf).rstrip())
            return proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            raise

    def _handle_line(self, line: str):
        if not line:
            return
        stats = dict(self._KV_RE.findall(line))
        if self._STATS_KEYS.issubset(stats):
            self._apply_stats(stats)
        else:
            # Normal log output — only non-progress lines reach scrollback.
            self.ui.log(line)

    # Fixed-width columns for the ffmpeg status area (prevents jitter).
    # Each entry is (format string, value-width). Values are left/right-
    # justified inside their width so the overall string length is constant.
    _COLS = (
        ("frame {:>4}",   'frame'),
        ("{:<3} fps",     'fps'),
        ("{:<7} kbits/s", 'bitrate'),
        ("t={:<11}",      'time'),
        ("{:>7}",         'speed'),
    )
    # Subtle grey-gradient background per column (xterm 256-color indices).
    # Picked as a gentle ramp down from the center; tweak to taste.
    _COL_BG = (234, 236, 234, 236, 234)

    def _apply_stats(self, s: dict):
        time_ms = self._parse_time(s.get('time', ''))
        if self.episode_duration_ms > 0 and time_ms:
            self.ui.update_episode_progress(
                min(100.0, time_ms / self.episode_duration_ms * 100)
            )
        # Strip the 'kbits/s' suffix so only the number lives in the cell.
        if 'bitrate' in s:
            s['bitrate'] = s['bitrate'].removesuffix('kbits/s')
        term = self.ui.term
        cells = []
        for (fmt, key), bg in zip(self._COLS, self._COL_BG):
            cell = " " + fmt.format(s.get(key, '-')) + " "
            cells.append(term.on_color(bg)(cell))
        status = "".join(cells)
        self.ui.update_ffmpeg_status(status)
        if self._status_callback:
            self._status_callback(status)

    @staticmethod
    def _parse_time(t: str) -> float:
        """Parse HH:MM:SS[.ms] into milliseconds; 0.0 on failure."""
        try:
            h, m, s = t.split(':')
            return (int(h) * 3600 + int(m) * 60 + float(s)) * 1000
        except (ValueError, AttributeError):
            return 0.0


class OutputTee:
    """
    Tees output to multiple destinations.
    Useful for sending output to both UI and a log file.
    """

    def __init__(self, *destinations):
        self.destinations = destinations

    def write(self, text: str):
        for dest in self.destinations:
            if hasattr(dest, 'write'):
                dest.write(text)

    def flush(self):
        for dest in self.destinations:
            if hasattr(dest, 'flush'):
                dest.flush()

    def isatty(self):
        return False
