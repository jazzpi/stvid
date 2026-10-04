#!/usr/bin/env python3
"""Copy interesting stvid PNGs (plus their matching _0.png) from one acquire directory."""
import argparse
import os
import re
import shutil

# <timestamp>_<satno>_<catalog>.png; _0.png is the plot without a detection
INTERESTING_RE = re.compile(r"^(?P<stem>\d{4}-\d\d-\d\dT\d\d-\d\d-\d\d\.\d+)_\d+_\w+\.png$")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", help="Single acquire directory (not searched recursively)")
    ap.add_argument("output", help="Directory to copy into (flat)")
    args = ap.parse_args()

    # A single listing: directory listings are the slow part on the NAS, so the
    # _0.png lookup reuses it instead of extra stat calls.
    present = set(os.listdir(args.input))
    wanted = set()
    n_interesting = 0
    for name in present:
        m = INTERESTING_RE.match(name)
        if not m:
            continue
        n_interesting += 1
        wanted.add(name)
        zero = f"{m['stem']}_0.png"
        if zero in present:
            wanted.add(zero)

    os.makedirs(args.output, exist_ok=True)
    for name in sorted(wanted):
        shutil.copy2(os.path.join(args.input, name), os.path.join(args.output, name))
    print(f"Copied {len(wanted)} files ({n_interesting} interesting, "
          f"{len(wanted) - n_interesting} _0.png)")


if __name__ == "__main__":
    main()
