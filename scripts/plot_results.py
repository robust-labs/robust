#!/usr/bin/env python3
"""Plot benchmark results in publication-ready style.

Usage:
    plot_results.py speedup <comparison.tsv> --out <file.pdf|png>
    plot_results.py metric  <memory|rows_scanned|cardinality> <metrics.csv>
                    --out-ratio <file> --out-totals <file>
"""
import argparse
import csv
import math
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import numpy as np

GREEN = "#558b2f"
GREEN_FILL = "#7cb342"
RED = "#b71c1c"
RED_FILL = "#c62828"
INK = "#1a1a1a"
GRID = "#bdbdbd"


def style():
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "DejaVu Serif"],
        "font.size": 11,
        "axes.linewidth": 0.8,
        "axes.edgecolor": INK,
        "axes.labelcolor": INK,
        "xtick.color": INK,
        "ytick.color": INK,
        "savefig.bbox": "tight",
    })


def parse_comparison(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f, delimiter="\t"):
            rows.append({
                "query": r["query"],
                "baseline": float(r["baseline"]),
                "robust": float(r["robust"]),
                "ratio": float(r["speedup"]),
            })
    return rows


METRIC_CONFIG = {
    "memory": {
        "csv_baseline": "baseline_memory",
        "csv_robust": "robust_memory",
        "title": "Robust Memory — JOB Benchmark",
        "ylabel": "Memory savings (Baseline / Robust)",
        "totals_label": "Total Memory Allocated",
        "totals_unit": "GB",
        "totals_divisor": 1024 ** 3,
    },
    "rows_scanned": {
        "csv_baseline": "baseline_rows_scanned",
        "csv_robust": "robust_rows_scanned",
        "title": "Robust Rows Scanned — JOB Benchmark",
        "ylabel": "Scan reduction (Baseline / Robust)",
        "totals_label": "Cumulative Rows Scanned",
        "totals_unit": "M rows",
        "totals_divisor": 1e6,
    },
    "cardinality": {
        "csv_baseline": "baseline_cardinality",
        "csv_robust": "robust_cardinality",
        "title": "Robust Cardinality — JOB Benchmark",
        "ylabel": "Cardinality reduction (Baseline / Robust)",
        "totals_label": "Cumulative Cardinality",
        "totals_unit": "M rows",
        "totals_divisor": 1e6,
    },
    "peak_buffer": {
        "csv_baseline": "baseline_peak_buffer",
        "csv_robust": "robust_peak_buffer",
        "title": "Robust Peak Buffer Memory — JOB Benchmark",
        "ylabel": "Peak buffer ratio (Baseline / Robust)",
        "totals_label": "Peak Buffer Memory",
        "totals_unit": "GB",
        "totals_divisor": 1024 ** 3,
    },
    "hj_card_sum": {
        "csv_baseline": "baseline_hj_card_sum",
        "csv_robust": "robust_hj_card_sum",
        "title": "Robust HJ Output (sum) — JOB Benchmark",
        "ylabel": "HJ output sum reduction (Baseline / Robust)",
        "totals_label": "Sum of HASH_JOIN Output Cardinality",
        "totals_unit": "M rows",
        "totals_divisor": 1e6,
    },
    "hj_card_max": {
        "csv_baseline": "baseline_hj_card_max",
        "csv_robust": "robust_hj_card_max",
        "title": "Robust HJ Output (peak) — JOB Benchmark",
        "ylabel": "HJ peak reduction (Baseline / Robust)",
        "totals_label": "Max HASH_JOIN Output Cardinality (sum across queries)",
        "totals_unit": "M rows",
        "totals_divisor": 1e6,
    },
}


def parse_metric(path, baseline_col, robust_col):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            b = float(r[baseline_col])
            x = float(r[robust_col])
            rows.append({
                "query": r["query"],
                "baseline": b,
                "robust": x,
                # ratio = baseline / robust → >1 means robust is leaner (matches speedup orientation)
                "ratio": (b / x) if x > 0 else float("nan"),
            })
    return [r for r in rows if not math.isnan(r["ratio"])]


