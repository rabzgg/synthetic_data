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
    w = World(preset, hours * 3600, seed)
    ta = np.arange(0, hours * 3600 + 1, w.air_dt)
    tb = np.arange(0, hours * 3600, w.body_dt)
    xa, xb = w.timestamps(ta).astype("datetime64[ms]").astype(object), w.timestamps(tb).astype("datetime64[ms]").astype(object)
    fig, ax = plt.subplots(6, 1, figsize=(13, 15), sharex=True)

    def twin(a, x, y1, l1, c1, y2, l2, c2):
        a.plot(x, y1, color=c1, lw=1)
        a.set_ylabel(l1, color=c1)
        b = a.twinx()
        b.plot(x, y2, color=c2, lw=1)
        b.set_ylabel(l2, color=c2)
        a.ticklabel_format(axis="y", useOffset=False)
        b.ticklabel_format(axis="y", useOffset=False)
    twin(ax[0], xa, w.at("air.temperature_c", ta), "Temperature (°C)", "tab:red",
         w.at("air.humidity_rh", ta), "Relative humidity (%RH)", "tab:blue")
    twin(ax[1], xa, w.at("air.pressure_hpa", ta), "Pressure (hPa)", "tab:purple",
         w.at("altitude_m", ta), "Device altitude (m)", "tab:gray")
    twin(ax[2], xa, w.at("air.co2_ppm", ta), "CO₂ (ppm)", "tab:brown", w.at("air.o2_pct", ta), "O₂ (%vol)", "tab:cyan")
    ax[3].plot(xa, w.at("light.lux", ta), color="goldenrod", lw=1)
    ax[3].set_ylabel("Light (lx)")
    f = w.at("body.accel_g", tb)
    g = w.at("body.gyro_dps", tb)
    for k, (c, lab) in enumerate(zip(("tab:red", "tab:green", "tab:blue"), "xyz")):
        ax[4].plot(xb, f[:, k], color=c, lw=0.4, label=lab)
        ax[5].plot(xb, g[:, k], color=c, lw=0.4, label=lab)
    ax[4].set_ylabel("Specific force,\nworld frame (g)")
    ax[5].set_ylabel("Angular rate,\nworld frame (°/s)")
    ax[4].legend(loc="upper right", ncol=3, fontsize=8)
    walking = w.state_at(tb) == "walk"
    for a in ax:
        a.fill_between(xb, 0, 1, where=walking, color="tab:green", alpha=0.12, lw=0, transform=a.get_xaxis_transform())
        a.grid(alpha=0.3)
    ax[-1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax[-1].set_xlabel("Time (UTC)" + ("   ·   green: walking" if walking.any() else ""))
    d = w.describe()
    fig.suptitle(f"World: {d['title']} · seed {seed} · first {hours:g} h · realism: {d['realism']}\n"
                 "raw world values, before any sensor (no noise, no resolution)", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    os.makedirs(out_dir, exist_ok=True)
    p = os.path.join(out_dir, f"world_{preset}_{hours:g}h.png")
    fig.savefig(p, dpi=90)
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
