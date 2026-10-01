"""
eval_plots.py — presentation-ready real-vs-synthetic comparison figures.

Draws real vs synthetic with different colors, on shared axes by default (an
overlay), because side-by-side panels make it impossible to judge whether two
signals actually match. Modes:

  (default)   one figure per column with 4 panels: time-series overlay, box plot,
              histogram overlay, ACF overlay.
  --single    ONE plot per column: just the time-series overlay.
  --split     ONE image per column, 2 stacked panels (real top / synthetic
              bottom, shared y-limits). Best for quantized / duty-cycle columns
              like acceleration_z where an overlay is an unreadable mess.
  --combined  ONE image for ALL --cols together, one stacked overlay panel per
              column (e.g. the whole environment group in a single figure).

X-axis:
  By default the x-axis is NORMALIZED time [0,1] so two recordings of different
  length line up. Pass --time-axis to use REAL elapsed time (minutes) instead,
  so a shorter recording visibly ends earlier than a longer one.

A column that is dead in the real data (constant / all ~0, e.g. a stuck channel)
is drawn but LABELLED as a dead channel instead of an empty axis.

Usage
-----
python3 eval_plots.py --real REAL.csv --syn SYN.csv --cols A B C --out plots/

Options
-------
--real       path to the real recording CSV                       (required)
--syn        path to the synthetic CSV                            (required)
--cols       one or more column names to plot                     (required)
--out        output directory for the PNGs                        (default: plots/)
--label-real name for the real series in legends                  (default: real)
--label-syn  name for the synthetic series in legends            (default: synthetic)
--single     one overlay plot per column (no box/hist/ACF)
--split      2-panel real/synthetic per column (for spiky columns)
--combined   all --cols in one image, one overlay panel each
--name       output basename for --combined                       (default: group)
--title      figure title for --combined
--time-axis  x-axis = real elapsed minutes instead of normalized [0,1]
--max-lag    max autocorrelation lag                              (default: 300)
--points     max points drawn per series in overlay/single modes  (default: 4000)
             (split & combined draw at full resolution)

Example
-------
python3 eval_plots.py \
    --real ppt/fridge/fridge_xdk1_real.csv \
    --syn  ppt/fridge/fridge_xdk1_syn.csv \
    --cols temperature light humidity pressure \
    --combined --name fridge_environment --time-axis --out ppt/fridge
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stat_eval import autocorr  # reuse the same ACF used by the metrics

REAL_COLOR = "steelblue"
SYN_COLOR = "darkorange"
DEAD_EPS = 1e-9        # a real column whose range is below this is a dead channel
FULL_CAP = 200_000     # split/combined draw full-res up to this many points


def _read_columns(path):
    df = pd.read_csv(path)
    df.columns = [str(c).strip().strip('"') for c in df.columns]
    return df


def load_series(path, col):
    """Just the numeric values of one column (NaNs dropped)."""
    df = _read_columns(path)
    if col not in df.columns:
        print(f"Error: column '{col}' not in {path}")
        print(f"  Available: {[c for c in df.columns if c != 'timestamp']}")
        sys.exit(1)
    return pd.to_numeric(df[col], errors="coerce").dropna().to_numpy(dtype=float)


def load_xy(path, col, time_axis):
    """Return (x, y) for one column.

    time_axis=False -> x is normalized [0,1] (two recordings line up).
    time_axis=True  -> x is REAL elapsed minutes from that recording's own start,
                       so a shorter recording ends earlier on the axis.
    """
    df = _read_columns(path)
    if col not in df.columns:
        print(f"Error: column '{col}' not in {path}")
        print(f"  Available: {[c for c in df.columns if c != 'timestamp']}")
        sys.exit(1)

    if not time_axis:
        y = pd.to_numeric(df[col], errors="coerce").dropna().to_numpy(dtype=float)
        return np.linspace(0.0, 1.0, len(y)), y

    tcol = "timestamp" if "timestamp" in df.columns else df.columns[0]
    sub = df[[tcol, col]].copy()
    sub[tcol] = pd.to_numeric(sub[tcol], errors="coerce")
    sub[col] = pd.to_numeric(sub[col], errors="coerce")
    sub = sub.dropna()
    ts = sub[tcol].to_numpy(dtype=float)
    y = sub[col].to_numpy(dtype=float)
    if len(ts) < 2:
        return np.zeros(len(ts)), y
    # Convert elapsed time to MINUTES. Timestamps may be epoch or relative, in
    # milliseconds or seconds, so detect the UNIT from the median sample step
    # (subtracting ts[0] first makes epoch-vs-relative irrelevant): these sensors
    # sample every ~0.1-0.5 s, so a median step >= 10 means milliseconds.
    dt = float(np.median(np.diff(ts)))
    div = 60000.0 if dt >= 10 else 60.0   # ms->min or s->min
    x = (ts - ts[0]) / div
    return x, y


def downsample_xy(x, y, max_points):
    """Stride (x, y) down to at most max_points, keeping them aligned."""
    n = len(y)
    if n <= max_points:
        return x, y
    step = int(np.ceil(n / max_points))
    return x[::step], y[::step]


def xlabel_for(time_axis):
    return ("elapsed time (minutes, from each recording's own start)"
            if time_axis else
            "normalized time (0 = start, 1 = end of each recording)")


def _is_dead(y):
    return len(y) == 0 or float(y.max() - y.min()) < DEAD_EPS


def _dead_text(ax, col=None):
    msg = "DEAD CHANNEL\n(real signal is constant ~0)"
    if col:
        msg = f"{col}: DEAD CHANNEL (real constant ~0)"
    ax.text(0.5, 0.5, msg, ha="center", va="center", fontsize=11,
            color="gray", transform=ax.transAxes)
    ax.set_xticks([]); ax.set_yticks([])


# ── Figure builders ──────────────────────────────────────────────────────────

def make_single_figure(col, xr, yr, xs, ys, args):
    """ONE plot: real vs synthetic time series overlaid, different colors."""
    import matplotlib.pyplot as plt
    lbl_r, lbl_s = args.label_real, args.label_syn
    fig, ax = plt.subplots(figsize=(13, 5))

    if _is_dead(yr):
        _dead_text(ax)
        ax.set_title(f"{col} — dead channel in real data (nothing to compare)")
        return fig

    xr, yr = downsample_xy(xr, yr, args.points)
    xs, ys = downsample_xy(xs, ys, args.points)
    ax.plot(xr, yr, color=REAL_COLOR, lw=0.8, alpha=0.7, label=lbl_r)
    ax.plot(xs, ys, color=SYN_COLOR, lw=0.8, alpha=0.7, label=lbl_s)
    ax.set_title(f"{col} — real vs synthetic")
    ax.set_xlabel(xlabel_for(args.time_axis)); ax.set_ylabel(col)
    ax.legend(loc="upper right", fontsize=10); ax.grid(alpha=0.3)
    fig.tight_layout()
    return fig


def make_split_figure(col, xr, yr, xs, ys, args):
    """ONE image, 2 stacked panels: real (top) and synthetic (bottom).

    Full resolution: for duty-cycle / quantized columns (compressor vibration in
    acceleration_z) the on/off block structure only survives if every point is
    drawn — striding to a few thousand points smears the blocks into noise.
    """
    import matplotlib.pyplot as plt
    lbl_r, lbl_s = args.label_real, args.label_syn
    fig, (a0, a1) = plt.subplots(2, 1, figsize=(13, 6), sharex=True)

    if _is_dead(yr):
        _dead_text(a0); _dead_text(a1)
        fig.suptitle(f"{col} — dead channel in real data (nothing to compare)")
        return fig

    xr, yr = downsample_xy(xr, yr, FULL_CAP)
    xs, ys = downsample_xy(xs, ys, FULL_CAP)
    a0.plot(xr, yr, color=REAL_COLOR, lw=0.4); a0.set_ylabel(lbl_r)
    a0.set_title(f"{col} — {lbl_r} (n={len(yr)})", fontsize=10)
    a1.plot(xs, ys, color=SYN_COLOR, lw=0.4); a1.set_ylabel(lbl_s)
    a1.set_title(f"{col} — {lbl_s} (n={len(ys)})", fontsize=10)

    lo = float(min(yr.min(), ys.min())); hi = float(max(yr.max(), ys.max()))
    pad = (hi - lo) * 0.05 or 1.0
    for ax in (a0, a1):
        ax.set_ylim(lo - pad, hi + pad); ax.grid(alpha=0.3)
    a1.set_xlabel(xlabel_for(args.time_axis))
    fig.suptitle(f"{col} — real vs synthetic (separate panels)", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    return fig


def make_combined_figure(cols, data, args):
    """ONE image, one stacked overlay panel per column (real vs synthetic)."""
    import matplotlib.pyplot as plt
    lbl_r, lbl_s = args.label_real, args.label_syn
    n = len(cols)
    fig, axes = plt.subplots(n, 1, figsize=(12, 2.4 * n + 0.6), squeeze=False)
    axes = axes[:, 0]

    for ax, col in zip(axes, cols):
        xr, yr, xs, ys = data[col]
        if _is_dead(yr):
            _dead_text(ax, col)
            continue
        xr, yr = downsample_xy(xr, yr, FULL_CAP)
        xs, ys = downsample_xy(xs, ys, FULL_CAP)
        ax.plot(xr, yr, color=REAL_COLOR, lw=0.6, alpha=0.75, label=lbl_r)
        ax.plot(xs, ys, color=SYN_COLOR, lw=0.6, alpha=0.75, label=lbl_s)
        ax.set_ylabel(col); ax.grid(alpha=0.3)
        ax.legend(loc="upper right", fontsize=8)

    axes[-1].set_xlabel(xlabel_for(args.time_axis))
    fig.suptitle(args.title or f"{args.name} — real vs synthetic", fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.99))
    return fig


def make_figure(col, xr, yr, xs, ys, args):
    """Default 4-panel figure: time-series overlay + box + histogram + ACF."""
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec

    lbl_r, lbl_s = args.label_real, args.label_syn
    fig = plt.figure(figsize=(15, 8))
    gs = GridSpec(2, 3, figure=fig, height_ratios=[1.1, 1.0], hspace=0.32, wspace=0.28)
    ax_ts = fig.add_subplot(gs[0, :])
    ax_box = fig.add_subplot(gs[1, 0])
    ax_hist = fig.add_subplot(gs[1, 1])
    ax_acf = fig.add_subplot(gs[1, 2])

    if _is_dead(yr):
        for ax in (ax_ts, ax_box, ax_hist, ax_acf):
            _dead_text(ax)
        fig.suptitle(f"{col} — dead channel in real data (nothing to compare)", fontsize=14)
        return fig

    xr_d, yr_d = downsample_xy(xr, yr, args.points)
    xs_d, ys_d = downsample_xy(xs, ys, args.points)
    ax_ts.plot(xr_d, yr_d, color=REAL_COLOR, lw=0.7, alpha=0.6, label=lbl_r)
    ax_ts.plot(xs_d, ys_d, color=SYN_COLOR, lw=0.7, alpha=0.6, label=lbl_s)
    ax_ts.set_title(f"{col} — time series overlay (real n={len(yr)}, syn n={len(ys)})")
    ax_ts.set_xlabel(xlabel_for(args.time_axis)); ax_ts.set_ylabel(col)
    ax_ts.legend(loc="upper right", fontsize=9); ax_ts.grid(alpha=0.3)

    bp = ax_box.boxplot([yr, ys], patch_artist=True, showfliers=False, widths=0.5)
    ax_box.set_xticks([1, 2]); ax_box.set_xticklabels([lbl_r, lbl_s])
    for patch, c in zip(bp["boxes"], (REAL_COLOR, SYN_COLOR)):
        patch.set_facecolor(c); patch.set_alpha(0.55)
    for med in bp["medians"]:
        med.set_color("black")
    ax_box.set_title("box plot (value spread)"); ax_box.grid(alpha=0.3, axis="y")

    ax_hist.hist(yr, bins=60, density=True, alpha=0.55, color=REAL_COLOR, label=lbl_r)
    ax_hist.hist(ys, bins=60, density=True, alpha=0.55, color=SYN_COLOR, label=lbl_s)
    ax_hist.set_title("value distribution (overlay)")
    ax_hist.set_xlabel(col); ax_hist.set_ylabel("density")
    ax_hist.legend(fontsize=8); ax_hist.grid(alpha=0.3)

    acf_r = autocorr(yr, args.max_lag)
    acf_s = autocorr(ys, args.max_lag)
    ax_acf.plot(acf_r, color=REAL_COLOR, label=lbl_r)
    ax_acf.plot(acf_s, color=SYN_COLOR, label=lbl_s)
    acf_diff = float(np.mean(np.abs(acf_r - acf_s)))
    ax_acf.set_title(f"autocorrelation overlay (ACF diff = {acf_diff:.3f})")
    ax_acf.set_xlabel("lag"); ax_acf.set_ylabel("autocorrelation")
    ax_acf.legend(fontsize=8); ax_acf.grid(alpha=0.3)

    fig.suptitle(f"{col} — real vs synthetic", fontsize=14)
    return fig


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Overlaid real-vs-synthetic comparison figures.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example:\n  python3 eval_plots.py --real real.csv --syn syn.csv "
               "--cols temperature pressure --out plots/")
    ap.add_argument("--real", required=True, help="Path to the real recording CSV")
    ap.add_argument("--syn", required=True, help="Path to the synthetic CSV")
    ap.add_argument("--cols", nargs="+", required=True, help="Column name(s) to plot")
    ap.add_argument("--out", default="plots/", help="Output directory (default: plots/)")
    ap.add_argument("--label-real", default="real", help="Legend name for real series")
    ap.add_argument("--label-syn", default="synthetic", help="Legend name for synthetic series")
    ap.add_argument("--single", action="store_true",
                    help="ONE overlay plot per column (no box/histogram/ACF panels)")
    ap.add_argument("--split", action="store_true",
                    help="ONE image, 2 stacked panels real/synthetic per column "
                         "(best for quantized/spiky columns like acceleration_z)")
    ap.add_argument("--combined", action="store_true",
                    help="ONE image for ALL --cols together, one overlay panel each")
    ap.add_argument("--name", default="group",
                    help="Output basename for --combined (default: group -> group_compare.png)")
    ap.add_argument("--title", default=None, help="Figure title for --combined mode")
    ap.add_argument("--time-axis", action="store_true",
                    help="X-axis = real elapsed minutes instead of normalized [0,1], "
                         "so a shorter recording visibly ends earlier")
    ap.add_argument("--max-lag", type=int, default=300, help="Max autocorrelation lag (default 300)")
    ap.add_argument("--points", type=int, default=4000,
                    help="Max points per series in overlay/single modes (default 4000)")
    args = ap.parse_args()

    for p in (args.real, args.syn):
        if not os.path.exists(p):
            print(f"Error: file not found: {p}")
            sys.exit(1)

    os.makedirs(args.out, exist_ok=True)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if args.combined:
        data = {}
        for col in args.cols:
            xr, yr = load_xy(args.real, col, args.time_axis)
            xs, ys = load_xy(args.syn, col, args.time_axis)
            data[col] = (xr, yr, xs, ys)
        fig = make_combined_figure(args.cols, data, args)
        out_path = os.path.join(args.out, f"{args.name}_compare.png")
        fig.savefig(out_path, dpi=130, bbox_inches="tight")
        plt.close(fig)
        print(f"  {args.name} ({', '.join(args.cols)}) -> {out_path}")
        print(f"\nDone. 1 combined figure in {args.out}")
        return

    for col in args.cols:
        xr, yr = load_xy(args.real, col, args.time_axis)
        xs, ys = load_xy(args.syn, col, args.time_axis)
        if args.split:
            fig = make_split_figure(col, xr, yr, xs, ys, args)
        elif args.single:
            fig = make_single_figure(col, xr, yr, xs, ys, args)
        else:
            fig = make_figure(col, xr, yr, xs, ys, args)
        out_path = os.path.join(args.out, f"{col}_compare.png")
        fig.savefig(out_path, dpi=130, bbox_inches="tight")
        plt.close(fig)
        print(f"  {col:<18} -> {out_path}")

    print(f"\nDone. {len(args.cols)} figure(s) in {args.out}")


if __name__ == "__main__":
    main()