def sorted_curve_plot(rows, out_path, *,
                      title, ylabel,
                      good_when_above=True,
                      annotate_top=3, annotate_bot=3,
                      summary_word_good="faster", summary_word_bad="slower",
                      summary_metric_label="Geomean",
                      yscale="log"):
    """Plot a sorted curve with red/green fills around y=1.

    good_when_above=True  → values >1 are green (good), <1 are red.
    good_when_above=False → values <1 are green (good), >1 are red.
    """
    rows_sorted = sorted(rows, key=lambda r: r["ratio"])
    ratios = np.array([r["ratio"] for r in rows_sorted])
    n = len(ratios)
    x = np.arange(n)

    geomean = math.exp(np.mean(np.log(ratios)))
    n_good = sum(1 for v in ratios if (v > 1.0) == good_when_above)
    n_bad = sum(1 for v in ratios if (v < 1.0) == good_when_above)

    good_color = GREEN_FILL
    bad_color = RED_FILL
    above_color = good_color if good_when_above else bad_color
    below_color = bad_color if good_when_above else good_color
    above_label_color = GREEN if good_when_above else RED
    below_label_color = RED if good_when_above else GREEN

    fig, ax = plt.subplots(figsize=(7.5, 4.0))

    ax.plot(x, ratios, color=INK, linewidth=1.1)
    ax.fill_between(x, 1.0, ratios, where=(ratios >= 1.0),
                    color=above_color, alpha=0.35, interpolate=True, linewidth=0)
    ax.fill_between(x, 1.0, ratios, where=(ratios <= 1.0),
                    color=below_color, alpha=0.35, interpolate=True, linewidth=0)

    ax.axhline(1.0, color="#666666", linewidth=0.6, linestyle="--", alpha=0.7)
    ax.axhline(geomean, color=GREEN if (geomean > 1) == good_when_above else RED,
               linewidth=0.9, linestyle="--", alpha=0.85)

    # only annotate actual outliers in the right direction;
    # stagger y offsets so close-together points don't overlap.
    top = [r for r in rows_sorted if r["ratio"] > 1.0][-annotate_top:][::-1]
    bot = [r for r in rows_sorted if r["ratio"] < 1.0][:annotate_bot]
    # diagonal stagger so labels of close-together points don't overlap
    for k, r in enumerate(top):
        i = rows_sorted.index(r)
        ax.annotate(f"{r['query']} {r['ratio']:.2f}×",
                    xy=(i, r["ratio"]),
                    xytext=(-12 - k * 32, 4 + k * 22), textcoords="offset points",
                    fontsize=8, ha="right", va="bottom",
                    color=above_label_color,
                    arrowprops=dict(arrowstyle="-", color=above_label_color,
                                    lw=0.5, alpha=0.6))
    for k, r in enumerate(bot):
        i = rows_sorted.index(r)
        ax.annotate(f"{r['query']} {r['ratio']:.2f}×",
                    xy=(i, r["ratio"]),
                    xytext=(10 + k * 28, -6 - k * 16), textcoords="offset points",
                    fontsize=8, ha="left", va="top",
                    color=below_label_color,
                    arrowprops=dict(arrowstyle="-", color=below_label_color,
                                    lw=0.5, alpha=0.6))

    geomean_label_color = GREEN if (geomean > 1) == good_when_above else RED
    ax.text(n * 0.55, geomean, f"{summary_metric_label}: {geomean:.3f}×",
            fontsize=9, va="bottom", ha="center", color=geomean_label_color,
            backgroundcolor="white")

    ax.set_xlabel("Queries (sorted)", fontsize=10)
    ax.set_ylabel(ylabel, fontsize=10)
    ax.set_title(title, fontsize=12, pad=10, color=INK)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_xticks([])
    ax.set_xlim(-1, n)
    if yscale == "log":
        ax.set_yscale("log")
        ymin = max(ratios.min() * 0.85, 1e-3)
        ymax = ratios.max() * 1.18
        ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{y:g}×"))
    else:
        ymin = max(0, ratios.min() * 0.85)
        ymax = max(ratios.max(), 1.05) * 1.15
    ax.set_ylim(ymin, ymax)
    ax.grid(axis="y", alpha=0.3, linewidth=0.5, color=GRID, which="both")

    fig.text(0.5, 0.01,
             f"{n} queries  •  {n_good} {summary_word_good}  •  "
             f"{n_bad} {summary_word_bad}  •  {summary_metric_label}: {geomean:.3f}×",
             ha="center", fontsize=9, color=INK)

    fig.tight_layout(rect=[0, 0.03, 1, 1])
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    print(f"wrote {out_path}")


