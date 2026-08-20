"""Standalone tool: strip forced (burned-in) subtitles from a full-dialogue SRT.

Reads a "forced" SRT (lines that will be burned into video) and a "full" SRT
(all dialogue). Removes from the full file any subtitle whose timing overlaps
a forced one, asks the user how to resolve text mismatches, and ensures the
following surviving subtitle does not start before the forced subtitle ends.

Usage:
    python forcedstripper.py FULL.srt FORCED.srt OUTPUT.srt \
        [--window-ms 250] [--min-duration-ms 500] [--gap-ms 1]
"""

import argparse
import re
import sys
from datetime import timedelta

import srt

# --- Tunable defaults (override via CLI flags) -------------------------------
OVERLAP_WINDOW_MS = 0  # slack on both ends when matching forced<->full
MIN_DURATION_MS = 500    # warn if a timing-fix shrinks a sub below this
GAP_MS = 1               # gap inserted between forced.end and next full.start

_TAG_RE = re.compile(r"<[^>]+>|\{[^}]+\}")


def overlaps(a: srt.Subtitle, b: srt.Subtitle, window_ms: int) -> bool:
    """Return True if a and b overlap in time, allowing window_ms slack."""
    slack = timedelta(milliseconds=window_ms)
    return (a.start - slack) < b.end and (b.start - slack) < a.end


