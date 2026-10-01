"""
identity_report.py — Level-1 sensor identity report: fingerprints F1–F6 + classifier juries.

Classifier cases (trained on real, interleaved split per 37 s cycle):
  a  real holdout                     ceiling
  b  joint-template B+ (production)   bank = whole recording -> replays training cycles (leaky)
  b2 joint-template B+ from holdout   bank restricted to cycles in the test/buffer bins (leak-free)
  c  old generator (deck files)       control, must fail
  d  B+ with shuffled sensor labels   negative control, must fail
Each for feature sets: all | no_mag | frame_safe (no absolute quat, no mag: heading-independent).

Sensor -> link mapping is [USER TO VERIFY]; this report makes no Level-2 claim.
Usage: python3 identity_report.py [--syn-dir out/regression_arm] [--seed 42]
"""
import argparse
import copy
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import sensor_identity as SI
from core.joint_template import JointBank, JointTemplateEngine

ap = argparse.ArgumentParser()
ap.add_argument("--syn-dir", default=os.path.join(ROOT, "out", "regression_arm"))
ap.add_argument("--seed", type=int, default=42)
ap.add_argument("--out", default=os.path.join(ROOT, "out", "identity"))
args = ap.parse_args()
os.makedirs(args.out, exist_ok=True)

bank_path = os.path.join(ROOT, "configs", "robot_arm", "joint_bank_arm.npz")
bank = JointBank(bank_path)
keys = bank.sensors
real_paths = {k: bank.real_path(k) for k in keys}
new_paths = {k: os.path.join(args.syn_dir, f"joint_{k}_seed{args.seed}.csv") for k in keys}
old_paths = {k: os.path.join(ROOT, "ppt", "arm_robot", f"{k}_syn.csv") for k in keys}