def paired_bar_plot(rows, out_path, *, title, ylabel, unit, divisor,
                    sort_by="baseline", split=1):
    """Back-to-back bars: Robust above the center axis, Baseline below it (inverted).
    Both halves use log y-scale; sort queries by baseline magnitude (default) or by
    ratio. `split` > 1 → N stacked panels of contiguous query chunks."""
    import matplotlib.gridspec as gridspec

    if sort_by == "ratio":
        rows_sorted = sorted(rows, key=lambda r: r["ratio"])
    else:
        rows_sorted = sorted(rows, key=lambda r: -r["baseline"])
    n = len(rows_sorted)
    chunk = (n + split - 1) // split

    fig = plt.figure(figsize=(7.8, 3.2 * split))
    outer = gridspec.GridSpec(split, 1, figure=fig, hspace=0.45)

    # consistent y-limits across panels: pick global max/min so all panels share scale
    bvals_all = np.array([r["baseline"] / divisor for r in rows_sorted])
    rvals_all = np.array([r["robust"] / divisor for r in rows_sorted])
    ymax = max(bvals_all.max(), rvals_all.max()) * 1.15
    pos_min = min(bvals_all[bvals_all > 0].min() if (bvals_all > 0).any() else 1,
                  rvals_all[rvals_all > 0].min() if (rvals_all > 0).any() else 1)
    ymin = pos_min * 0.7

    for k in range(split):
        a, b = k * chunk, min((k + 1) * chunk, n)
        sub = rows_sorted[a:b]
        nn = len(sub)
        x = np.arange(nn)
        bvals = np.array([r["baseline"] / divisor for r in sub])
        rvals = np.array([r["robust"] / divisor for r in sub])

        inner = gridspec.GridSpecFromSubplotSpec(2, 1, subplot_spec=outer[k], hspace=0)
        ax_top = fig.add_subplot(inner[0])
        ax_bot = fig.add_subplot(inner[1], sharex=ax_top)

        ax_top.bar(x, rvals, color=GREEN, edgecolor="none", width=0.85, zorder=3)
        ax_top.set_yscale("log")
        ax_top.set_ylabel("Robust", fontsize=9, color=GREEN)
        ax_top.tick_params(labelbottom=False, length=0)
        ax_top.spines["top"].set_visible(False)
        ax_top.spines["right"].set_visible(False)
        ax_top.spines["bottom"].set_color(INK)
        ax_top.spines["bottom"].set_linewidth(0.9)
        ax_top.grid(axis="y", alpha=0.30, color=GRID, which="both", linewidth=0.4)
        ax_top.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{y:g}"))

        ax_bot.bar(x, bvals, color="#7a7a7a", edgecolor="none", width=0.85, zorder=3)
        ax_bot.set_yscale("log")
        ax_bot.invert_yaxis()
        ax_bot.set_ylabel("Baseline", fontsize=9, color="#444444")
        ax_bot.tick_params(length=0)
        ax_bot.set_xticks([])
        ax_bot.spines["top"].set_visible(False)
        ax_bot.spines["bottom"].set_visible(False)
        ax_bot.spines["right"].set_visible(False)
        ax_bot.grid(axis="y", alpha=0.30, color=GRID, which="both", linewidth=0.4)
        ax_bot.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{y:g}"))

        ax_top.set_ylim(ymin, ymax)
        ax_bot.set_ylim(ymax, ymin)
        ax_top.set_xlim(-0.5, max(nn - 0.5, 0.5))

        if split > 1:
            ax_top.text(0.005, 0.92, f"queries {a+1}–{b} of {n}",
                        transform=ax_top.transAxes, fontsize=8, color="#555555",
                        va="top", ha="left")

    fig.suptitle(title, fontsize=12, y=0.995)
    sort_caption = ("sorted by Robust/Baseline ratio (regressions left)"
                    if sort_by == "ratio"
                    else "sorted by baseline magnitude (largest left)")
    fig.text(0.5, 0.01, f"Queries — {sort_caption}   •   y-axis: {ylabel} ({unit})",
             ha="center", fontsize=9, color=INK)
    fig.tight_layout(rect=[0, 0.025, 1, 0.97])
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    print(f"wrote {out_path}")


