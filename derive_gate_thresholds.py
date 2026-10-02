"""
derive_gate_thresholds.py — derive the data-driven physics-gate thresholds for the arm.

Nothing here is a guess; every number comes from the real recording or from seed variation of
the CURRENT engine (whatever the joint configs produce):

omega p99 tolerance (per sensor)
    tol = max over real 60-min windows of |p99(window) - p99(full)| / p99(full)      (natural variation)
        + 2 * std over seeds of synthetic p99 / p99(full)                             (generator variation)

C2ST threshold (per sensor; real first 60 min vs synthetic 60 min, motion features, block folds)
    threshold = 95th percentile of a label-permutation null + 2 * std over seeds of the synthetic C2ST
    null: the same windows and the same block folds as the test, real/synthetic labels shuffled
    across the pooled windows (real + synthetic seed `--null-seed`), `--n-perm` times.
    C2ST is a REPORTED metric, not a blocking gate check (physics_gate.py marks it informational).

The previous file is read first; its omega tolerance is kept next to the new one
("rel_tol_previous") with the reason for the change (--omega-change-reason).

Writes configs/robot_arm/gate_thresholds.json, read by physics_gate.py.
Usage: python3 derive_gate_thresholds.py [--seeds 42 43 44 45 46] [--n-perm 100]
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
ap.add_argument("--n-perm", type=int, default=100)
ap.add_argument("--null-seed", type=int, default=42)
ap.add_argument("--omega-change-reason", default=None,
                help="why the omega tolerance changed; stored next to the previous value")
ap.add_argument("--output", default=os.path.join(ROOT, "configs", "robot_arm", "gate_thresholds.json"))
args = ap.parse_args()

prev = json.load(open(args.output)) if os.path.exists(args.output) else None
cfg1 = json.load(open(os.path.join(ROOT, "configs", "robot_arm", "sensor_1_joint.json")))["motion"]
bank = JointBank(os.path.join(ROOT, "configs", "robot_arm", cfg1["bank"]))
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

res = {"derived_from": {"seeds": args.seeds, "span_s": args.span, "bank_version": bank.meta.get("version"),
                        "bank_am_split": bank.meta.get("am_split", "savgol"),
                        "log_jitter": cfg1.get("log_jitter", "empirical" if bank.has_log_t else "gaussian"),
                        "c2st_null": {"n_perm": args.n_perm, "pooled_with_seed": args.null_seed}},
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
    om = {"real_p99": full, "rel_tol": nat + gen, "natural_rel_dev": nat, "seed_2sd_rel": gen, "seed_p99": seed_p99}
    if prev and k in prev.get("omega_p99", {}):
        p = prev["omega_p99"][k]
        om["rel_tol_previous"] = p.get("rel_tol_previous", p["rel_tol"]) if args.omega_change_reason is None else p["rel_tol"]
        om["seed_2sd_rel_previous"] = p.get("seed_2sd_rel_previous", p["seed_2sd_rel"]) if args.omega_change_reason is None else p["seed_2sd_rel"]
        om["change_reason"] = args.omega_change_reason or p.get("change_reason")
    res["omega_p99"][k] = om

    sr = SI.real_span(SI.signals(bank.real_path(k), True), args.span)
    sc = [SI.c2st_syn(sr, SI.signals(syn[s][k], False)) for s in args.seeds]
    null = SI.c2st_permutation_null(sr, SI.signals(syn[args.null_seed][k], False), n_perm=args.n_perm)
    sd_seed = float(np.std(sc, ddof=1))
    p95 = float(np.percentile(null, 95))
    res["c2st"][k] = {"threshold": p95 + 2 * sd_seed, "null_p95": p95, "null_mean": float(np.mean(null)),
                      "null_sd": float(np.std(null, ddof=1)), "seed_sd": sd_seed, "seed_values": sc,
                      "blocking": False}
    print(f"{k}: omega tol ±{100 * om['rel_tol']:.1f}% (natural {100 * nat:.1f}% + seeds {100 * gen:.1f}%)"
          + (f", previous ±{100 * om['rel_tol_previous']:.1f}%" if "rel_tol_previous" in om else "")
          + f"  C2ST threshold {res['c2st'][k]['threshold']:.3f} (null p95 {p95:.3f} + 2 sd seeds {2 * sd_seed:.3f}); "
          f"synthetic {np.mean(sc):.3f}±{sd_seed:.3f}", flush=True)
json.dump(res, open(args.output, "w"), indent=1)
print(f"wrote {os.path.relpath(args.output, ROOT)}")
