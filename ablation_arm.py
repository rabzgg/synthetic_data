"""
ablation_arm.py — one-cause-at-a-time ablations of the arm joint-template engine.

Generates one engine variant (motion-config overrides) for every seed and sensor, then measures
against the real recording, with the CURRENT gate thresholds (configs/robot_arm/gate_thresholds.json,
never changed here):
  * logged dt distribution (p1/p25/p50/p75/p99, sd, excess kurtosis, lag-1/2 autocorrelation)
  * omega p99 vs real (relative deviation, pass/fail against the data-derived tolerance)
  * C2ST overall and per feature group (quat, accel, angular velocity, gravity, mag), every seed
  * copy metric (sensor_1, sensor_2; sensor_3 is excluded from the copy check by the gate)

Usage:
  python3 ablation_arm.py --name gaussian --motion log_jitter=gaussian
  python3 ablation_arm.py --name A_no_jitter --motion log_jitter=none
Results: out/ablation/<name>/ablation.json
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np
from scipy.stats import kurtosis

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import physics_gate as G
import sensor_identity as SI
import validate_physics as V
from core.joint_template import JointBank, _abs_seconds

GROUPS = {"quat": [0, 1, 2], "accel": [3, 4, 5], "angular velocity": [6, 7, 8, 9],
          "gravity (from quat)": [10, 11, 12], "mag": [13, 14, 15]}
BANK = os.path.join(ROOT, "configs", "robot_arm", "joint_bank_arm.npz")


def _val(v):
    try:
        return json.loads(v)
    except json.JSONDecodeError:
        return v


def generate(name, overrides, seeds, duration):
    out = os.path.join(ROOT, "out", "ablation", name)
    os.makedirs(out, exist_ok=True)
    paths = {s: {} for s in seeds}
    for seed in seeds:
        procs = []
        for k in (1, 2, 3):
            cfg = json.load(open(os.path.join(ROOT, "configs", "robot_arm", f"sensor_{k}_joint.json")))
            cfg["motion"]["bank"] = BANK
            cfg["motion"].update(overrides)
            cp = os.path.join(out, f"cfg_sensor_{k}.json")
            json.dump(cfg, open(cp, "w"), indent=1)
            p = os.path.join(out, f"sensor_{k}_seed{seed}.csv")
            procs.append(subprocess.Popen(["python3", "main.py", "--config", cp, "--output", p, "--duration",
                                           str(duration), "--seed", str(seed), "--no-physics-gate"],
                                          cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE))
            paths[seed][f"sensor_{k}"] = p
        for pr in procs:
            if pr.wait() != 0:
                raise RuntimeError(pr.stderr.read().decode())
    return out, paths


def _ac(x, j):
    x = x - x.mean()
    return float(np.sum(x[j:] * x[:-j]) / np.sum(x * x))


def dt_stats(path):
    import pandas as pd
    t = _abs_seconds(pd.read_csv(path, usecols=["timestamp"])["timestamp"]) * 1000.0
    d = np.diff(t)
    d = d[(d > 0) & (d <= 1000)]
    p = np.percentile(d, [1, 25, 50, 75, 99])
    return {"p1": p[0], "p25": p[1], "p50": p[2], "p75": p[3], "p99": p[4], "sd": float(d.std()),
            "kurt": float(kurtosis(d)), "ac1": _ac(d, 1), "ac2": _ac(d, 2),
            "pct_gt150": float(100 * np.mean(d > 150)), "pct_lt40": float(100 * np.mean(d < 40))}


def measure(paths, seeds, with_copy=True):
    bank = JointBank(BANK)
    thr = json.load(open(os.path.join(ROOT, "configs", "robot_arm", "gate_thresholds.json")))
    res = {}
    for k in bank.sensors:
        real = bank.real_path(k)
        sr = SI.real_span(SI.signals(real, True), 3600.0)
        XR, cR = SI.windows_with_cycles(sr)
        om = thr["omega_p99"][k]
        d_real = G._load(real) if with_copy else None
        r = {"real_dt": dt_stats(real), "seeds": {}}
        for seed in seeds:
            p = paths[seed][k]
            ss = SI.signals(p, False)
            XS, cS = SI.windows_with_cycles(ss)
            groups = {}
            for g, chs in GROUPS.items():
                cols = [st * 16 + c for st in range(5) for c in chs]
                groups[g] = SI.c2st(XR[:, cols], SI.block_fold(cR), XS[:, cols], SI.block_fold(cS))
            p99 = float(np.percentile(V.omega_series(V.load(p))["all"], 99))
            rel = (p99 - om["real_p99"]) / om["real_p99"]
            e = {"dt": dt_stats(p), "omega_p99": p99, "omega_rel": rel, "omega_pass": bool(abs(rel) <= om["rel_tol"]),
                 "c2st": SI.c2st(XR, SI.block_fold(cR), XS, SI.block_fold(cS)), "c2st_groups": groups}
            if with_copy and k not in G.COPY_EXCLUDE:
                e["copy_pct"] = G.copy_pct(G._load(p), d_real, bank.period)
            r["seeds"][str(seed)] = e
            print(f"{k} seed {seed}: omega p99 {p99:.2f} ({100 * rel:+.1f}%, tol ±{100 * om['rel_tol']:.1f}%)  "
                  f"C2ST {e['c2st']:.3f}  " + "  ".join(f"{g[:5]} {v:.3f}" for g, v in groups.items())
                  + (f"  copy {e['copy_pct']:.1f}%" if "copy_pct" in e else ""), flush=True)
        S = r["seeds"].values()
        r["summary"] = {
            "omega_rel_mean": float(np.mean([e["omega_rel"] for e in S])),
            "omega_rel_sd": float(np.std([e["omega_rel"] for e in S], ddof=1)),
            "omega_pass_n": int(sum(e["omega_pass"] for e in S)), "omega_tol": om["rel_tol"],
            "c2st_mean": float(np.mean([e["c2st"] for e in S])), "c2st_sd": float(np.std([e["c2st"] for e in S], ddof=1)),
            "c2st_threshold": thr["c2st"][k]["threshold"],
            "c2st_groups_mean": {g: float(np.mean([e["c2st_groups"][g] for e in S])) for g in GROUPS},
            "c2st_groups_sd": {g: float(np.std([e["c2st_groups"][g] for e in S], ddof=1)) for g in GROUPS},
            "dt_mean": {f: float(np.mean([e["dt"][f] for e in S])) for f in r["real_dt"]},
        }
        if all("copy_pct" in e for e in S):
            r["summary"]["copy_pct_mean"] = float(np.mean([e["copy_pct"] for e in S]))
        res[k] = r
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--motion", nargs="*", default=[], help="motion-config overrides key=value (JSON values)")
    ap.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44, 45, 46])
    ap.add_argument("--duration", type=float, default=3600.0)
    ap.add_argument("--no-copy", action="store_true")
    args = ap.parse_args()
    overrides = {kv.split("=", 1)[0]: _val(kv.split("=", 1)[1]) for kv in args.motion}
    out, paths = generate(args.name, overrides, args.seeds, args.duration)
    res = {"name": args.name, "motion_overrides": overrides, "seeds": args.seeds,
           "sensors": measure(paths, args.seeds, not args.no_copy)}
    json.dump(res, open(os.path.join(out, "ablation.json"), "w"), indent=1, default=float)
    print("wrote", os.path.relpath(os.path.join(out, "ablation.json"), ROOT))


if __name__ == "__main__":
    main()