def paired_curve_plot(rows, out_path, *, title, ylabel, unit, divisor,
                      sort_by="baseline", split=1):
    """Plot baseline and robust as two curves on shared axes, sorted by `sort_by`
    descending. Fills between to show per-query gap. `split` > 1 → N stacked subplots
    each covering a contiguous chunk of queries."""
    if sort_by == "ratio":
        rows_sorted = sorted(rows, key=lambda r: r["ratio"])  # asc: regressions left
    else:
        rows_sorted = sorted(rows, key=lambda r: -r["baseline"])  # desc: largest left
    n = len(rows_sorted)
    fig, axes = plt.subplots(split, 1, figsize=(7.5, 3.0 * split), squeeze=False)
    axes = axes.flatten()
    chunk = (n + split - 1) // split

    for k, ax in enumerate(axes):
        a, b = k * chunk, min((k + 1) * chunk, n)
        sub = rows_sorted[a:b]
        x = np.arange(b - a)
        bvals = np.array([r["baseline"] / divisor for r in sub])
        rvals = np.array([r["robust"] / divisor for r in sub])
        bvals = np.where(bvals <= 0, 1e-12, bvals)
        rvals = np.where(rvals <= 0, 1e-12, rvals)

        ax.plot(x, bvals, color="#777777", linewidth=1.0, label="Baseline", zorder=3)
        ax.plot(x, rvals, color=GREEN, linewidth=1.0, label="Robust", zorder=4)
        ax.fill_between(x, bvals, rvals, where=(rvals < bvals),
                        color=GREEN_FILL, alpha=0.30, interpolate=True, linewidth=0)
        ax.fill_between(x, bvals, rvals, where=(rvals > bvals),
                        color=RED_FILL, alpha=0.30, interpolate=True, linewidth=0)

        ax.set_yscale("log")
        ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{y:g}"))
        ax.set_ylabel(f"{ylabel}\n({unit})", fontsize=9)
        ax.set_xticks([])
        ax.set_xlim(-1, max(b - a, 1))
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(axis="y", alpha=0.3, linewidth=0.5, color=GRID, which="both")
        if k == 0:
            ax.legend(loc="upper right", frameon=False, fontsize=9)
        if split > 1:
            ax.text(0.01, 0.95, f"queries {a+1}–{b} of {n}",
                    transform=ax.transAxes, fontsize=8, color="#555555",
                    va="top", ha="left")

    fig.suptitle(title, fontsize=12)
    sort_caption = ("sorted by Robust/Baseline ratio" if sort_by == "ratio"
                    else "sorted by baseline magnitude (largest left)")
    fig.text(0.5, 0.01, f"Queries — {sort_caption}",
             ha="center", fontsize=9, color=INK)
    fig.tight_layout(rect=[0, 0.03, 1, 0.95])
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    print(f"wrote {out_path}")


