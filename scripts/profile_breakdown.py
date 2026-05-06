#!/usr/bin/env python3
"""Parse DuckDB JSON profiling output and print operator breakdown.

Usage:
    profile_breakdown.py <baseline.json> <robust.json>
    profile_breakdown.py <baseline.json> <robust.json> <join_order.json>
    profile_breakdown.py <single.json>
"""
import json
import sys


def flatten_operators(node, depth=0):
    ops = []
    name = node.get("operator_name", node.get("operator_type", "?"))
    ops.append({
        "depth": depth,
        "name": name,
        "timing_ms": node.get("operator_timing", 0) * 1000,
        "cardinality": node.get("operator_cardinality", 0),
        "rows_scanned": node.get("operator_rows_scanned", 0),
        "extra": node.get("extra_info", {}),
    })
    for child in node.get("children", []):
        ops.extend(flatten_operators(child, depth + 1))
    return ops


def scan_map(ops):
    """Map scans to unique keys (table, ordinal) so duplicates in the same query
    (e.g. self-joins) are preserved rather than overwritten."""
    counts = {}
    m = {}
    for o in ops:
        if "SCAN" in o["name"]:
            table = o["extra"].get("Table", "?")
            idx = counts.get(table, 0)
            counts[table] = idx + 1
            m[(table, idx)] = o
    return m


def scan_label(key, multi_tables=None):
    table, idx = key
    if multi_tables is not None and table not in multi_tables:
        return table
    return f"{table}#{idx+1}"


def multi_scan_tables(*scan_maps):
    """Return set of table names that appear more than once in any scan map."""
    multi = set()
    for m in scan_maps:
        counts = {}
        for (t, _) in m.keys():
            counts[t] = counts.get(t, 0) + 1
        for t, c in counts.items():
            if c > 1:
                multi.add(t)
    return multi


def print_profile(label, data):
    latency = data.get("latency", 0) * 1000
    cpu = data.get("cpu_time", 0) * 1000
    blocked = data.get("blocked_thread_time", 0) * 1000

    root = data.get("children", [data])[0] if "children" in data else data
    ops = flatten_operators(root)
    total_op = sum(o["timing_ms"] for o in ops)

    print(f"\n{'='*70}")
    print(f" {label}")
    print(f"{'='*70}")
    print(f"  Wall (latency):         {latency:8.2f} ms")
    print(f"  CPU time (all threads): {cpu:8.2f} ms")
    print(f"  Blocked thread time:    {blocked:8.2f} ms")
    print(f"  CPU / Wall ratio:       {cpu/latency:8.2f}x" if latency > 0 else "")
    print()

    # operator tree
    print(f"  {'Operator':<35s} {'CPU(ms)':>10s} {'Rows':>12s} {'Scanned':>12s}")
    print(f"  {'-'*35} {'-'*10} {'-'*12} {'-'*12}")
    for o in ops:
        indent = "  " * o["depth"]
        name = indent + o["name"]
        print(f"  {name:<35s} {o['timing_ms']:10.2f} {o['cardinality']:12,} {o['rows_scanned']:12,}")
    print()

    # scan detail
    print(f"  --- SEQ_SCAN detail ---")
    for o in ops:
        if "SCAN" not in o["name"]:
            continue
        table = o["extra"].get("Table", "?")
        projs = o["extra"].get("Projections", "?")
        filters = o["extra"].get("Filters", "")
        print(f"  {table:20s}  cpu={o['timing_ms']:8.2f}ms  rows_out={o['cardinality']:>10,}  scanned={o['rows_scanned']:>12,}")
        print(f"    projections: {projs}")
        if filters:
            print(f"    filters: {filters}")

    return ops, latency, cpu


