"""
generate.py — one command from a scenario to files: CSV, labels, manifest and gate per device.

Usage: python3 cli/generate.py --scenario fridge_compressor_failure --seed 42 --out out/fridge
       python3 cli/generate.py --scenario worker_collapse --seed 7 --devices blackline_g7c bme280_sensor_board:fixed
       python3 cli/generate.py --list
Exit code 1 if a device fails its gate.
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.events import list_scenarios
from core.output import run


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario")
    ap.add_argument("--seed", type=int, default=None, help="default: the scenario's seed")
    ap.add_argument("--out", default=os.path.join(ROOT, "out"))
    ap.add_argument("--duration", type=float, default=None, help="seconds (default: the scenario's)")
    ap.add_argument("--devices", nargs="*", help="slug or slug:fixed / slug:body, replacing the scenario's devices")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    if args.list or not args.scenario:
        print("\n".join(list_scenarios()))
        return
    devices = None
    if args.devices:
        devices = [{"device": d.split(":")[0], "mount": (d.split(":") + ["body"])[1]} for d in args.devices]
    ok = True
    for r in run(args.scenario, seed=args.seed, out_dir=args.out, devices=devices, duration_s=args.duration):
        ok &= r.get("passed", True)
        print(f"{r['device']}: gate {'PASSED' if r.get('passed') else 'FAILED'}  ->  {os.path.relpath(r['csv'], ROOT)}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
