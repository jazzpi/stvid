#!/usr/bin/env python3
"""Summarize which satellites were seen in a directory of stvid diagnostic PNGs."""
import argparse
import configparser
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# <timestamp>_<satno>_<catalog>.png; the "no detection" plots are <timestamp>_0.png
PNG_RE = re.compile(
    r"^(?P<ts>\d{4}-\d\d-\d\dT\d\d-\d\d-\d\d\.\d+)_(?P<satno>\d+)_(?P<catalog>\w+)\.png$"
)
TS_FORMAT = "%Y-%m-%dT%H-%M-%S.%f"
CLASSIFIED_CATALOG = "classfd"
UNID_CATALOG = "unid"


def parse_tle_names(tle_dir):
    """Map NORAD number -> {tle file stem: name} over all *.tle files in tle_dir."""
    names = defaultdict(dict)
    for path in sorted(Path(tle_dir).glob("*.tle")):
        lines = [l.rstrip() for l in path.read_text(errors="replace").splitlines()]
        for i, line in enumerate(lines):
            if not line.startswith("1 ") or i + 1 >= len(lines):
                continue
            if not lines[i + 1].startswith("2 "):
                continue
            try:
                satno = int(line[2:7])
            except ValueError:
                continue
            name = None
            if i > 0 and not lines[i - 1][:2] in ("1 ", "2 "):
                name = re.sub(r"^0 ", "", lines[i - 1]).strip()
            names[satno][path.stem] = name
    return names


def find_pngs(root):
    for path in sorted(Path(root).rglob("*.png")):
        m = PNG_RE.match(path.name)
        if not m:
            continue
        yield (
            datetime.strptime(m["ts"], TS_FORMAT),
            int(m["satno"]),
            m["catalog"],
        )


def group_passes(detections, gap):
    """Group (time, satno, catalog) into passes: same satellite, gaps <= gap."""
    by_sat = defaultdict(list)
    for t, satno, catalog in detections:
        by_sat[(satno, catalog)].append(t)
    passes = []
    for (satno, catalog), times in by_sat.items():
        times.sort()
        start = prev = times[0]
        n = 1
        for t in times[1:]:
            if t - prev > gap:
                passes.append((start, prev, satno, catalog, n))
                start, n = t, 0
            prev = t
            n += 1
        passes.append((start, prev, satno, catalog, n))
    return sorted(passes)


def find_clusters(times, gap):
    """Split sorted timestamps into (start, end, n_frames) clusters separated by > gap."""
    times = sorted(times)
    clusters = []
    start = prev = times[0]
    n = 1
    for t in times[1:]:
        if t - prev > gap:
            clusters.append((start, prev, n))
            start, n = t, 0
        prev = t
        n += 1
    clusters.append((start, prev, n))
    return clusters


def describe(satno, catalog, names):
    if catalog == UNID_CATALOG:
        return f"unid #{satno}", "-"
    entries = names.get(satno, {})
    name = next((n for n in entries.values() if n), "<not in TLE files>")
    classified = catalog == CLASSIFIED_CATALOG or CLASSIFIED_CATALOG in entries
    return name, "classified" if classified else "public"


def table(rows, header):
    widths = [max(len(str(r[i])) for r in [header, *rows]) for i in range(len(header))]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    out = [fmt.format(*header), fmt.format(*("-" * w for w in widths))]
    out += [fmt.format(*map(str, r)) for r in rows]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("directory", help="Directory to search recursively for PNGs")
    ap.add_argument("--tle-dir", help="Directory with TLE files (default: tlepath from config)")
    ap.add_argument("-c", "--conf-file", default="configuration.ini")
    ap.add_argument(
        "--gap",
        type=float,
        default=5.0,
        help="Minutes between frames after which a new pass starts (default: 5)",
    )
    ap.add_argument(
        "--cluster-gap",
        type=float,
        default=60.0,
        help="Minutes between frames after which a new observing cluster starts (default: 60)",
    )
    args = ap.parse_args()

    tle_dir = args.tle_dir
    if tle_dir is None:
        cfg = configparser.ConfigParser(inline_comment_prefixes=("#", ";"))
        cfg.read(args.conf_file)
        tle_dir = cfg.get("Elements", "tlepath", fallback=None)
    names = parse_tle_names(tle_dir) if tle_dir and Path(tle_dir).is_dir() else {}
    if not names:
        print("Warning: no TLEs loaded, names/classification unavailable\n")

    detections = list(find_pngs(args.directory))
    if not detections:
        print("No interesting PNGs found")
        return
    passes = group_passes(detections, timedelta(minutes=args.gap))

    rows = []
    for start, end, satno, catalog, n in passes:
        name, status = describe(satno, catalog, names)
        rows.append(
            (
                start.strftime("%Y-%m-%d %H:%M:%S"),
                end.strftime("%H:%M:%S"),
                f"{satno:05d}",
                name,
                status,
                n,
            )
        )
    print("Passes (UTC)\n")
    print(table(rows, ("Start", "End", "ID", "Name", "Status", "Frames")))

    ident = {(s, c) for _, _, s, c, _ in passes if c != UNID_CATALOG}
    unid = {(s, c) for _, _, s, c, _ in passes if c == UNID_CATALOG}
    classified = {k for k in ident if describe(*k, names)[1] == "classified"}
    times = [t for t, _, _ in detections]
    nights = Counter(t.date() for t in times)
    unnamed = [k for k in ident if k[0] not in names]

    print("\nStats\n")
    clusters = find_clusters(times, timedelta(minutes=args.cluster_gap))
    print(f"Time range:        {min(times):%Y-%m-%d %H:%M:%S} .. {max(times):%Y-%m-%d %H:%M:%S} (UTC)")
    print(f"Observing clusters ({len(clusters)}):")
    for start, end, n in clusters:
        print(f"  {start:%Y-%m-%d %H:%M:%S} .. {end:%Y-%m-%d %H:%M:%S}  "
              f"({str(end - start).split(".")[0]}, {n} frames)")
    print(f"Frames:            {len(detections)}")
    print(f"Passes:            {len(passes)} "
          f"({sum(c != UNID_CATALOG for *_, c, _ in passes)} identified, "
          f"{sum(c == UNID_CATALOG for *_, c, _ in passes)} unidentified)")
    print(f"Unique ID'd sats:  {len(ident)} ({len(classified)} classified)")
    print(f"Unique unID'd:     {len(unid)}")
    if unnamed:
        print(f"Not in TLE files:  {len(unnamed)}")
    print("Frames per date:   " + ", ".join(f"{d} {n}" for d, n in sorted(nights.items())))
    print("Most frequent sats:")
    freq = Counter()
    for _, _, satno, catalog, _ in passes:
        if catalog != UNID_CATALOG:
            freq[(satno, catalog)] += 1
    for (satno, catalog), n in freq.most_common(5):
        print(f"  {satno:05d} {describe(satno, catalog, names)[0]}: {n} passes")


if __name__ == "__main__":
    main()
