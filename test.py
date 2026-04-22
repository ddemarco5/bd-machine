"""
Binary search to find the minimum CQ increment that produces a measurable
bitrate change with hevc_nvenc.

Strategy:
  - Pick a baseline CQ (BASE_CQ).
  - Binary search over delta in [0, 1] to find the smallest delta where
    encoding at BASE_CQ and BASE_CQ + delta yields different file sizes.
  - Each encode uses a 5-minute clip so the test runs quickly.
"""

import os
import sys
from pathlib import Path
from pymediainfo import MediaInfo

from commands import encode_video
from episode import Episode
from source import Source
from constants import UBP_X700
from ui import UIManager
from ui_redirector import PrintRedirector


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
VID_PATH = "C:/Users/Dominic/Desktop/bd-machine/test/Foundation.2021.S01E01.The.Emperors.Peace.2160p.ATVP.WEB-DL.DDP5.1.Atmos.DV.MP4.x265-DVSUX.mp4"
STOP_TIME = "00:01:00"
BASE_CQ   = 30.0          # reference quality level
WORK_DIR  = Path("./cq_test_workspace")
PROFILE   = UBP_X700
TOLERANCE = 1e-4          # binary search stops when hi - lo < this
MAX_ITERS = 20


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_episode():
    src = Source(name="test")
    ep = Episode(ep_num=1, origin_src=src, vid_src=VID_PATH, name="test", sub_src=None)
    # Populate duration_src so stop_time logic fires in encode_video.
    # 5 min in ms is more than enough; the actual value just needs to be > 0.
    ep.duration_src = 1 * 60 * 1000
    return ep


def get_bitrate(path: Path) -> int:
    info = MediaInfo.parse(path)
    return info.video_tracks[0].bit_rate


def encode_at_cq(cq: float, ep, ui) -> int:
    result = encode_video(
        episode=ep,
        out_path=WORK_DIR,
        crf=cq,
        profile=PROFILE,
        hardsub=False,
        fontsdir=Path(".").absolute(),
        stop_time=STOP_TIME,
        ui_manager=ui,
    )
    bitrate = get_bitrate(result)
    print(f"    bitrate: {bitrate}")
    os.remove(result)
    return bitrate


# ---------------------------------------------------------------------------
# Main binary search
# ---------------------------------------------------------------------------
def main(ui):
    WORK_DIR.mkdir(exist_ok=True)
    ep  = make_episode()

    print(f"=== CQ minimum increment test ===")
    print(f"Base CQ : {BASE_CQ}")
    print(f"Clip    : {STOP_TIME}")
    print()

    base_bitrate = encode_at_cq(BASE_CQ, ep, ui)
    print(f"Baseline bitrate at CQ={BASE_CQ}: {base_bitrate}")

    # Binary search for smallest delta where BASE_CQ + delta differs from BASE_CQ.
    #   lo : delta known to produce NO change (starts tiny; assumed no-op)
    #   hi : delta known to produce a change  (starts at 1.0; assumed large enough)
    # Each iteration:
    #   target = lo + (hi - lo) / 2
    #   encode at BASE_CQ + target, compare to base_bitrate
    #   if changed  -> target is a new upper bound (hi = target)
    #   if no change -> target is a new lower bound (lo = target)
    lo, hi = 0.1, .3

    for i in range(MAX_ITERS):
        target = lo + (hi - lo) / 2.0
        print(f"\n[iter {i+1}/{MAX_ITERS}] target delta={target:.6f}  "
              f"(lo={lo:.6f} no-change, hi={hi:.6f} change)")

        print(f"\n--- Encoding at CQ={BASE_CQ + target:.6f}, crf increment of {target} ---")
        trial_bitrate = encode_at_cq(BASE_CQ + target, ep, ui)
        changed = trial_bitrate != base_bitrate

        print(f"    base={base_bitrate}  trial={trial_bitrate}  changed={changed}")

        if changed:
            hi = target
        else:
            lo = target

        if (hi - lo) < TOLERANCE:
            print(f"\nConverged after {i+1} iterations.")
            break

    print()
    print(f"Smallest CQ delta that causes a bitrate change : ~{hi:.6f}")
    print(f"  (lo={lo:.6f} still produced no change; hi={hi:.6f} did produce a change)")


if __name__ == "__main__":
    exit_code = 0
    with UIManager() as ui:
        redirector = PrintRedirector(ui)
        redirector.start()
        try:
            main(ui)
        except KeyboardInterrupt:
            ui.update_status("Interrupted — shutting down...")
            exit_code = 130
        finally:
            redirector.stop()
    sys.exit(exit_code)