def normalize_text(s: str) -> str:
    """Strip tags/whitespace, collapse spaces, lowercase for comparison."""
    s = _TAG_RE.sub("", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def fmt_ts(td: timedelta) -> str:
    total_ms = int(td.total_seconds() * 1000)
    h, rem = divmod(total_ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def fmt_sub(sub: srt.Subtitle) -> str:
    return f"#{sub.index} {fmt_ts(sub.start)} --> {fmt_ts(sub.end)} | {sub.content!r}"


def prompt(msg: str, choices: str) -> str:
    """Prompt until the user enters one of the single-letter choices."""
    valid = set(choices.lower())
    while True:
        sys.stdout.write(f"{msg} [{'/'.join(choices)}]: ")
        sys.stdout.flush()
        line = sys.stdin.readline()
        if not line:
            print()
            sys.exit(1)
        ans = line.strip().lower()
        if ans in valid:
            return ans
        print(f"  please enter one of: {', '.join(choices)}")


def prompt_int_list(msg: str, max_n: int) -> list:
    """Prompt for a comma-separated list of 1..max_n, or 'none'."""
    while True:
        sys.stdout.write(f"{msg}: ")
        sys.stdout.flush()
        line = sys.stdin.readline()
        if not line:
            print()
            sys.exit(1)
        ans = line.strip().lower()
        if ans in ("", "none", "n"):
            return []
        try:
            picks = [int(x) for x in ans.replace(",", " ").split()]
            if all(1 <= p <= max_n for p in picks):
                return picks
        except ValueError:
            pass
        print(f"  enter numbers 1..{max_n} separated by commas, or 'none'")


def prompt_int(msg: str) -> int:
    while True:
        sys.stdout.write(f"{msg}: ")
        sys.stdout.flush()
        line = sys.stdin.readline()
        if not line:
            print()
            sys.exit(1)
        try:
            return int(line.strip())
        except ValueError:
            print("  enter an integer")


def load_srt(path: str) -> list:
    with open(path, "r", encoding="utf-8-sig") as fh:
        return list(srt.parse(fh.read()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("full", help="path to full-dialogue SRT")
    parser.add_argument("forced", help="path to forced (burned-in) SRT")
    parser.add_argument("output", help="path to write the stripped SRT")
    parser.add_argument("--window-ms", type=int, default=OVERLAP_WINDOW_MS,
                        help=f"timing match tolerance ms (default {OVERLAP_WINDOW_MS})")
    parser.add_argument("--min-duration-ms", type=int, default=MIN_DURATION_MS,
                        help=f"warn if adjusted sub shorter than this (default {MIN_DURATION_MS})")
    parser.add_argument("--gap-ms", type=int, default=GAP_MS,
                        help=f"gap after forced.end (default {GAP_MS})")
    args = parser.parse_args()

    window_ms = args.window_ms
    min_dur_ms = args.min_duration_ms
    gap_ms = args.gap_ms

    full_subs = sorted(load_srt(args.full), key=lambda s: s.start)
    forced_subs = sorted(load_srt(args.forced), key=lambda s: s.start)

    print(f"Loaded {len(full_subs)} full subs, {len(forced_subs)} forced subs.")
    print(f"Window: {window_ms}ms  Min duration: {min_dur_ms}ms  Gap: {gap_ms}ms\n")

    removed_ids = set()        # id(sub) of full subs to drop
    text_replacements = {}     # id(sub) -> new text
    n_removed = 0
    n_text_replaced = 0
    n_timing_fixed = 0
    n_warnings = 0

    # --- Phase 1: removal decisions -----------------------------------------
    print("=== Phase 1: matching forced -> full ===")
    for fsub in forced_subs:
        candidates = [s for s in full_subs
                      if id(s) not in removed_ids and overlaps(fsub, s, window_ms)]

        if not candidates:
            print(f"WARN: forced {fmt_sub(fsub)} has no overlapping full sub.")
            n_warnings += 1
            continue

        if len(candidates) > 1:
            print(f"\nForced: {fmt_sub(fsub)}")
            print(f"  {len(candidates)} full-file subs overlap; processing each:")
            for c in candidates:
                print(f"    - {fmt_sub(c)}")

        for full_sub in candidates:
            same = normalize_text(fsub.content) == normalize_text(full_sub.content)
            if same:
                print(f"MATCH  forced #{fsub.index} <-> full #{full_sub.index}  "
                      f"{fmt_ts(fsub.start)}  {fsub.content!r}  -> remove")
                removed_ids.add(id(full_sub))
                n_removed += 1
                continue

            print(f"\nMISMATCH  forced #{fsub.index} <-> full #{full_sub.index}")
            print(f"  forced: {fmt_ts(fsub.start)} --> {fmt_ts(fsub.end)}  {fsub.content!r}")
            print(f"  full:   {fmt_ts(full_sub.start)} --> {fmt_ts(full_sub.end)}  {full_sub.content!r}")
            choice = prompt("f=remove from output, u=keep in output, q=quit", "fuq")
            if choice == "q":
                print("Aborted by user.")
                sys.exit(1)
            elif choice == "u":
                print(f"  -> keep full #{full_sub.index}")
            elif choice == "f":
                print(f"  -> remove full #{full_sub.index}")
                removed_ids.add(id(full_sub))
                n_removed += 1

    # --- Phase 2: timing fix on following sub -------------------------------
    print("\n=== Phase 2: timing-collision fix ===")
    surviving = [s for s in full_subs if id(s) not in removed_ids]

    for fsub in forced_subs:
        # next surviving sub whose start is before forced.end + gap
        boundary = fsub.end + timedelta(milliseconds=gap_ms)
        # find first surviving with start < boundary AND start >= fsub.start - window
        # (i.e. one that begins during/just-after the forced range)
        candidates = [s for s in surviving
                      if s.start < boundary and s.end > fsub.start]
        if not candidates:
            continue
        # Pick the latest-starting candidate (the "following" one most likely to clash)
        nxt = max(candidates, key=lambda s: s.start)
        if nxt.start >= boundary:
            continue

        new_start = boundary
        if new_start >= nxt.end:
            new_dur_ms = 0
        else:
            new_dur_ms = int((nxt.end - new_start).total_seconds() * 1000)

        print(f"\nForced ends at {fmt_ts(fsub.end)}; following full sub:")
        print(f"  {fmt_sub(nxt)}")
        print(f"  proposed start: {fmt_ts(new_start)}  (new duration {new_dur_ms}ms)")

        if new_dur_ms < min_dur_ms:
            n_warnings += 1
            choice = prompt(
                f"Below min-duration ({min_dur_ms}ms). "
                "a=adjust anyway, d=drop sub, k=keep original (overlap remains), m=manual ms",
                "adkm")
            if choice == "a":
                nxt.start = new_start
                n_timing_fixed += 1
            elif choice == "d":
                removed_ids.add(id(nxt))
                surviving = [s for s in surviving if id(s) != id(nxt)]
                n_removed += 1
            elif choice == "k":
                pass
            elif choice == "m":
                ms = prompt_int("Enter new start offset from forced.end in ms")
                nxt.start = fsub.end + timedelta(milliseconds=ms)
                n_timing_fixed += 1
        else:
            nxt.start = new_start
            n_timing_fixed += 1
            print("  adjusted.")

    # --- Summary + write -----------------------------------------------------
    print("\n=== Summary ===")
    print(f"  removed:           {n_removed}")
    print(f"  text-replaced:     {n_text_replaced}")
    print(f"  timings adjusted:  {n_timing_fixed}")
    print(f"  warnings:          {n_warnings}")

    out_subs = [s for s in full_subs if id(s) not in removed_ids]
    for s in out_subs:
        if id(s) in text_replacements:
            s.content = text_replacements[id(s)]
    out_subs.sort(key=lambda s: s.start)
    out_subs = list(srt.sort_and_reindex(out_subs))

    if prompt(f"\nWrite {len(out_subs)} subs to {args.output}?", "yn") != "y":
        print("Not written.")
        return

    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(srt.compose(out_subs))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
