"""
identity_report.py — can synthetic sensor_k be told apart from real sensor_k? (Level 1 only)

Level 1: synthetic sensor_k vs real sensor_k of the same device/position.
Level 2 (which arm link a sensor is on) is NOT answered: the mapping is [USER TO VERIFY].

1. C2ST per sensor: random forest separating real (first 60 min) from synthetic (60 min), motion
   features only (quat, accel, mag, body angular velocity, gravity from quat; no temp / light /
   humidity / pressure / id / timestamp), 10 s windows, block-of-cycles folds. 0.5 = cannot tell apart.
   - baseline: real vs real (interleaved halves of the same 60 min) from gate_thresholds.json
   - control: the old per-column generator (deck files) must be far above the baseline
2. Fingerprints F1-F5: d(synthetic_k, real_k) next to d(real_k half A, real_k half B).
3. F6 counter-rotation about the vertical (quaternions slerped to 10 Hz, per-sensor thresholds).

Usage: python3 identity_report.py [--syn-dir out/regression_arm] [--seeds 42 43 44 45 46]
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
ap.add_argument("--syn-dir", default=os.path.join(ROOT, "out", "regression_arm"))
ap.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44, 45, 46])
ap.add_argument("--out", default=os.path.join(ROOT, "out", "identity"))
args = ap.parse_args()
os.makedirs(args.out, exist_ok=True)

bank = JointBank(os.path.join(ROOT, "configs", "robot_arm", "joint_bank_arm.npz"))
thr = json.load(open(os.path.join(ROOT, "configs", "robot_arm", "gate_thresholds.json")))
K = bank.sensors
real = {k: bank.real_path(k) for k in K}
deck = {k: os.path.join(ROOT, "ppt", "arm_robot", f"{k}_syn.csv") for k in K}
syn = {s: {k: os.path.join(args.syn_dir, f"joint_{k}_seed{s}.csv") for k in K} for s in args.seeds}
CH = ["qx", "qy", "qz", "ax", "ay", "az", "wx", "wy", "wz", "speed", "gx", "gy", "gz", "mx", "my", "mz"]
GROUPS = {"quat": [0, 1, 2], "accel": [3, 4, 5], "angular velocity": [6, 7, 8, 9], "gravity (from quat)": [10, 11, 12],
          "mag": [13, 14, 15]}
FS = ("F1", "F2", "F3", "F4", "F5")
rep = {"c2st": {}, "fingerprint": {}, "f6": {}}

for k in K:
    sr = SI.real_span(SI.signals(real[k], True), 3600.0)
    s_syn = {s: SI.signals(syn[s][k], False) for s in args.seeds}
    s_deck = SI.signals(deck[k], False)
    c_syn = [SI.c2st_syn(sr, s_syn[s]) for s in args.seeds]
    c_deck = SI.c2st_syn(sr, s_deck)
    XR, cR = SI.windows_with_cycles(sr)
    XS, cS = SI.windows_with_cycles(s_syn[args.seeds[0]])
    groups = {}
    for g, chs in GROUPS.items():
        cols = [st * 16 + c for st in range(5) for c in chs]
        groups[g] = SI.c2st(XR[:, cols], SI.block_fold(cR), XS[:, cols], SI.block_fold(cS))
    t = thr["c2st"][k]
    rep["c2st"][k] = {"baseline_mean": t["baseline_mean"], "baseline_sd": t["baseline_sd"], "threshold": t["threshold"],
                      "synthetic": c_syn, "synthetic_mean": float(np.mean(c_syn)), "synthetic_sd": float(np.std(c_syn, ddof=1)),
                      "deck_control": c_deck, "has_power": bool(c_deck > t["threshold"]),
                      "synthetic_passes": bool(np.mean(c_syn) <= t["threshold"]),
                      f"by_feature_group_seed{args.seeds[0]}": groups}
    fr = SI.fingerprint(sr)
    ab = SI.fingerprint_split_distance(sr)
    ds = [SI.fp_distance(SI.fingerprint(s_syn[s]), fr) for s in args.seeds]
    rep["fingerprint"][k] = {"real_A_vs_B": ab,
                             "synthetic_vs_real": {F: float(np.mean([d[F] for d in ds])) for F in FS},
                             "deck_vs_real": SI.fp_distance(SI.fingerprint(s_deck), fr),
                             "summary": {"real": SI.fp_summary(fr), "synthetic": SI.fp_summary(SI.fingerprint(s_syn[args.seeds[0]])),
                                         "deck": SI.fp_summary(SI.fingerprint(s_deck))}}
    print(k, "done", flush=True)


def f6(paths):
    G = {k: SI.slerp_grid(paths[k]) for k in K}
    out = {}
    for a, c in ((K[0], K[1]), (K[1], K[2]), (K[0], K[2])):
        wa, wc = SI._align(G[a], G[c])
        key = f"{a[-1]}-{c[-1]}"
        for lbl, ta, tc in (("rel50", 0.5 * np.percentile(np.abs(wa), 95), 0.5 * np.percentile(np.abs(wc), 95)),
                            ("fixed3", 3.0, 3.0)):
            both = (np.abs(wa) > ta) & (np.abs(wc) > tc)
            out[f"{key} per-sample {lbl}"] = float(100 * np.mean(np.sign(wa[both]) != np.sign(wc[both]))) if both.any() else float("nan")
        cr = SI.counter_rotation(G[a], G[c])
        out[f"{key} episodes"] = cr["episode_counter_pct"]
        out[f"{key} n_episodes"] = cr["episodes_both_yaw"]
    return out


rep["f6"]["real"] = f6(real)
rep["f6"]["deck"] = f6(deck)
seed_f6 = [f6(syn[s]) for s in args.seeds]
rep["f6"]["synthetic_mean"] = {key: float(np.nanmean([x[key] for x in seed_f6])) for key in seed_f6[0]}
rep["f6"]["synthetic_sd"] = {key: float(np.nanstd([x[key] for x in seed_f6], ddof=1)) for key in seed_f6[0]}
json.dump(rep, open(os.path.join(args.out, "identity_report.json"), "w"), indent=1, default=float)

# ── markdown ──
L = ["# Sensor identity report (Level 1)", "",
     "Can synthetic sensor_k be told apart from real sensor_k? Sensor -> arm-link mapping is "
     "**[USER TO VERIFY]**; nothing here makes a Level-2 claim.", "",
     "## C2ST (balanced accuracy; 0.5 = indistinguishable)", "",
     "| sensor | real vs real (baseline) | threshold | synthetic (5 seeds) | old generator (control) | test has power | synthetic passes |",
     "|---|---|---|---|---|---|---|"]
for k, r in rep["c2st"].items():
    L.append(f"| {k} | {r['baseline_mean']:.3f} ± {r['baseline_sd']:.3f} | {r['threshold']:.3f} | "
             f"{r['synthetic_mean']:.3f} ± {r['synthetic_sd']:.3f} | {r['deck_control']:.3f} | "
             f"{'yes' if r['has_power'] else 'NO'} | {'yes' if r['synthetic_passes'] else '**no**'} |")
L += ["", f"C2ST restricted to one feature group (seed {args.seeds[0]}):", "",
      "| sensor | " + " | ".join(GROUPS) + " |", "|---|" + "---|" * len(GROUPS)]
for k, r in rep["c2st"].items():
    g = r[f"by_feature_group_seed{args.seeds[0]}"]
    L.append(f"| {k} | " + " | ".join(f"{g[x]:.3f}" for x in GROUPS) + " |")
L += ["", "## Fingerprint distances (F1-F3 Wasserstein, F4 KS, F5 Wasserstein)", "",
      "| sensor | pair | " + " | ".join(FS) + " |", "|---|---|" + "---|" * len(FS)]
for k, r in rep["fingerprint"].items():
    L.append(f"| {k} | real half A vs half B | " + " | ".join(f"{r['real_A_vs_B'][F]:.4f}" for F in FS) + " |")
    L.append(f"| {k} | synthetic vs real | " + " | ".join(f"{r['synthetic_vs_real'][F]:.4f}" for F in FS) + " |")
    L.append(f"| {k} | old generator vs real | " + " | ".join(f"{r['deck_vs_real'][F]:.4f}" for F in FS) + " |")
L += ["", "## Fingerprint summary (real | synthetic | old generator)", "",
      "| sensor | field | real | synthetic | old generator |", "|---|---|---|---|---|"]
for k, r in rep["fingerprint"].items():
    for f in r["summary"]["real"]:
        L.append(f"| {k} | {f} | {r['summary']['real'][f]} | {r['summary']['synthetic'][f]} | {r['summary']['deck'][f]} |")
L += ["", "## F6 counter-rotation about the vertical (%)", "", "| metric | real | synthetic (5 seeds) | old generator |", "|---|---|---|---|"]
for key in rep["f6"]["real"]:
    L.append(f"| {key} | {rep['f6']['real'][key]:.1f} | {rep['f6']['synthetic_mean'][key]:.1f} ± "
             f"{rep['f6']['synthetic_sd'][key]:.1f} | {rep['f6']['deck'][key]:.1f} |")
open(os.path.join(args.out, "identity_report.md"), "w").write("\n".join(L) + "\n")
print("wrote", os.path.join(args.out, "identity_report.md"))
