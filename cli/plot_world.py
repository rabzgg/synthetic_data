"""
plot_world.py — the raw world of a preset (before any sensor), to check it by eye.

Usage: python3 cli/plot_world.py --preset indoor_worker_walking [--hours 1] [--seed 42] [--out docs/figures]
       python3 cli/plot_world.py --all
Output: <out>/world_<preset>_<hours>h.png
"""
import argparse
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.world import World, list_presets


def plot(preset, hours, seed, out_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from core.quantities import CATALOG
    w = World(preset, hours * 3600, seed)
    ta = np.arange(0, hours * 3600 + 1, w.air_dt)
    tb = np.arange(0, hours * 3600, w.body_dt)
    xa, xb = w.timestamps(ta).astype("datetime64[ms]").astype(object), w.timestamps(tb).astype("datetime64[ms]").astype(object)
    scalars = [q for q in w.quantities() if not CATALOG[q].vector]
    moving = not w.motion_state.constant
    panels = scalars + (["body.accel_g", "body.gyro_dps"] if moving else [])
    fig, ax = plt.subplots(len(panels), 1, figsize=(13, 2.0 * len(panels) + 1.2), sharex=True, squeeze=False)
    ax = ax[:, 0]
    for a, q in zip(ax, panels):
        c = CATALOG[q]
        if c.vector:
            f = w.at(q, tb)
            for k, (col, lab) in enumerate(zip(("tab:red", "tab:green", "tab:blue"), "xyz")):
                a.plot(xb, f[:, k], color=col, lw=0.4, label=lab)
            a.legend(loc="upper right", ncol=3, fontsize=8)
            a.set_ylabel(f"{c.name},\nworld frame ({c.unit})")
        else:
            a.plot(xa, w.at(q, ta), color="tab:blue", lw=1)
            a.set_ylabel(f"{c.name}\n({c.unit})")
            a.ticklabel_format(axis="y", useOffset=False)
        a.grid(alpha=0.3)
    walking = w.state_at(tb) == "walk" if moving else np.zeros(len(tb), bool)
    if walking.any():
        for a in ax:
            a.fill_between(xb, 0, 1, where=walking, color="tab:green", alpha=0.12, lw=0, transform=a.get_xaxis_transform())
    ax[-1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax[-1].set_xlabel("Time (UTC)" + ("   ·   green: walking" if walking.any() else ""))
    d = w.describe()
    fig.suptitle(f"World: {d['title']} · seed {seed} · first {hours:g} h · realism: {d['realism']}\n"
                 "raw world values, before any sensor (no noise, no resolution)", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    os.makedirs(out_dir, exist_ok=True)
    p = os.path.join(out_dir, f"world_{preset}_{hours:g}h.png")
    fig.savefig(p, dpi=80)
    plt.close(fig)
    print(os.path.relpath(p, ROOT))
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", choices=list_presets())
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--hours", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "figures"))
    args = ap.parse_args()
    for p in (list_presets() if args.all else [args.preset]):
        plot(p, args.hours, args.seed, args.out)


if __name__ == "__main__":
    main()