def metric_totals_plot(rows, out_path, *, label, unit, divisor):
    """Bar chart of workload totals: baseline vs robust for any metric."""
    base_total = sum(r["baseline"] for r in rows) / divisor
    rob_total = sum(r["robust"] for r in rows) / divisor
    delta_pct = (rob_total - base_total) / base_total * 100 if base_total else 0

    fig, ax = plt.subplots(figsize=(4.0, 3.2))
    bars = ax.bar(["Baseline", "Robust"],
                  [base_total, rob_total],
                  color=["#888888", GREEN if rob_total < base_total else RED],
                  width=0.55, edgecolor=INK, linewidth=0.5)

    for b, v in zip(bars, [base_total, rob_total]):
        ax.text(b.get_x() + b.get_width() / 2, v,
                f"{v:.2f} {unit}", ha="center", va="bottom", fontsize=10)

    sign = "+" if delta_pct >= 0 else ""
    ax.set_title(f"{label}  ({sign}{delta_pct:.1f}%)",
                 fontsize=11, pad=10, color=INK)
    ax.set_ylabel(f"{unit} across workload", fontsize=10)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=0.3, linewidth=0.5, color=GRID)
    ax.set_ylim(0, max(base_total, rob_total) * 1.18)

    fig.tight_layout()
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    print(f"wrote {out_path}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("speedup")
    sp.add_argument("input")
    sp.add_argument("--out", required=True)
    sp.add_argument("--title", default="Robust Speedup — JOB Benchmark")
    sp.add_argument("--yscale", choices=["log", "linear"], default="log")

    mp = sub.add_parser("metric")
    mp.add_argument("metric", choices=list(METRIC_CONFIG.keys()))
    mp.add_argument("input")
    mp.add_argument("--out-ratio", required=True)
    mp.add_argument("--out-totals", required=True)
    mp.add_argument("--title", default=None,
                    help="override the default title for this metric")
    mp.add_argument("--yscale", choices=["log", "linear"], default="log")

    pp = sub.add_parser("pairs")
    pp.add_argument("metric", choices=list(METRIC_CONFIG.keys()))
    pp.add_argument("input")
    pp.add_argument("--out", required=True)
    pp.add_argument("--split", type=int, default=1,
                    help="split queries into N stacked sub-panels (default 1)")
    pp.add_argument("--sort-by", choices=["baseline", "ratio"], default="baseline",
                    help="sort queries by baseline magnitude (default) or by ratio")
    pp.add_argument("--style", choices=["bars", "line"], default="bars",
                    help="back-to-back bars (default) or sorted dual lines")
    pp.add_argument("--title", default=None)

    args = ap.parse_args()
    style()

    if args.cmd == "speedup":
        rows = parse_comparison(args.input)
        sorted_curve_plot(
            rows, args.out,
            title=args.title,
            ylabel="Speedup (Robust / Baseline)",
            good_when_above=True,
            summary_word_good="faster", summary_word_bad="slower",
            summary_metric_label="Geomean",
            yscale=args.yscale,
        )
    elif args.cmd == "metric":
        cfg = METRIC_CONFIG[args.metric]
        rows = parse_metric(args.input, cfg["csv_baseline"], cfg["csv_robust"])
        sorted_curve_plot(
            rows, args.out_ratio,
            title=args.title or cfg["title"],
            ylabel=cfg["ylabel"],
            good_when_above=True,  # above 1 = robust is leaner = good
            summary_word_good="leaner", summary_word_bad="heavier",
            summary_metric_label="Geomean",
            yscale=args.yscale,
        )
        metric_totals_plot(rows, args.out_totals,
                           label=cfg["totals_label"],
                           unit=cfg["totals_unit"],
                           divisor=cfg["totals_divisor"])
    elif args.cmd == "pairs":
        cfg = METRIC_CONFIG[args.metric]
        rows = parse_metric(args.input, cfg["csv_baseline"], cfg["csv_robust"])
        plot_fn = paired_bar_plot if args.style == "bars" else paired_curve_plot
        plot_fn(
            rows, args.out,
            title=args.title or cfg["title"],
            ylabel=cfg["totals_label"],
            unit=cfg["totals_unit"],
            divisor=cfg["totals_divisor"],
            sort_by=args.sort_by,
            split=args.split,
        )


if __name__ == "__main__":
    main()
