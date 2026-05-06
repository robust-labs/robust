#!/usr/bin/env python3
"""Plot benchmark results in publication-ready style.

Usage:
    plot_results.py speedup <comparison.tsv> --out <file.pdf|png> [--title "..."]
    plot_results.py memory  <memory.csv>     --out-ratio <file> --out-totals <file>
"""
import argparse
import csv
import math
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
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


def parse_memory(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            b = float(r["baseline_bytes"])
            x = float(r["robust_bytes"])
            rows.append({
                "query": r["query"],
                "baseline": b,
                "robust": x,
                # ratio = robust / baseline → <1 means robust uses less
                "ratio": (x / b) if b > 0 else float("nan"),
            })
    return [r for r in rows if not math.isnan(r["ratio"])]


def sorted_curve_plot(rows, out_path, *,
                      title, ylabel,
                      good_when_above=True,
                      annotate_top=3, annotate_bot=3,
                      summary_word_good="faster", summary_word_bad="slower",
                      summary_metric_label="Geomean"):
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
    ymax = max(ratios.max(), 1.05) * 1.15
    ymin = max(0, ratios.min() * 0.85)
    ax.set_ylim(ymin, ymax)
    ax.grid(axis="y", alpha=0.3, linewidth=0.5, color=GRID)

    fig.text(0.5, 0.01,
             f"{n} queries  •  {n_good} {summary_word_good}  •  "
             f"{n_bad} {summary_word_bad}  •  {summary_metric_label}: {geomean:.3f}×",
             ha="center", fontsize=9, color=INK)

    fig.tight_layout(rect=[0, 0.03, 1, 1])
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    print(f"wrote {out_path}")


def memory_totals_plot(rows, out_path):
    """Bar chart of workload totals: baseline vs robust memory."""
    base_total = sum(r["baseline"] for r in rows) / (1024 ** 3)  # GB
    rob_total = sum(r["robust"] for r in rows) / (1024 ** 3)
    delta_pct = (rob_total - base_total) / base_total * 100 if base_total else 0

    fig, ax = plt.subplots(figsize=(4.0, 3.2))
    bars = ax.bar(["Baseline", "Robust"],
                  [base_total, rob_total],
                  color=["#888888", GREEN if rob_total < base_total else RED],
                  width=0.55, edgecolor=INK, linewidth=0.5)

    for b, v in zip(bars, [base_total, rob_total]):
        ax.text(b.get_x() + b.get_width() / 2, v,
                f"{v:.2f} GB", ha="center", va="bottom", fontsize=10)

    sign = "+" if delta_pct >= 0 else ""
    ax.set_title(f"Total Memory Allocated  ({sign}{delta_pct:.1f}%)",
                 fontsize=11, pad=10, color=INK)
    ax.set_ylabel("GB across workload", fontsize=10)
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

    mp = sub.add_parser("memory")
    mp.add_argument("input")
    mp.add_argument("--out-ratio", required=True)
    mp.add_argument("--out-totals", required=True)
    mp.add_argument("--title", default="Robust Memory — JOB Benchmark")

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
        )
    elif args.cmd == "memory":
        rows = parse_memory(args.input)
        sorted_curve_plot(
            rows, args.out_ratio,
            title=args.title,
            ylabel="Memory ratio (Robust / Baseline)",
            good_when_above=False,  # below 1 = uses less = good
            summary_word_good="lower", summary_word_bad="higher",
            summary_metric_label="Geomean",
        )
        memory_totals_plot(rows, args.out_totals)


if __name__ == "__main__":
    main()
