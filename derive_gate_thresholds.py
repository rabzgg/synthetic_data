"""
derive_gate_thresholds.py — derive the data-driven physics-gate thresholds for the arm.

Nothing here is a guess; every number comes from the real recording or from seed variation:

omega p99 tolerance (per sensor)
    tol = max over real 60-min windows of |p99(window) - p99(full)| / p99(full)      (natural variation)
        + 2 * std over seeds of synthetic p99 / p99(full)                             (generator variation)

C2ST threshold (per sensor; real first 60 min vs synthetic 60 min, motion features, block folds)
    threshold = mean(real-vs-real C2ST) + 2 * sqrt(std_seed^2 + std_baseline^2)
    real-vs-real = interleaved halves of the same 60 min (two split schemes x 5 RF seeds).

Writes configs/robot_arm/gate_thresholds.json, read by physics_gate.py.
Usage: python3 derive_gate_thresholds.py [--seeds 42 43 44 45 46]
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import sensor_identity as SI
import validate_physics as V
from core.joint_template import JointBank

ap = argparse.ArgumentParser()
ap.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44, 45, 46])
ap.add_argument("--span", type=float, default=3600.0)
ap.add_argument("--output", default=os.path.join(ROOT, "configs", "robot_arm", "gate_thresholds.json"))
args = ap.parse_args()

bank = JointBank(os.path.join(ROOT, "configs", "robot_arm", "joint_bank_arm.npz"))
OUT = os.path.join(ROOT, "out", "derive_thresholds")
os.makedirs(OUT, exist_ok=True)
syn = {s: {} for s in args.seeds}
for s in args.seeds:
    for i, k in enumerate(bank.sensors, 1):
        p = os.path.join(OUT, f"{k}_seed{s}.csv")
        subprocess.run(["python3", "main.py", "--config", f"configs/robot_arm/sensor_{i}_joint.json", "--output", p,
                        "--duration", str(args.span), "--seed", str(s), "--no-physics-gate"],
                       cwd=ROOT, check=True, capture_output=True)
        syn[s][k] = p

res = {"derived_from": {"seeds": args.seeds, "span_s": args.span, "bank_smooth_quat": bank.meta.get("smooth_quat")},
       "omega_p99": {}, "c2st": {}}
for k in bank.sensors:
    d = V.load(bank.real_path(k))
    te = V.elapsed_seconds(d)
    full = float(np.percentile(V.omega_series(d)["all"], 99))
    wins = [np.percentile(V.omega_series(d[(te >= a) & (te < a + args.span)].reset_index(drop=True))["all"], 99)
            for a in np.arange(0, te[-1] - args.span + 1, 300)]
    nat = float(np.max(np.abs(np.array(wins) - full)) / full)
    seed_p99 = [float(np.percentile(V.omega_series(V.load(syn[s][k]))["all"], 99)) for s in args.seeds]
    gen = float(2 * np.std(seed_p99, ddof=1) / full)
    res["omega_p99"][k] = {"real_p99": full, "rel_tol": nat + gen, "natural_rel_dev": nat,
                           "seed_2sd_rel": gen, "seed_p99": seed_p99}

    sr = SI.real_span(SI.signals(bank.real_path(k), True), args.span)
    base = SI.c2st_real_baseline(sr)
    sc = [SI.c2st_syn(sr, SI.signals(syn[s][k], False)) for s in args.seeds]
    margin = float(2 * np.sqrt(np.var(sc, ddof=1) + np.var(base, ddof=1)))
    res["c2st"][k] = {"threshold": float(np.mean(base) + margin), "baseline_mean": float(np.mean(base)),
                      "baseline_sd": float(np.std(base, ddof=1)), "seed_sd": float(np.std(sc, ddof=1)),
                      "margin": margin, "seed_values": sc}
    print(f"{k}: omega tol ±{100*res['omega_p99'][k]['rel_tol']:.1f}% (natural {100*nat:.1f}% + seeds {100*gen:.1f}%)  "
          f"C2ST threshold {res['c2st'][k]['threshold']:.3f} (baseline {np.mean(base):.3f} + margin {margin:.3f}); "
          f"synthetic {np.mean(sc):.3f}±{np.std(sc, ddof=1):.3f}", flush=True)
json.dump(res, open(args.output, "w"), indent=1)
print(f"wrote {os.path.relpath(args.output, ROOT)}")