def print_comparison(baseline_data, robust_data):
    def categorize(ops):
        cats = {"SEQ_SCAN": 0, "HASH_JOIN": 0, "FILTER": 0, "Other": 0}
        for o in ops:
            if "SCAN" in o["name"]:
                cats["SEQ_SCAN"] += o["timing_ms"]
            elif "HASH_JOIN" in o["name"]:
                cats["HASH_JOIN"] += o["timing_ms"]
            elif "CREATE_FILTER" in o["name"] or "PROBE_FILTER" in o["name"]:
                cats["FILTER"] += o["timing_ms"]
            else:
                cats["Other"] += o["timing_ms"]
        return cats

    b_ops, b_wall, b_cpu = print_profile("BASELINE", baseline_data)
    r_ops, r_wall, r_cpu = print_profile("Robust", robust_data)

    b_cats = categorize(b_ops)
    r_cats = categorize(r_ops)

    print(f"\n{'='*70}")
    print(f" COMPARISON")
    print(f"{'='*70}")
    print(f"  {'':20s} {'Baseline':>10s} {'Robust':>10s} {'Delta':>10s}")
    print(f"  {'-'*20} {'-'*10} {'-'*10} {'-'*10}")
    print(f"  {'Wall time (ms)':<20s} {b_wall:10.1f} {r_wall:10.1f} {r_wall-b_wall:+10.1f}")
    print(f"  {'Total CPU (ms)':<20s} {b_cpu:10.1f} {r_cpu:10.1f} {r_cpu-b_cpu:+10.1f}")
    for cat in ["SEQ_SCAN", "HASH_JOIN", "FILTER", "Other"]:
        print(f"  {'  ' + cat:<20s} {b_cats[cat]:10.1f} {r_cats[cat]:10.1f} {r_cats[cat]-b_cats[cat]:+10.1f}")

    # scan-level comparison (preserves duplicates: same table can be scanned multiple times)
    b_scans = scan_map(b_ops)
    r_scans = scan_map(r_ops)
    all_keys = sorted(set(list(b_scans.keys()) + list(r_scans.keys())))
    multi = multi_scan_tables(b_scans, r_scans)

    # compute totals for rows emitted and rows scanned
    b_rows_total = sum((o["cardinality"] for o in b_scans.values()), 0)
    r_rows_total = sum((o["cardinality"] for o in r_scans.values()), 0)
    b_scanned_total = sum((o["rows_scanned"] for o in b_scans.values()), 0)
    r_scanned_total = sum((o["rows_scanned"] for o in r_scans.values()), 0)

    print(f"  {'Rows emitted':<20s} {b_rows_total:10,} {r_rows_total:10,} {r_rows_total-b_rows_total:+10,}")
    print(f"  {'Rows scanned':<20s} {b_scanned_total:10,} {r_scanned_total:10,} {r_scanned_total-b_scanned_total:+10,}")

    print(f"\n  --- Per-table scan comparison ---")
    print(f"  {'Table':<28s} {'B cpu(ms)':>10s} {'R cpu(ms)':>10s} {'B rows':>12s} {'R rows':>12s} {'B scanned':>12s} {'R scanned':>12s}")
    print(f"  {'-'*28} {'-'*10} {'-'*10} {'-'*12} {'-'*12} {'-'*12} {'-'*12}")
    for k in all_keys:
        b = b_scans.get(k)
        r = r_scans.get(k)
        label = scan_label(k, multi)
        b_t = b["timing_ms"] if b else 0
        r_t = r["timing_ms"] if r else 0
        b_r = b["cardinality"] if b else 0
        r_r = r["cardinality"] if r else 0
        b_s = b["rows_scanned"] if b else 0
        r_s = r["rows_scanned"] if r else 0
        print(f"  {label:<28s} {b_t:10.2f} {r_t:10.2f} {b_r:12,} {r_r:12,} {b_s:12,} {r_s:12,}")
    print()


