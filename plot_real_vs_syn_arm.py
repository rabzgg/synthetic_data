"""
plot_real_vs_syn_arm.py — overlay real vs synthetic orientation_x/y/z and acceleration_x/y/z per arm sensor.

Real = first 60 min of ppt/arm_robot/sensor_k_real.csv; synthetic = a joint-template file of the same
length. Both on elapsed time from their own first sample. Left: the whole hour; right: a 3-min zoom.
The synthetic replays real cycles from the same part of the session, but not in the same order and
from a random cycle phase, so in the zoom panel the synthetic trace is shifted in time (lag shown in
the panel) to put its cycles on the real ones: lag = argmax of the cross-correlation of orientation_y
on a 10 Hz grid, within ± one arm cycle (37 s). Lines are broken at gaps > 1 s.
Sensor -> arm-link mapping: [USER TO VERIFY].

Usage: python3 plot_real_vs_syn_arm.py --syn-dir out/robot_arm_joint_1h --seed 42 [--zoom 1200 1380] [--sensors 4 5 6]
"""
import argparse
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from core.joint_template import REAL_ALIASES, _abs_seconds

ap = argparse.ArgumentParser()
ap.add_argument("--syn-dir", required=True)
ap.add_argument("--seed", type=int, default=42)
ap.add_argument("--span", type=float, default=3600.0)
ap.add_argument("--zoom", type=float, nargs=2, default=[1200.0, 1380.0])
ap.add_argument("--out", default=os.path.join(ROOT, "results", "joint_template", "plots"))
ap.add_argument("--label", default="synthetic joint-template (60 min)", help="name of the synthetic data in the title")
ap.add_argument("--sensors", type=int, nargs="+", default=[1, 2, 3])
args = ap.parse_args()
os.makedirs(args.out, exist_ok=True)

COLS = [("orientation_x", "orientation x"), ("orientation_y", "orientation y"), ("orientation_z", "orientation z"),
        ("acceleration_x", "accel x [g]"), ("acceleration_y", "accel y [g]"), ("acceleration_z", "accel z [g]")]


def load(path, span):
    d = pd.read_csv(path).rename(columns=REAL_ALIASES)
    t = _abs_seconds(d["timestamp"])
    d["t"] = t - t[0]
    return d[d["t"] < span].reset_index(drop=True)


def gapped(t, y, gap=1.0):
    """Insert NaN where consecutive samples are more than `gap` s apart, so gaps are not bridged."""
    t, y = np.asarray(t, float), np.asarray(y, float)
    br = np.where(np.diff(t) > gap)[0] + 1
    return np.insert(t, br, np.nan), np.insert(y, br, np.nan)


def phase_lag(real, syn, lo, hi, col="orientation_y", max_lag=37.0):
    g = np.arange(lo, hi, 0.1)
    r = np.interp(g, real["t"], real[col])
    best, lag_best = -np.inf, 0.0
    for lag in np.arange(-max_lag, max_lag + 0.05, 0.1):
        sv = np.interp(g + lag, syn["t"], syn[col])
        c = np.corrcoef(r, sv)[0, 1]
        if c > best:
            best, lag_best = c, lag
    return lag_best, best


for k in args.sensors:
    real = load(os.path.join(ROOT, "ppt", "arm_robot", f"sensor_{k}_real.csv"), args.span)
    syn = load(os.path.join(args.syn_dir, f"sensor_{k}_seed{args.seed}.csv"), args.span)
    lag, cc = phase_lag(real, syn, *args.zoom)
    fig, ax = plt.subplots(6, 2, figsize=(16, 15), sharex="col", gridspec_kw={"width_ratios": [3, 2]})
    for i, (c, lbl) in enumerate(COLS):
        for j, (lo, hi) in enumerate(((0, args.span), tuple(args.zoom))):
            a = ax[i, j]
            for d, name, col, lw, al, sh in ((real, "real", "black", 0.6, 0.8, 0.0),
                                             (syn, f"synthetic (seed {args.seed})", "tab:orange", 0.6, 0.7, lag if j else 0.0)):
                tt = d["t"] - sh                          # zoom: synthetic shifted onto the real cycle phase
                m = (tt >= lo) & (tt < hi)
                x, y = gapped(tt[m], d[c][m])
                a.plot(x / 60.0 if j == 0 else x, y, color=col, lw=lw if j == 0 else 1.0, alpha=al, label=name)
            if j == 0:
                a.set_ylabel(lbl)
            if i == 0:
                a.set_title("whole hour" if j == 0 else
                            f"zoom {args.zoom[0] / 60:.0f}–{args.zoom[1] / 60:.0f} min (synthetic shifted {lag:+.1f} s to align cycle phase)")
            a.grid(alpha=0.3)
    ax[-1, 0].set_xlabel("elapsed time [min]")
    ax[-1, 1].set_xlabel("elapsed time [s]")
    ax[0, 1].legend(loc="upper right", fontsize=9)
    fig.suptitle(f"sensor_{k}: real (first 60 min) vs {args.label} — orientation and acceleration\n"
                 f"(sensor → arm-link mapping: [USER TO VERIFY])", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    p = os.path.join(args.out, f"sensor_{k}_orientation_accel_real_vs_syn.png")
    fig.savefig(p, dpi=110)
    plt.close(fig)
    print("wrote", os.path.relpath(p, ROOT))
