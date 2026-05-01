"""
Terminal UI Manager.

Layout (top to bottom):
    [ scrollback region      ]   <- native terminal scroll (bottom-up)
    [ ─────────────────────── ]   <- separator
    [ Status:    <text>       ]
    [ <ep label> [bar] NNN%   ]
    [ Overall:   [bar] NNN%   ]
    [ History:   <blocks>     ]

The scrollback uses a DECSTBM scrolling region so new log lines scroll
naturally from the bottom up without any manual redraw. The 5 bottom
rows live outside the scrolling region and are only rewritten on status
or progress updates, so full-screen repaints never occur.
"""

import sys
import threading
from collections import deque
from blessed import Terminal

import episode as ep

class UIManager:
    BOTTOM_ROWS = 5         # separator + status + episode bar + overall bar + history bar
    LABEL_W = 12            # fixed left-column width so bars line up
    BAR_CHAR = '█'
    FILL_FG = (180, 180, 180)   # light grey for filled portion
    EMPTY_FG = (55, 55, 55)     # dim grey for unfilled portion
    SCROLLBACK_MAX = 1000   # bounded history kept for repaint on resize
    HISTORY_MAX = 2000      # bounded size-error history for the History bar
    HIST_SAT_CAP = 0.25     # |percent_off| at which block colour is fully saturated
    LOG_GREY = (170, 170, 170)  # rgb for scrollback text colour
    DIV_CHAR = '━'          # heavy horizontal box-drawing char

    def __init__(self):
        self.term = Terminal()
        self._lock = threading.RLock()
        self._status = "Initializing..."
        self._ffmpeg = ""
        self._ep_text = "No episode"
        self._ep_pct = 0.0
        self._ov_pct = 0.0
        self._ov_text = "0/0"
        self._running = False
        self._size = (0, 0)
        self._scrollback = deque(maxlen=self.SCROLLBACK_MAX)
        self._history = deque(maxlen=self.HISTORY_MAX)
        self._divider_cache = ("", 0)  # (rendered_string, width)
        self._resize_stop = threading.Event()
        self._resize_thread = None
        # Always write to the real stdout so we bypass any redirector.
        self._out = sys.__stdout__

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.cleanup()
        return False

    # ---- lifecycle ----------------------------------------------------

    def start(self):
        self._running = True
        self._size = (self.term.width, self.term.height)
        self._write(self.term.hide_cursor + self.term.clear)
        self._set_scroll_region()
        self._draw_panel()
        self._park_cursor()
        # Start cross-platform resize watcher (polls terminal size).
        self._resize_stop.clear()
        self._resize_thread = threading.Thread(
            target=self._watch_resize, daemon=True, name="ui-resize-watch")
        self._resize_thread.start()

    def cleanup(self):
        if not self._running:
            return
        self._running = False
        # Stop resize watcher.
        self._resize_stop.set()
        if self._resize_thread and self._resize_thread.is_alive():
            self._resize_thread.join(timeout=1.0)
        self._resize_thread = None
        # Reset scroll region, restore cursor, move below UI.
        self._write("\x1b[r" + self.term.normal_cursor
                    + self.term.move_xy(0, self.term.height - 1) + "\n")

    # ---- geometry -----------------------------------------------------

    def _scroll_bot_row(self):
        """0-indexed last row of the scrolling region."""
        return self.term.height - self.BOTTOM_ROWS - 1

    def _set_scroll_region(self):
        # DECSTBM is 1-indexed, inclusive: top..bot.
        top = 1
        bot = self.term.height - self.BOTTOM_ROWS
        self._write(f"\x1b[{top};{bot}r")

    def _park_cursor(self):
        self._write(self.term.move_xy(0, self._scroll_bot_row()))

    def _watch_resize(self):
        """Poll terminal size; on change, re-flow the UI.

        blessed's `notify_on_resize()` helper requires an input loop via
        `term.inkey()` which would consume keystrokes, so we poll instead.
        `term.width` / `term.height` delegate to `shutil.get_terminal_size()`,
        which works on both POSIX and Windows without SIGWINCH.
        """
        while not self._resize_stop.wait(0.2):
            try:
                size = (self.term.width, self.term.height)
            except Exception:
                continue
            if size != self._size and size[0] > 0 and size[1] > 0:
                self._size = size
                self._on_resize()

    def _on_resize(self):
        if not self._running:
            return
        with self._lock:
            # Full repaint: clear the screen, re-establish the scroll region,
            # replay the tail of the scrollback buffer into it, and redraw
            # the bottom panel.
            self._divider_cache = ("", 0)  # width changed; rebuild on demand
            self._write("\x1b[r" + self.term.clear)
            self._set_scroll_region()
            self._replay_scrollback()
            self._draw_panel()
            self._park_cursor()

    @staticmethod
    def _visual_rows(line, w):
        """How many rows `line` occupies after terminal autowrap at width `w`."""
        if w <= 0 or not line:
            return 1
        return (len(line) + w - 1) // w

    def _replay_scrollback(self):
        """Paint the last N lines of scrollback into the scroll region.

        Lines are written whole and the terminal's autowrap is allowed to
        flow them across multiple rows, so copy/paste preserves them as
        single lines.
        """
        w = self.term.width
        region_h = self._scroll_bot_row() + 1  # rows 0.._scroll_bot_row inclusive
        if region_h <= 0:
            return
        # Walk scrollback from newest to oldest, accumulating whole lines
        # whose combined visual rows fit in the region.
        selected = []
        used = 0
        for line in reversed(self._scrollback):
            n = self._visual_rows(line, w)
            if used + n > region_h:
                break
            selected.append((line, n))
            used += n
        selected.reverse()
        # Place the tail flush to the bottom of the region.
        row = region_h - used
        out = []
        for line, n in selected:
            out.append(self.term.move_xy(0, row)
                       + self.term.clear_eol + self._style_log(line))
            row += n
        if out:
            self._write("".join(out))

    # ---- drawing ------------------------------------------------------

    def _history_bar(self, width):
        width = max(3, width)
        vals = list(self._history)[-width:]
        t = self.term
        parts = []
        for v in vals:
            intensity = min(1.0, abs(v) / self.HIST_SAT_CAP)
            c = int(50 + 205 * intensity)
            rgb = (c, 0, 0) if v > 0 else (0, c, 0)
            parts.append(t.color_rgb(*rgb)(self.BAR_CHAR))
        pct = vals[-1] * 100 if vals else 0.0
        return f"[{''.join(parts)}{' ' * (width - len(vals))}] {pct:3.0f}%"

    def _bar(self, pct, width):
        width = max(3, width)
        filled = int(width * pct / 100)
        t = self.term
        fill = t.color_rgb(*self.FILL_FG)(self.BAR_CHAR * filled)
        empty = t.color_rgb(*self.EMPTY_FG)(self.BAR_CHAR * (width - filled))
        return f"[{fill}{empty}] {pct:3.0f}%"

    def _divider(self, w):
        """Build a styled divider line with a horizontal grey gradient.

        Dark at the edges, brighter in the centre; cached per width so it's
        only recomputed on resize rather than every panel refresh.
        """
        cached, cached_w = self._divider_cache
        if cached_w == w and cached:
            return cached
        t = self.term
        parts = []
        denom = max(1, w - 1)
        for i in range(w):
            # x: 0 at edges, 1 at center
            x = 1.0 - abs((i / denom) - 0.5) * 2
            v = int(40 + x * 120)  # grey ramp 40..160
            parts.append(t.color_rgb(v, v, v)(self.DIV_CHAR))
        rendered = "".join(parts)
        self._divider_cache = (rendered, w)
        return rendered

    def _style_log(self, line):
        return self.term.color_rgb(*self.LOG_GREY)(line)

    def _label(self, text):
        """Truncate/pad a label to LABEL_W chars so bars line up."""
        text = text[:self.LABEL_W - 1]
        return f"{text:<{self.LABEL_W}}"

    def _compose_status_row(self, w):
        """`Status: <left text>          <ffmpeg stats right-justified>`"""
        left = self._label("Status:") + self._status
        if not self._ffmpeg:
            return left[:w]
        # Use visible length (term.length ignores ANSI styling codes).
        right_w = self.term.length(self._ffmpeg)
        left = left[:max(0, w - right_w - 1)]
        return left + self.term.rjust(self._ffmpeg, w - self.term.length(left))

    def _draw_panel(self):
        w = self.term.width
        sep = self.term.height - self.BOTTOM_ROWS   # 0-indexed separator row
        ov_suffix = f"  {self._ov_text}"
        # Budget per row: LABEL_W + `[` + bar_w + `] NNN%` + suffix <= w
        # `[` + `] NNN%` contributes 7 visible chars.
        fixed = self.LABEL_W + 7
        ov_bar_w = max(3, w - fixed - len(ov_suffix))
        # Bar strings contain ANSI codes; widths above account for all
        # visible characters so no byte-level truncation is needed.
        rows = [
            (sep,     self._divider(w)),
            (sep + 1, self._compose_status_row(w)),
            (sep + 2, self._label(self._ep_text + ":") + self._bar(self._ep_pct, ov_bar_w)),
            (sep + 3, self._label("Overall:") + self._bar(self._ov_pct, ov_bar_w) + ov_suffix),
            (sep + 4, self._label("History:") + self._history_bar(ov_bar_w)),
        ]
        out = "".join(self.term.move_xy(0, r) + self.term.clear_eol + s for r, s in rows)
        self._write(out)

    def _refresh_panel(self):
        if self._running:
            self._draw_panel()
            self._park_cursor()

    # ---- public API ---------------------------------------------------

    def log(self, message: str):
        msg = self.term.strip_seqs(message).rstrip()
        with self._lock:
            self._scrollback.append(msg)
            if not self._running:
                print(msg)
                return
            # Scroll the region up first (\n at the bottom row of a DECSTBM
            # region scrolls), then paint the new line onto the now-blank
            # bottom row. Doing it in this order avoids leaving a trailing
            # blank row between the newest log line and the divider.
            # The line is written in full; the terminal's autowrap (DECAWM)
            # combined with the DECSTBM scroll region handles long lines
            # natively, so copy/paste keeps them as a single line.
            bot = self._scroll_bot_row()
            self._write(self.term.move_xy(0, bot)
                        + "\n"
                        + self.term.move_xy(0, bot)
                        + self.term.clear_eol
                        + self._style_log(msg))

    def update_status(self, text: str):
        """Set the free-form left-side status text."""
        with self._lock:
            self._status = text
            self._refresh_panel()

    def update_ffmpeg_status(self, text: str):
        """Set the right-justified ffmpeg stats text on the status row."""
        with self._lock:
            self._ffmpeg = text
            self._refresh_panel()

    def update_episode(self, ep: ep.Episode, total: int = 0):
        with self._lock:
            # self._ep_text = f"Ep {number}/{total} - {name}" if number and total else name
            self._ep_text = f"Ep {ep.ep_num}/{total}" if ep and total else f"Ep {ep.ep_num}"
            self._refresh_panel()

    def update_episode_progress(self, percent: float):
        with self._lock:
            self._ep_pct = max(0.0, min(100.0, percent))
            self._refresh_panel()

    def update_overall_progress(self, current: int, total: int):
        with self._lock:
            if total > 0:
                self._ov_pct = current / total * 100
                self._ov_text = f"{current}/{total}"
            else:
                self._ov_pct = 0.0
                self._ov_text = "0/0"
            self._refresh_panel()

    def append_history(self, percent_off: float):
        """Append a loop-iteration size error (fractional, + oversized / - undersized)."""
        with self._lock:
            self._history.append(percent_off)
            self._refresh_panel()

    def set_history(self, values):
        """Replace the History bar contents wholesale (used on project reload)."""
        with self._lock:
            self._history.clear()
            # deque(maxlen=...) will trim on extend if values exceeds capacity.
            self._history.extend(values)
            self._refresh_panel()

    def refresh(self):
        with self._lock:
            self._refresh_panel()

    def clear_scrollback(self):
        with self._lock:
            if not self._running:
                return
            for r in range(self._scroll_bot_row() + 1):
                self._write(self.term.move_xy(0, r) + self.term.clear_eol)
            self._park_cursor()

    # ---- internal -----------------------------------------------------

    def _write(self, s: str):
        self._out.write(s)
        self._out.flush()


