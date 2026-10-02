"""
regression_arm.py — regression harness for the robot-arm generator.

1. Flag OFF: regenerate the deck configs (sensor_k_normal.json, 3600 s, seed 42) and compare
   with ppt/arm_robot/sensor_k_syn.csv byte for byte. Known pre-existing difference: sensor_1
   'temperature' already differed before the joint-template work (older GradualCurve change);
   every other column must match exactly.
2. Flag ON: generate sensor_1/2/3 with the joint-template configs for each seed and run the
   full physics gate (per-sensor + cross-sensor). Report pass/fail per seed.
3. Compare the seed-42 joint outputs with baseline_before.json (validate_physics metrics).

Exit code != 0 if the flag-off check or any gate fails.

Usage: python3 regression_arm.py [--seeds 42 43 44 45 46] [--duration 3600] [--json out.json]
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import validate_physics as V
from physics_gate import check_physics_gate, load_thresholds
from core.joint_template import JointBank

KNOWN_PREEXISTING = {1: {"temperature"}}
OUT = os.path.join(ROOT, "out", "regression_arm")


def run(cmd):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-2000:], r.stderr[-2000:])
        raise SystemExit(f"command failed: {' '.join(cmd)}")


def flag_off_check() -> bool:
    ok = True
    for k in (1, 2, 3):
        out = os.path.join(OUT, f"flagoff_sensor_{k}.csv")
        run(["python3", "main.py", "--config", f"configs/robot_arm/sensor_{k}_normal.json",
             "--output", out, "--duration", "3600", "--seed", "42"])
        ref = os.path.join(ROOT, "ppt", "arm_robot", f"sensor_{k}_syn.csv")
        if open(out, "rb").read() == open(ref, "rb").read():
            print(f"  flag-off sensor_{k}: byte-identical to deck file")
            continue
        a, b = pd.read_csv(out), pd.read_csv(ref)
        diff = {c for c in a.columns if not a[c].equals(b[c])}
        allowed = KNOWN_PREEXISTING.get(k, set())
        status = "OK (known pre-existing)" if diff <= allowed else "FAIL"
        ok &= diff <= allowed
        print(f"  flag-off sensor_{k}: differs in {sorted(diff)} -> {status}")
    return ok


def joint_gate(seeds, duration) -> dict:
    bank = JointBank(os.path.join(ROOT, "configs", "robot_arm", "joint_bank_arm.npz"))
    real = {s: bank.real_path(s) for s in bank.sensors}
    results = {}
    for seed in seeds:
        syn = {}
        for k in (1, 2, 3):
            out = os.path.join(OUT, f"joint_sensor_{k}_seed{seed}.csv")
            run(["python3", "main.py", "--config", f"configs/robot_arm/sensor_{k}_joint.json", "--output", out,
                 "--duration", str(duration), "--seed", str(seed), "--no-physics-gate"])
            syn[f"sensor_{k}"] = out
        thr = load_thresholds(os.path.join(ROOT, "configs", "robot_arm", "gate_thresholds.json"))
        rep = check_physics_gate(syn, real, bank.period, cross_sensor=True, thresholds=thr)
        results[seed] = rep
        print(f"\n--- seed {seed} ---\n{rep.format()}")
    return results


def baseline_compare(seed):
    base = json.load(open(os.path.join(ROOT, "baseline_before.json")))["pairs"]
    print(f"\n{'pair':8}{'metric':28}{'baseline (deck)':>16}{'joint seed ' + str(seed):>18}")
    for k in (1, 2, 3):
        name = f"arm_j{k}"
        cur = V.run_pair(base[name]["real_path"], os.path.join(OUT, f"joint_sensor_{k}_seed{seed}.csv"),
                         name, OUT, do_plots=False)
        b = base[name]
        rows = [("gravity syn median (quiet)", b["gravity"]["syn"]["quantile_all"]["median"],
                 cur["gravity"]["syn"]["quantile_all"]["median"]),
                ("validity syn % s>1", b["validity"]["syn"]["pct_gt_1"], cur["validity"]["syn"]["pct_gt_1"]),
                ("omega syn p99", b["omega"]["syn"]["p99"], cur["omega"]["syn"]["p99"]),
                ("omega syn max", b["omega"]["syn"]["max"], cur["omega"]["syn"]["max"])]
        for lbl, bv, cv in rows:
            print(f"{name:8}{lbl:28}{bv:>16.3f}{cv:>18.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44, 45, 46])
    ap.add_argument("--duration", type=float, default=3600)
    ap.add_argument("--skip-flag-off", action="store_true")
    ap.add_argument("--json", default=None, help="write every gate check per seed to this JSON file")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    ok = True
    if not args.skip_flag_off:
        print("=== 1. flag OFF vs deck files ===")
        ok &= flag_off_check()
    print("\n=== 2. joint template: physics gate per seed ===")
    res = joint_gate(args.seeds, args.duration)
    print("\n=== summary ===")
    for seed, rep in res.items():
        failed = [f"{c.sensor}/{c.name}" for c in rep.checks if not c.passed and not c.informational]
        info = [f"{c.sensor}/{c.name}" for c in rep.checks if not c.passed and c.informational]
        print(f"  seed {seed}: {'PASS' if rep.passed else 'FAIL ' + ', '.join(failed)}"
              + (f"  (reported, not blocking, above threshold: {', '.join(info)})" if info else ""))
        ok &= rep.passed
    if args.json:
        json.dump({str(seed): rep.to_dict() for seed, rep in res.items()}, open(args.json, "w"), indent=1)
        print(f"\nwrote {args.json}")
    print("\n=== 3. vs baseline_before.json ===")
    baseline_compare(args.seeds[0])
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
