"""
drift_diagnosis.py — where does the slow drift of the arm's rest orientation come from?

Per sensor, on the full real recording, at the same rest pose every cycle (rest samples within ±1 s of
each cycle boundary of the joint-template bank; the boundary sits mid-rest):
  a) mag_body (raw, sensor frame): does it stay constant?
  b) gravity_body (accel / |accel|, sensor frame): does it stay constant?
  c) orientation change dR = R_t R_ref^T (world frame) split into yaw (twist about world z) and tilt (swing)
  d) yaw(t): linear trend (°/min), residual, and relation to temperature
  e) the discriminating test: observed mag_body change vs the change a PHYSICAL yaw of that size would
     cause, ΔM_phys = (R_t^T R_ref − I)(M_ref − b), b = hard-iron offset (imu_consistency). A heading
     drift of the fusion leaves mag_body unchanged. (Gravity_body cannot discriminate: a physical yaw
     about the vertical does not change it either; it only rules out tilt drift.)
Cycles whose accel gravity direction changed > 2° are a different rest pose (the cycle boundary fell
on another pose; identified from accel, independent of the fusion) and are left out.
Reference = mean of the first 3 cycles. Diagnosis only; the engine is not changed.
Run from clean_project/:  python3 results/joint_template/drift/drift_diagnosis.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation

sys.path.insert(0, os.getcwd())
from core.joint_template import JointBank, load_real, omega_smooth, motion_threshold, REAL_ALIASES
import imu_consistency as IC
import sensor_identity as SI

OUT = os.path.join("results", "joint_template", "drift")
bank = JointBank("configs/robot_arm/joint_bank_arm.npz")
t0 = bank.meta["t0_abs"]
res = {}


def ang(u, v):
    u = u / np.linalg.norm(u); v = v / np.linalg.norm(v)
    return float(np.degrees(np.arccos(np.clip(u @ v, -1, 1))))


for s in bank.sensors:
    r = load_real(bank.real_path(s))
    temp = pd.read_csv(bank.real_path(s), usecols=["temp"])["temp"].to_numpy(float) / 1000.0
    t = r["t"] - t0
    om = omega_smooth(r["t"], r["q"])
    rest = om < motion_threshold(om)
    rows = []
    for a, b in bank.windows:
        m = rest & (np.abs(t - a) < 1.0)
        if m.sum() < 5:
            continue
        q = r["q"][m]                                   # [w, x, y, z], hemisphere-continuous
        q = np.where((q @ q[0])[:, None] < 0, -q, q)
        rot = Rotation.from_quat(np.c_[q[:, 1:], q[:, 0]]).mean()
        rows.append({"t_min": float(a / 60), "temp_c": float(temp[m].mean()), "rot": rot,
                     "M": r["M"][m].mean(0), "g": (r["A"][m] / np.linalg.norm(r["A"][m], axis=1, keepdims=True)).mean(0)})
    g_first = np.mean([x["g"] for x in rows[:3]], 0)
    n_all = len(rows)
    rows = [x for x in rows if ang(x["g"], g_first) <= 2.0]            # same rest pose only
    b_hi = IC.hard_iron_from_attitude(SI.signals(bank.real_path(s), True))
    ref_rot = Rotation.concatenate([x["rot"] for x in rows[:3]]).mean()
    M0 = np.mean([x["M"] for x in rows[:3]], 0)
    g0 = np.mean([x["g"] for x in rows[:3]], 0)
    yaw, tilt, tot, dmag, dmagn, dgrav, dgrav_q, phys_pred, obs_vs_phys = [], [], [], [], [], [], [], [], []
    for x in rows:
        dR = x["rot"] * ref_rot.inv()                    # world-frame change
        qd = dR.as_quat()                               # x, y, z, w
        tw = Rotation.from_quat([0, 0, qd[2], qd[3]] / np.linalg.norm([qd[2], qd[3]]))   # twist about world z
        sw = dR * tw.inv()
        yv = np.degrees(tw.as_rotvec()[2])
        yaw.append(yv); tilt.append(np.degrees(sw.magnitude())); tot.append(np.degrees(dR.magnitude()))
        dmag.append(ang(x["M"], M0)); dmagn.append(float(np.linalg.norm(x["M"]) - np.linalg.norm(M0)))
        dgrav.append(ang(x["g"], g0))
        dgrav_q.append(ang(x["rot"].inv().apply([0, 0, 1]), ref_rot.inv().apply([0, 0, 1])))
        M_phys = (x["rot"].inv() * ref_rot).apply(M0 - b_hi) + b_hi     # field if the arm had really turned
        phys_pred.append(ang(M_phys, M0))
        obs_vs_phys.append(ang(x["M"], M_phys))
    tm = np.array([x["t_min"] for x in rows]); tc = np.array([x["temp_c"] for x in rows])
    yaw, tilt, tot = np.array(yaw), np.array(tilt), np.array(tot)
    # yaw trend vs time and temperature
    A1 = np.c_[np.ones_like(tm), tm]
    c1, *_ = np.linalg.lstsq(A1, yaw, rcond=None)
    res1 = yaw - A1 @ c1
    r2_t = 1 - res1.var() / yaw.var()
    A2 = np.c_[np.ones_like(tm), tm, tc]
    c2, *_ = np.linalg.lstsq(A2, yaw, rcond=None)
    r2_tt = 1 - (yaw - A2 @ c2).var() / yaw.var()
    inc = np.diff(res1)
    late = tm > tm[-1] - 15
    res[s] = {
        "n_cycles": len(rows), "n_cycles_other_pose_excluded": n_all - len(rows), "span_min": float(tm[-1] - tm[0]),
        "hard_iron_b": [float(v) for v in b_hi],
        "e_mag_body_change_if_physical_deg_last15min": float(np.mean(np.array(phys_pred)[late])),
        "e_mag_body_observed_change_deg_last15min": float(np.mean(np.array(dmag)[late])),
        "e_observed_vs_physical_prediction_deg_last15min": float(np.mean(np.array(obs_vs_phys)[late])),
        "a_mag_body_dir_change_deg_p95": float(np.percentile(dmag, 95)),
        "b_gravity_body_change_deg_p95": float(np.percentile(dgrav, 95)),
        "temp_c_range": [float(tc.min()), float(tc.max())],
        "a_mag_body_dir_change_deg_max": float(np.max(dmag)), "a_mag_body_dir_change_deg_last15min": float(np.mean(np.array(dmag)[late])),
        "a_mag_body_norm_change_last15min": float(np.mean(np.array(dmagn)[late])),
        "b_gravity_body_change_deg_max": float(np.max(dgrav)), "b_gravity_body_change_deg_last15min": float(np.mean(np.array(dgrav)[late])),
        "b_gravity_from_quat_change_deg_last15min": float(np.mean(np.array(dgrav_q)[late])),
        "c_total_change_deg_last15min": float(np.mean(tot[late])), "c_yaw_deg_last15min": float(np.mean(yaw[late])),
        "c_tilt_deg_last15min": float(np.mean(tilt[late])),
        "c_yaw_share_pct_last15min": float(100 * np.mean(np.abs(yaw[late])) / np.mean(tot[late])),
        "c_yaw_share_of_squared_pct_last15min": float(100 * np.mean(yaw[late] ** 2) / np.mean(tot[late] ** 2)),
        "d_yaw_slope_deg_per_min": float(c1[1]), "d_r2_linear_time": float(r2_t), "d_r2_time_plus_temp": float(r2_tt),
        "d_temp_coef_deg_per_c": float(c2[2]), "d_corr_yaw_temp": float(np.corrcoef(yaw, tc)[0, 1]),
        "d_corr_time_temp": float(np.corrcoef(tm, tc)[0, 1]),
        "d_residual_sd_deg": float(res1.std()), "d_residual_lag1_autocorr": float(np.corrcoef(inc[:-1], inc[1:])[0, 1]) if len(inc) > 3 else None,
        "series": {"t_min": tm.tolist(), "temp_c": tc.tolist(), "yaw_deg": yaw.tolist(), "tilt_deg": tilt.tolist(),
                   "mag_body_change_deg": dmag, "gravity_body_change_deg": dgrav},
    }
    x = res[s]
    print(f"{s}: {x['n_cycles']} cycles (+{x['n_cycles_other_pose_excluded']} at another rest pose, left out) over {x['span_min']:.0f} min, temp {x['temp_c_range'][0]:.1f}–{x['temp_c_range'][1]:.1f} °C")
    print(f"   a) mag_body direction change: last 15 min {x['a_mag_body_dir_change_deg_last15min']:.2f}°, p95 {x['a_mag_body_dir_change_deg_p95']:.2f}°, max {x['a_mag_body_dir_change_deg_max']:.2f}°; |M| change {x['a_mag_body_norm_change_last15min']:+.2f}")
    print(f"   b) gravity_body (accel) change: last 15 min {x['b_gravity_body_change_deg_last15min']:.2f}°, p95 {x['b_gravity_body_change_deg_p95']:.2f}°, max {x['b_gravity_body_change_deg_max']:.2f}°; gravity from quat change {x['b_gravity_from_quat_change_deg_last15min']:.2f}°")
    print(f"   c) orientation change last 15 min: total {x['c_total_change_deg_last15min']:.2f}°, yaw {x['c_yaw_deg_last15min']:+.2f}°, tilt {x['c_tilt_deg_last15min']:.2f}° -> yaw share {x['c_yaw_share_pct_last15min']:.0f}% (of squared {x['c_yaw_share_of_squared_pct_last15min']:.0f}%)")
    print(f"   d) yaw slope {x['d_yaw_slope_deg_per_min']:+.4f}°/min, R² time {x['d_r2_linear_time']:.2f}, time+temp {x['d_r2_time_plus_temp']:.2f}, corr(yaw,temp) {x['d_corr_yaw_temp']:+.2f} (corr(time,temp) {x['d_corr_time_temp']:+.2f}), residual sd {x['d_residual_sd_deg']:.2f}°")
    print(f"   e) mag_body change last 15 min: observed {x['e_mag_body_observed_change_deg_last15min']:.2f}° vs {x['e_mag_body_change_if_physical_deg_last15min']:.2f}° if the arm had physically turned; "
          f"observed is {x['e_observed_vs_physical_prediction_deg_last15min']:.2f}° from the physical prediction")
json.dump(res, open(os.path.join(OUT, "drift_diagnosis.json"), "w"), indent=1)
