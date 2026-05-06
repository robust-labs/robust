#!/usr/bin/env python3
"""rg_aggregate.py — aggregate `[rg_instr] ...` stderr lines per table.

Phase-1 instrumentation in the duckdb submodule emits one line per scan
thread on `~CollectionScanState()`:

  [rg_instr] table=<name> visited=N pruned_zonemap=N zero_emit=N zero_emit_pct=X.XX

This script reads stdin (or a file via --input), sums the counters per
table, and writes a CSV. Optional --query and --config columns are
prepended so the wrapper script can pipe rows straight into a single
results CSV.

usage:
    rg_aggregate.py [--input FILE] [--query Q] [--config C]
                    [--out CSV] [--header]
"""
import argparse
import csv
import re
import sys
from collections import defaultdict

LINE_RE = re.compile(
    r"\[rg_instr\]\s+"
    r"table=(?P<table>\S+)\s+"
    r"visited=(?P<visited>\d+)\s+"
    r"pruned_zonemap=(?P<pruned>\d+)\s+"
    r"zero_emit=(?P<zero>\d+)"
)


def aggregate(stream):
    totals = defaultdict(lambda: [0, 0, 0])  # visited, pruned, zero_emit
    for line in stream:
        m = LINE_RE.search(line)
        if not m:
            continue
        t = totals[m["table"]]
        t[0] += int(m["visited"])
        t[1] += int(m["pruned"])
        t[2] += int(m["zero"])
    return totals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="read from this file instead of stdin")
    ap.add_argument("--query", default="", help="query label to prepend")
    ap.add_argument("--config", default="", help="config label to prepend")
    ap.add_argument("--out", help="write CSV to this path (append if exists)")
    ap.add_argument("--header", action="store_true",
                    help="emit CSV header row before data")
    args = ap.parse_args()

    src = open(args.input) if args.input else sys.stdin
    try:
        totals = aggregate(src)
    finally:
        if args.input:
            src.close()

    fieldnames = ["query", "config", "table",
                  "visited", "pruned_zonemap", "zero_emit", "zero_emit_pct"]

    if args.out:
        # append mode; header only if file is empty / forced
        import os
        write_header = args.header or not os.path.exists(args.out) \
            or os.path.getsize(args.out) == 0
        f = open(args.out, "a", newline="")
    else:
        write_header = args.header
        f = sys.stdout

    try:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        if write_header:
            w.writeheader()
        for table in sorted(totals):
            visited, pruned, zero = totals[table]
            pct = (100.0 * zero / visited) if visited else 0.0
            w.writerow({
                "query": args.query,
                "config": args.config,
                "table": table,
                "visited": visited,
                "pruned_zonemap": pruned,
                "zero_emit": zero,
                "zero_emit_pct": f"{pct:.2f}",
            })
    finally:
        if args.out:
            f.close()


if __name__ == "__main__":
    main()
