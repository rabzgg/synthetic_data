"""
c2st_permutation.py — permutation null for the real-vs-synthetic C2ST gate.

For each sensor: the same windows and the same block folds as the gate's C2ST (real first 60 min vs
synthetic 60 min), with the real/synthetic labels shuffled across the pooled windows, n_perm times.
  permutation threshold = 95th percentile of the null + 2 * sd over seeds of the synthetic C2ST
Round-2 analysis tool: it also reported the old threshold (real-vs-real baseline + margin) when the
thresholds file still had it. The threshold now in use is derived by derive_gate_thresholds.py.
Nothing here changes configs/robot_arm/gate_thresholds.json.

Usage: python3 c2st_permutation.py --syn-dir out/ablation/<variant> [--n-perm 100]
       (expects <syn-dir>/sensor_k_seed<seed>.csv and <syn-dir>/ablation.json for the seed values)
"""
import argparse
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import sensor_identity as SI
from core.joint_template import JointBank

ap = argparse.ArgumentParser()
ap.add_argument("--syn-dir", required=True)
ap.add_argument("--null-seed", type=int, default=42, help="synthetic seed pooled with real for the null")
ap.add_argument("--n-perm", type=int, default=100)
ap.add_argument("--out", default=None)
args = ap.parse_args()

bank = JointBank(os.path.join(ROOT, "configs", "robot_arm", "joint_bank_arm.npz"))
thr = json.load(open(os.path.join(ROOT, "configs", "robot_arm", "gate_thresholds.json")))
abl = json.load(open(os.path.join(args.syn_dir, "ablation.json")))
res = {"syn_dir": os.path.relpath(args.syn_dir, ROOT), "n_perm": args.n_perm, "null_seed": args.null_seed, "sensors": {}}
for k in bank.sensors:
    sr = SI.real_span(SI.signals(bank.real_path(k), True), 3600.0)
    ss = SI.signals(os.path.join(args.syn_dir, f"{k}_seed{args.null_seed}.csv"), False)
    null = SI.c2st_permutation_null(sr, ss, n_perm=args.n_perm)
    seeds = [v["c2st"] for v in abl["sensors"][k]["seeds"].values()]
    sd_seed = float(np.std(seeds, ddof=1))
    p95 = float(np.percentile(null, 95))
    old = thr["c2st"][k]
    r = {"null": null, "null_mean": float(np.mean(null)), "null_sd": float(np.std(null, ddof=1)), "null_p95": p95,
         "seed_sd": sd_seed, "perm_threshold": p95 + 2 * sd_seed,
         "old_threshold": old.get("old_threshold", old["threshold"]) if "baseline_mean" in old else None,
         "old_baseline_mean": old.get("baseline_mean"),
         "synthetic_mean": float(np.mean(seeds)),
         "p_value_vs_null": float((1 + np.sum(np.array(null) >= np.mean(seeds))) / (1 + len(null)))}
    r["passes_perm"] = bool(r["synthetic_mean"] <= r["perm_threshold"])
    r["passes_old"] = None if r["old_threshold"] is None else bool(r["synthetic_mean"] <= r["old_threshold"])
    res["sensors"][k] = r
    print(f"{k}: null {r['null_mean']:.3f} ± {r['null_sd']:.3f} (p95 {p95:.3f}) -> perm threshold {r['perm_threshold']:.3f} | "
          + (f"old threshold {r['old_threshold']:.3f} (real-vs-real {r['old_baseline_mean']:.3f}) | "
             if r["old_threshold"] is not None else "") +
          f"synthetic {r['synthetic_mean']:.3f}: perm {'pass' if r['passes_perm'] else 'FAIL'}", flush=True)
out = args.out or os.path.join(args.syn_dir, "c2st_permutation.json")
json.dump(res, open(out, "w"), indent=1)
print("wrote", os.path.relpath(out, ROOT))
