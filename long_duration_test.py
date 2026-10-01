"""
long_duration_test.py — generate longer than the recording and gate each hour separately.

Usage: python3 long_duration_test.py [--hours 3] [--seed 42]
Exit code != 0 if any hour fails the gate.
"""
import argparse
import os
import subprocess
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from physics_gate import check_physics_gate
from core.joint_template import JointBank, build_schedule

ap = argparse.ArgumentParser()
ap.add_argument("--hours", type=int, default=3)
ap.add_argument("--seed", type=int, default=42)
ap.add_argument("--json", default=None, help="write schedule info + every gate check per hour")
args = ap.parse_args()
dur = args.hours * 3600
OUT = os.path.join(ROOT, "out", "long_duration")
os.makedirs(OUT, exist_ok=True)
bank = JointBank(os.path.join(ROOT, "configs", "robot_arm", "joint_bank_arm.npz"))

paths = {}
for k in (1, 2, 3):
    p = os.path.join(OUT, f"sensor_{k}_{args.hours}h_seed{args.seed}.csv")
    r = subprocess.run(["python3", "main.py", "--config", f"configs/robot_arm/sensor_{k}_joint.json",
                        "--output", p, "--duration", str(dur), "--seed", str(args.seed), "--no-physics-gate"],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-2000:], r.stderr[-2000:]); sys.exit(2)
    warn = [l for l in r.stdout.splitlines() if l.startswith("WARNING")]
    print(f"sensor_{k}: {warn[0] if warn else 'NO WARNING PRINTED'}")
    paths[f"sensor_{k}"] = p

# splice continuity, split by phase
sched, info = build_schedule(bank, dur, args.seed)
print(f"\nschedule: {info}")
pe = {s: bank.data[s]["pose_end"] for s in bank.sensors}
ps = {s: bank.data[s]["pose_start"] for s in bank.sensors}
from core.joint_template import tilt_deg, angle_deg
for phase in ("local", "pool"):
    tl, fl = [], []
    for prev, cur in zip(sched[:-1], sched[1:]):
        if cur["phase"] != phase:
            continue
        i, j = prev["template"], cur["template"]
        tl.append(max(float(tilt_deg(pe[s][i], ps[s][j])[0]) for s in bank.sensors))
        fl.append(max(float(angle_deg(pe[s][i], ps[s][j])) for s in bank.sensors))
    if tl:
        print(f"  splices into '{phase}' cycles: n={len(tl)}  tilt max {max(tl):.2f}° p95 {np.percentile(tl,95):.2f}°"
              f"  full-pose max {max(fl):.2f}° p95 {np.percentile(fl,95):.2f}°")
n_pool_src = len({c["template"] for c in sched if c["phase"] == "pool"})
print(f"  distinct templates used after the recording: {n_pool_src} of {len(bank.windows)}")

ok = True
hours_out = {}
real = {s: bank.real_path(s) for s in bank.sensors}
for h in range(args.hours):
    hp = {}
    for s, p in paths.items():
        d = pd.read_csv(p)
        t = (d["timestamp"] - d["timestamp"].iloc[0]) / 1000.0
        part = d[(t >= h * 3600) & (t < (h + 1) * 3600)]
        hp[s] = os.path.join(OUT, f"{s}_hour{h+1}.csv")
        part.to_csv(hp[s], index=False)
    rep = check_physics_gate(hp, real, bank.period, cross_sensor=True)
    print(f"\n=== hour {h+1} ({h*60}-{(h+1)*60} min; recording ends at {bank.recording_s/60:.1f} min) ===")
    print(rep.format())
    hours_out[f"hour_{h+1}"] = rep.to_dict()
    ok &= rep.passed
if args.json:
    import json
    json.dump({"schedule_info": info, "hours": hours_out}, open(args.json, "w"), indent=1, default=float)
    print(f"wrote {args.json}")
sys.exit(0 if ok else 1)
