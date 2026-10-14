"""
plot_gas.py — figures for the gas detector CSVs in data/gas/ (same figure as the UI).

Usage: python3 cli/plot_gas.py --all                  (every data/gas/<device>_shift_seed<seed>.csv)
       python3 cli/plot_gas.py --device blackline_g8 --seed 42
Output: data/gas/plots/<device>_shift_seed<seed>.png
"""
import argparse
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.gas_detector import coverage_items
from core.profiles.gas import SCENARIOS, GasDetectorProfile, gas_devices

DATA = os.path.join(ROOT, "data", "gas")
ITEM_NAMES = {items[0]: label.replace("Test: ", "") for items, label in SCENARIOS.values() if items}


def scenario_text(p, seed):
    """'Normal shift', plus the coverage-plan items placed on this seed."""
    items = coverage_items(p.device, seed, p.A)
    return "Normal shift" + (" + test item: " + ", ".join(ITEM_NAMES[i] for i in items) if items else "")


def plot(device, seed):
    p = GasDetectorProfile(device)
    out = os.path.join(DATA, "plots", f"{device}_shift_seed{seed}.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    p.plot_file(os.path.join(DATA, f"{device}_shift_seed{seed}.csv"),
                f"{p.label} · {scenario_text(p, seed)} · seed {seed} · synthetic, datasheet-based", out)
    print(os.path.relpath(out, ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", choices=gas_devices())
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    if args.all:
        for f in sorted(glob.glob(os.path.join(DATA, "*_shift_seed*.csv"))):
            m = re.match(r"(.+)_shift_seed(\d+)\.csv$", os.path.basename(f))
            plot(m.group(1), int(m.group(2)))
    elif args.device:
        plot(args.device, args.seed)
    else:
        ap.error("give --device or --all")


if __name__ == "__main__":
    main()