def print_comparison_3way(baseline_data, lr_data, jo_data):
    """3-way comparison: baseline vs largest_root vs join_order."""
    def categorize(ops):
        cats = {"SEQ_SCAN": 0, "HASH_JOIN": 0, "FILTER": 0, "Other": 0}
        for o in ops:
            if "SCAN" in o["name"]:
                cats["SEQ_SCAN"] += o["timing_ms"]
            elif "HASH_JOIN" in o["name"]:
                cats["HASH_JOIN"] += o["timing_ms"]
            elif "CREATE_FILTER" in o["name"] or "PROBE_FILTER" in o["name"]:
                cats["FILTER"] += o["timing_ms"]
            else:
                cats["Other"] += o["timing_ms"]
        return cats

    b_ops, b_wall, b_cpu = print_profile("BASELINE", baseline_data)
    l_ops, l_wall, l_cpu = print_profile("Robust (largest_root)", lr_data)
    j_ops, j_wall, j_cpu = print_profile("Robust (join_order)", jo_data)

    b_cats = categorize(b_ops)
    l_cats = categorize(l_ops)
    j_cats = categorize(j_ops)

    print(f"\n{'='*80}")
    print(f" 3-WAY COMPARISON")
    print(f"{'='*80}")
    print(f"  {'':20s} {'Baseline':>10s} {'LR':>10s} {'JO':>10s} {'LR delta':>10s} {'JO delta':>10s}")
    print(f"  {'-'*20} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*10}")
    print(f"  {'Wall time (ms)':<20s} {b_wall:10.1f} {l_wall:10.1f} {j_wall:10.1f} {l_wall-b_wall:+10.1f} {j_wall-b_wall:+10.1f}")
    print(f"  {'Total CPU (ms)':<20s} {b_cpu:10.1f} {l_cpu:10.1f} {j_cpu:10.1f} {l_cpu-b_cpu:+10.1f} {j_cpu-b_cpu:+10.1f}")
    for cat in ["SEQ_SCAN", "HASH_JOIN", "FILTER", "Other"]:
        print(f"  {'  ' + cat:<20s} {b_cats[cat]:10.1f} {l_cats[cat]:10.1f} {j_cats[cat]:10.1f} {l_cats[cat]-b_cats[cat]:+10.1f} {j_cats[cat]-b_cats[cat]:+10.1f}")

    # scan-level comparison (preserves duplicates: same table can be scanned multiple times)
    b_scans = scan_map(b_ops)
    l_scans = scan_map(l_ops)
    j_scans = scan_map(j_ops)
    all_keys = sorted(set(list(b_scans.keys()) + list(l_scans.keys()) + list(j_scans.keys())))
    multi = multi_scan_tables(b_scans, l_scans, j_scans)

    b_rows = sum(o["cardinality"] for o in b_scans.values())
    l_rows = sum(o["cardinality"] for o in l_scans.values())
    j_rows = sum(o["cardinality"] for o in j_scans.values())
    b_scnd = sum(o["rows_scanned"] for o in b_scans.values())
    l_scnd = sum(o["rows_scanned"] for o in l_scans.values())
    j_scnd = sum(o["rows_scanned"] for o in j_scans.values())

    print(f"  {'Rows emitted':<20s} {b_rows:10,} {l_rows:10,} {j_rows:10,} {l_rows-b_rows:+10,} {j_rows-b_rows:+10,}")
    print(f"  {'Rows scanned':<20s} {b_scnd:10,} {l_scnd:10,} {j_scnd:10,} {l_scnd-b_scnd:+10,} {j_scnd-b_scnd:+10,}")

    print(f"\n  --- Per-table scan comparison ---")
    print(f"  {'Table':<28s} {'B cpu':>8s} {'LR cpu':>8s} {'JO cpu':>8s} {'B rows':>10s} {'LR rows':>10s} {'JO rows':>10s} {'B scanned':>12s} {'LR scanned':>12s} {'JO scanned':>12s}")
    print(f"  {'-'*28} {'-'*8} {'-'*8} {'-'*8} {'-'*10} {'-'*10} {'-'*10} {'-'*12} {'-'*12} {'-'*12}")
    for k in all_keys:
        b = b_scans.get(k)
        l = l_scans.get(k)
        j = j_scans.get(k)
        label = scan_label(k, multi)
        print(f"  {label:<28s} {(b['timing_ms'] if b else 0):8.2f} {(l['timing_ms'] if l else 0):8.2f} {(j['timing_ms'] if j else 0):8.2f} {(b['cardinality'] if b else 0):10,} {(l['cardinality'] if l else 0):10,} {(j['cardinality'] if j else 0):10,} {(b['rows_scanned'] if b else 0):12,} {(l['rows_scanned'] if l else 0):12,} {(j['rows_scanned'] if j else 0):12,}")
    print()


def main():
    if len(sys.argv) == 4:
        with open(sys.argv[1]) as f:
            baseline = json.load(f)
        with open(sys.argv[2]) as f:
            lr = json.load(f)
        with open(sys.argv[3]) as f:
            jo = json.load(f)
        print_comparison_3way(baseline, lr, jo)
    elif len(sys.argv) == 3:
        with open(sys.argv[1]) as f:
            baseline = json.load(f)
        with open(sys.argv[2]) as f:
            robust = json.load(f)
        print_comparison(baseline, robust)
    elif len(sys.argv) == 2:
        with open(sys.argv[1]) as f:
            data = json.load(f)
        print_profile(sys.argv[1], data)
    else:
        print(__doc__.strip())
        sys.exit(1)


if __name__ == "__main__":
    main()
