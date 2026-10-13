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

IMU cross-column consistency (per sensor; imu_consistency.py), reference = real first 60 min:
    rel_tol = |real half A - real half B| / ref + 2 * std over seeds / ref   (A, B = contiguous 30-min halves)
    metrics: gravity error while moving (median, p95) and mag world-frame spread while moving.
    "blocking" per metric is set from BLOCKING_IMU below (decided from the 5 + 10 held-out seed run).

Cross-sensor (all sensors of the bank; validate_physics.check_inter_sensor), reference = real first 60 min:
    7a activity correlation per pair, 7b agreement of ALL moving masks:
        min = real - (|real half A - real half B| + 2 * std over seeds)        (one-sided: lower bound)
    7c cross-correlation lag: max_abs = largest |lag| of any pair in the real reference or its halves
Copy check: copy_informative per sensor (physics_gate: held-out real vs real first 60 min), recorded.

The previous file is read first; its omega tolerance is kept next to the new one
("rel_tol_previous") with the reason for the change (--omega-change-reason).

Writes <config-dir>/gate_thresholds.json (next to the bank), read by physics_gate.py.
Usage: python3 derive_gate_thresholds.py [--seeds 42 43 44 45 46] [--n-perm 100]
       python3 derive_gate_thresholds.py --only-imu   (reuse out/derive_thresholds/*.csv; update only "imu_consistency")
       python3 derive_gate_thresholds.py --config-dir configs/robot_arm_456   (another arm bank, e.g. sensors 4-6)
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import imu_consistency as IC
import physics_gate as G
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
ap.add_argument("--only-imu", action="store_true",
                help="reuse the existing seed files and keep omega/C2ST; derive only the IMU consistency section")
ap.add_argument("--config-dir", default=os.path.join("configs", "robot_arm"),
                help="folder with the <sensor>_joint.json configs and their bank")
ap.add_argument("--output", default=None, help="default: <config-dir>/gate_thresholds.json")
args = ap.parse_args()
CFG_DIR = os.path.join(ROOT, args.config_dir)
args.output = args.output or os.path.join(CFG_DIR, "gate_thresholds.json")

# Blocking status per IMU metric, decided on 5 + 10 held-out seeds (review 2026-10-06):
# mag spread passes -> blocking; gravity-while-moving fails on the synthetic data (the donor accel
# residual shifts it by 0.01-0.1 deg; raw accel replay matches real) -> reported only.
BLOCKING_IMU = {"grav_moving_median_deg": False, "grav_moving_p95_deg": False, "mag_world_spread_moving_deg": True}

prev = json.load(open(args.output)) if os.path.exists(args.output) else None
cfg1 = json.load(open(os.path.join(CFG_DIR, sorted(f for f in os.listdir(CFG_DIR) if f.endswith("_joint.json"))[0])))["motion"]
bank = JointBank(os.path.join(CFG_DIR, cfg1["bank"]))
tag = os.path.basename(os.path.normpath(args.config_dir))
OUT = os.path.join(ROOT, "out", "derive_thresholds" + ("" if tag == "robot_arm" else f"_{tag}"))
os.makedirs(OUT, exist_ok=True)
syn = {s: {} for s in args.seeds}
for s in args.seeds:
    for k in bank.sensors:
        p = os.path.join(OUT, f"{k}_seed{s}.csv")
        syn[s][k] = p
        if args.only_imu:
            if not os.path.exists(p):
                raise SystemExit(f"--only-imu needs {p}; run without --only-imu first")
            continue
        subprocess.run(["python3", "main.py", "--config", os.path.join(CFG_DIR, f"{k}_joint.json"), "--output", p,
                        "--duration", str(args.span), "--seed", str(s), "--no-physics-gate"],
                       cwd=ROOT, check=True, capture_output=True)

res = {"derived_from": {"seeds": args.seeds, "span_s": args.span, "bank_version": bank.meta.get("version"),
                        "bank_am_split": bank.meta.get("am_split", "savgol"),
                        "log_jitter": cfg1.get("log_jitter", "empirical" if bank.has_log_t else "gaussian"),
                        "c2st_null": {"n_perm": args.n_perm, "pooled_with_seed": args.null_seed}},
       "omega_p99": {}, "c2st": {}, "imu_consistency": {}, "copy_informative": {}}
if args.only_imu:
    res = dict(prev)
    res["imu_consistency"] = {}
for k in bank.sensors:
    ref = IC.real_reference(bank.real_path(k), args.span)
    sm = {s: IC.synthetic_metrics(syn[s][k], ref["b"]) for s in args.seeds}
    imu = {"hard_iron_b": [float(x) for x in ref["b"]], "reference": f"real first {args.span / 60:.0f} min"}
    for m in IC.METRICS:
        r = ref["ref"][m]
        nat = abs(ref["half_a"][m] - ref["half_b"][m]) / r
        vals = [sm[s][m] for s in args.seeds]
        gen = float(2 * np.std(vals, ddof=1) / r)
        imu[m] = {"real": r, "real_half_a": ref["half_a"][m], "real_half_b": ref["half_b"][m],
                  "natural_rel_dev": nat, "seed_2sd_rel": gen, "rel_tol": nat + gen, "seed_values": vals,
                  "blocking": BLOCKING_IMU[m]}
        print(f"{k}: {m} real {r:.3f} tol ±{100 * (nat + gen):.1f}% (halves {100 * nat:.1f}% + seeds {100 * gen:.1f}%), "
              f"synthetic {np.mean(vals):.3f} ({100 * (np.mean(vals) - r) / r:+.1f}%), "
              f"{'blocking' if BLOCKING_IMU[m] else 'reported'}", flush=True)
    res["imu_consistency"][k] = imu
    if args.only_imu:
        continue
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

    res["copy_informative"][k] = G.copy_informative(bank.real_path(k), bank.period)
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
if not args.only_imu and len(bank.sensors) >= 2:
    order = sorted(bank.sensors)
    labels = [k.replace("sensor_", "s") for k in order]
    rp = [bank.real_path(k) for k in order]
    ref = V.check_inter_sensor(rp, None, labels=labels, real_span=(0, args.span))["real"]
    ha = V.check_inter_sensor(rp, None, labels=labels, real_span=(0, args.span / 2))["real"]
    hb = V.check_inter_sensor(rp, None, labels=labels, real_span=(args.span / 2, args.span / 2))["real"]
    sy = [V.check_inter_sensor(rp, [syn[s][k] for k in order], syn_use_abs=True, labels=labels)["syn"]
          for s in args.seeds]
    cs = {"sensors": order, "reference": f"real first {args.span / 60:.0f} min", "activity_corr": {}}

    def bound(r, a, b, vals):
        nat, gen = abs(a - b), float(2 * np.std(vals, ddof=1))
        return {"real": r, "real_half_a": a, "real_half_b": b, "natural_dev": nat, "seed_2sd": gen,
                "min": r - nat - gen, "seed_values": vals}
    for pair in ref["activity_corr"]:
        cs["activity_corr"][pair] = bound(ref["activity_corr"][pair], ha["activity_corr"][pair],
                                          hb["activity_corr"][pair], [x["activity_corr"][pair] for x in sy])
    cs["all_agree_pct"] = bound(ref["all_agree_pct"], ha["all_agree_pct"], hb["all_agree_pct"],
                                [x["all_agree_pct"] for x in sy])
    real_lags = {f"{n}:{p}": v["lag_ms"] for n, side in (("ref", ref), ("half_a", ha), ("half_b", hb))
                 for p, v in side["xcorr_lag"].items()}
    cs["lag_ms"] = {"max_abs": float(max(abs(v) for v in real_lags.values())),
                    "real_nonzero": {k: v for k, v in real_lags.items() if v != 0},
                    "seed_max_abs": [float(max(abs(v["lag_ms"]) for v in x["xcorr_lag"].values())) for x in sy]}
    res["cross_sensor"] = cs
    a = cs["all_agree_pct"]
    print(f"cross-sensor ({len(order)} sensors): 7b agreement real {a['real']:.1f}% -> min {a['min']:.1f}% "
          f"(synthetic {np.mean(a['seed_values']):.1f}%); 7a min over pairs "
          f"{min(v['min'] for v in cs['activity_corr'].values()):.3f}; 7c |lag| <= {cs['lag_ms']['max_abs']:.0f} ms", flush=True)
json.dump(res, open(args.output, "w"), indent=1)
print(f"wrote {os.path.relpath(args.output, ROOT)}")