# ── b2: leak-free B+ — bank windows whose span touches only test/buffer bins (cycle%5 in {4,0,1})
def leak_free_paths():
    t0 = bank.meta["t0_abs"]
    W = bank.windows
    keep = []
    for i, (a, b) in enumerate(W):
        bins = {int(x // SI.CYCLE_S) % 5 for x in np.arange(a, b, 1.0)}
        if bins <= {4, 0, 1}:
            keep.append(i)
    out = {}
    for k in keys:
        eng = JointTemplateEngine(bank_path, k)
        sub = copy.copy(eng.bank)
        sub.windows = W[keep]
        sub.data = {s: dict(eng.bank.data[s], pose_start=eng.bank.data[s]["pose_start"][keep],
                            pose_end=eng.bank.data[s]["pose_end"][keep]) for s in keys}
        eng.bank = sub
        ts = pd.read_csv(new_paths[k], usecols=["timestamp"])["timestamp"].to_numpy(float)
        cols = eng.generate(ts, ts[-1] / 1000.0, args.seed, origin_ms=20000.0)
        df = pd.DataFrame({"timestamp": ts.astype(int), **cols})
        out[k] = os.path.join(args.out, f"leakfree_{k}.csv")
        df.to_csv(out[k], index=False)
    return out, len(keep)

lf_paths, n_lf = leak_free_paths()
print(f"b2 leak-free bank: {n_lf} of {len(bank.windows)} cycles (test/buffer bins only)")

real = {k: SI.signals(real_paths[k], True) for k in keys}
sets = {"syn_new": {k: SI.signals(new_paths[k], False) for k in keys},
        "syn_old": {k: SI.signals(old_paths[k], False) for k in keys},
        "syn_leakfree": {k: SI.signals(lf_paths[k], False) for k in keys}}

# ── fingerprints ──────────────────────────────────────────────────────────────
fr = {k: SI.fingerprint(real[k]) for k in keys}
fp = {name: {k: SI.fingerprint(s[k]) for k in keys} for name, s in sets.items()}
report = {"fingerprint_summary": {}, "fingerprint_distance": {}, "relations": {}, "classifier": {}}
for k in keys:
    report["fingerprint_summary"][k] = {"real": SI.fp_summary(fr[k]),
                                        **{n: SI.fp_summary(fp[n][k]) for n in ("syn_new", "syn_old")}}
    others = [j for j in keys if j != k]
    rr = {j: SI.fp_distance(fr[k], fr[j]) for j in others}
    row = {"real_k_vs_nearest_other_real": {F: min(rr[j][F] for j in others) for F in ("F1", "F2", "F3", "F4", "F5")}}
    for n in ("syn_new", "syn_old", "syn_leakfree"):
        own = SI.fp_distance(fp[n][k], fr[k])
        oth = {j: SI.fp_distance(fp[n][k], fr[j]) for j in others}
        row[n] = {F: {"to_real_k": own[F], "to_nearest_other_real": min(oth[j][F] for j in others),
                      "closer_to_own": own[F] < min(oth[j][F] for j in others)} for F in own}
    report["fingerprint_distance"][k] = row
report["relations"] = {"real": SI.relations(real), **{n: SI.relations(s) for n, s in sets.items()}}

# ── classifier ────────────────────────────────────────────────────────────────
rng = np.random.default_rng(0)
for fs in SI.FEATURE_SETS:
    clf, Xte, yte, ck, _ = SI.train_classifier(real, fs)
    res = {}
    cm, rec = SI.confusion(clf, Xte, yte); res["a_real_holdout"] = (cm, rec)
    for tag, name in (("b_syn_new", "syn_new"), ("b2_syn_leakfree", "syn_leakfree"), ("c_syn_old_deck", "syn_old")):
        X, y = SI.syn_windows(sets[name], ck, fs); res[tag] = SI.confusion(clf, X, y)
    X, y = SI.syn_windows(sets["syn_new"], ck, fs); res["d_shuffled_labels"] = SI.confusion(clf, X, rng.permutation(y))
    report["classifier"][fs] = {t: {"confusion": cm.tolist(), "recall": rec.round(3).tolist(),
                                    "accuracy": float(np.trace(cm) / cm.sum())} for t, (cm, rec) in res.items()}

json.dump(report, open(os.path.join(args.out, "identity_report.json"), "w"), indent=1, default=float)
print(json.dumps(report["classifier"], indent=None, default=float)[:200], "...")
print(f"wrote {os.path.join(args.out, 'identity_report.json')}")

# ── markdown rendering of the same numbers ────────────────────────────────────
def _md(report) -> str:
    L = ["# Sensor identity report (Level 1)", "",
         "Level 1 only: is synthetic sensor_k recognisable as real sensor_k. Sensor -> arm-link "
         "mapping is **[USER TO VERIFY]**; nothing here makes a Level-2 claim.", "",
         "## Fingerprint summary (real | joint template | old generator)", ""]
    keys_ = list(report["fingerprint_summary"])
    fields = list(report["fingerprint_summary"][keys_[0]]["real"])
    L.append("| sensor | field | real | joint template | old generator |")
    L.append("|---|---|---|---|---|")
    for k in keys_:
        v = report["fingerprint_summary"][k]
        for f in fields:
            L.append(f"| {k} | {f} | {v['real'][f]} | {v['syn_new'][f]} | {v['syn_old'][f]} |")
    L += ["", "## Fingerprint distances (to own real sensor / to nearest other real sensor)", "",
          "| sensor | case | F1 | F2 | F3 | F4 | F5 |", "|---|---|---|---|---|---|---|"]
    for k, v in report["fingerprint_distance"].items():
        r = v["real_k_vs_nearest_other_real"]
        L.append(f"| {k} | real_k vs nearest other real | " + " | ".join(f"{r[F]:.4f}" for F in ("F1", "F2", "F3", "F4", "F5")) + " |")
        for n in ("syn_new", "syn_leakfree", "syn_old"):
            L.append(f"| {k} | {n} | " + " | ".join(
                f"{v[n][F]['to_real_k']:.4f} / {v[n][F]['to_nearest_other_real']:.4f} {'✓' if v[n][F]['closer_to_own'] else '✗'}"
                for F in ("F1", "F2", "F3", "F4", "F5")) + " |")
    L += ["", "## Classifier confusion matrices (rows = true sensor_1..3, cols = predicted)", ""]
    for fs, cases in report["classifier"].items():
        L += [f"### feature set: {fs}", "", "| case | accuracy | recall s1/s2/s3 | confusion |", "|---|---|---|---|"]
        for t, c in cases.items():
            L.append(f"| {t} | {c['accuracy']:.3f} | {' / '.join(f'{x:.3f}' for x in c['recall'])} | {c['confusion']} |")
        L.append("")
    L += ["## F6 inter-sensor relations", "", "| set | " + " | ".join(report["relations"]["real"]) + " |",
          "|---|" + "---|" * len(report["relations"]["real"])]
    for n, r in report["relations"].items():
        L.append(f"| {n} | " + " | ".join(f"{x:.3f}" for x in r.values()) + " |")
    return "\n".join(L) + "\n"

open(os.path.join(args.out, "identity_report.md"), "w").write(_md(report))
print(f"wrote {os.path.join(args.out, 'identity_report.md')}")
