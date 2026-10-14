"""
generate_gas.py — generate gas detector data from a datasheet spec (core/gas_detector.py).

Usage: python3 cli/generate_gas.py --device blackline_g7c [--duration 28800] [--seed 42] [--output path.csv]
       python3 cli/generate_gas.py --all          (every device in configs/gas/, one shift each)
Default output: data/gas/<device>_shift_seed<seed>.csv
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.gas_detector import GasDetectorEngine, _v, load_device

CONFIGS = os.path.join(ROOT, "configs")


def devices():
    d = os.path.join(CONFIGS, "gas")
    return sorted(x for x in os.listdir(d) if os.path.isfile(os.path.join(d, x, "spec.json")))


def run(device, duration, seed, output=None):
    spec, assumptions = load_device(device, CONFIGS)
    eng = GasDetectorEngine(spec, assumptions)
    duration = duration or float(_v(assumptions["shift"]["duration_s"]))
    df = eng.generate(duration, seed)
    output = output or os.path.join(ROOT, "data", "gas", f"{device}_shift_seed{seed}.csv")
    eng.write_csv(df, output)
    kinds = [e["kind"] for e in eng.events]
    print(f"{device}: {len(df)} rows -> {os.path.relpath(output, ROOT)}; events: {', '.join(kinds)}")
    return output


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", choices=devices())
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--duration", type=float, default=None, help="seconds (default: one shift from assumptions.json)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--output", default=None)
    args = ap.parse_args()
    if not args.all and not args.device:
        ap.error("give --device or --all")
    for d in (devices() if args.all else [args.device]):
        run(d, args.duration, args.seed, None if args.all else args.output)


if __name__ == "__main__":
    main()
