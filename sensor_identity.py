"""
sensor_identity.py — is synthetic sensor_k recognisable as real sensor_k? (Level 1 only)

Level 1 (this file): synthetic sensor_k is recognised as the same device/position as real sensor_k.
Level 2 (NOT answered here): which arm link sensor_k is mounted on. The sensor -> link mapping
is [USER TO VERIFY]; nothing in this file supports a Level-2 claim.

Two independent judges:
  1. Physical fingerprints F1–F6 (interpretable, heading-independent: each XDK has its own
     magnetometer heading, so absolute yaw is never compared).
       F1 gravity direction at rest, body frame (distribution of accel unit vectors)
       F2 body-frame rotation-axis distribution while moving (|axis| components; sign-free)
       F3 angle between rotation axis and gravity (0° = yaw about vertical, 90° = pitch/roll)
       F4 angular speed distribution while moving (p50 / p99)
       F5 magnetometer magnitude at rest (+ mean vector, reported only: heading-dependent)
       F6 inter-sensor relations: activity correlation, per-cycle rotation-amplitude ratio,
          counter-rotation frequency about the vertical
  2. A random-forest classifier on 10 s windows of motion columns only (quat, accel, mag and
     their derivatives). temp/light/humidity/pressure/id/timestamp are excluded: per-sensor
     temperature offsets alone would identify the device and make the test meaningless.

Gate (identity_checks): per sensor, synthetic recall >= 0.9 x real-holdout recall AND, for each
F1–F4, d(syn_k, real_k) < d(syn_k, real_j) for every j != k.
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation
from scipy.stats import ks_2samp, wasserstein_distance

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.joint_template import REAL_ALIASES, Q_COLS, A_COLS, M_COLS, _abs_seconds

MOVE_DEG_S = 3.0          # rotation counts as "moving" above this rate (same for every sensor)
WIN_S = 10.0              # classifier window
CYCLE_S = 37.0            # arm cycle, for the interleaved split
FEATURE_SETS = ("all", "no_mag", "frame_safe")


# ── per-sample signals ────────────────────────────────────────────────────────

def signals(path: str, use_abs_time: bool) -> dict:
    d = pd.read_csv(path).rename(columns=REAL_ALIASES)
    t = _abs_seconds(d["timestamp"])
    if not use_abs_time:
        t = t - t[0]
    x, y, z = (d[c].to_numpy(float) for c in Q_COLS)
    w = np.sqrt(np.clip(1 - (x * x + y * y + z * z), 0, None))
    rot = Rotation.from_quat(np.c_[x, y, z, w])                     # scipy normalises; q ~ -q
    A = d[list(A_COLS)].to_numpy(float)
    M = d[list(M_COLS)].to_numpy(float)
    dt = np.diff(t)
    rv = (rot[:-1].inv() * rot[1:]).as_rotvec()                      # body-frame step rotation
    ok = (dt > 0) & (dt <= 0.2)
    om_body = np.full((len(t), 3), np.nan)
    om_body[1:][ok] = np.degrees(rv[ok]) / dt[ok, None]              # deg/s, body frame
    om_world_z = np.full(len(t), np.nan)
    om_world_z[1:][ok] = (rot[1:][ok].apply(np.radians(om_body[1:][ok])))[:, 2] * 180 / np.pi
    grav = rot.inv().apply([0, 0, 1])                                # R^T z
    speed = np.linalg.norm(om_body, axis=1)
    sm = pd.Series(speed).rolling(10, center=True, min_periods=1).median().to_numpy()
    rest = (sm < MOVE_DEG_S) & (np.abs(np.linalg.norm(A, axis=1) - 1) < 0.05)
    return {"t": t, "Q": np.c_[x, y, z], "A": A, "M": M, "om": om_body, "speed": speed,
            "om_wz": om_world_z, "grav": grav, "rest": rest, "rot": rot}


# ── fingerprints ──────────────────────────────────────────────────────────────

def fingerprint(s: dict) -> dict:
    An = s["A"] / np.linalg.norm(s["A"], axis=1, keepdims=True)
    mv = np.isfinite(s["speed"]) & (s["speed"] > MOVE_DEG_S)
    axis = s["om"][mv] / s["speed"][mv, None]
    g = s["grav"][mv]
    ang = np.degrees(np.arccos(np.clip(np.abs(np.sum(axis * g, 1)), 0, 1)))   # 0 = about vertical
    rest, fallback = s["rest"], False
    if rest.mean() < 0.01:   # signal never comes to rest (old per-column generator): quietest 10 %
        sp = np.nan_to_num(s["speed"], nan=np.inf)
        rest, fallback = sp <= np.percentile(sp, 10), True
    return {"F1": An[rest], "F2": np.abs(axis), "F3": ang, "F4": s["speed"][mv],
            "F5": np.linalg.norm(s["M"][rest], axis=1), "F5_mean_vec": s["M"][rest].mean(0),
            "rest_fallback": fallback}


def fp_distance(fa: dict, fb: dict) -> dict:
    return {
        "F1": float(np.mean([wasserstein_distance(fa["F1"][:, i], fb["F1"][:, i]) for i in range(3)])),
        "F2": float(np.mean([wasserstein_distance(fa["F2"][:, i], fb["F2"][:, i]) for i in range(3)])),
        "F3": float(wasserstein_distance(fa["F3"], fb["F3"])),
        "F4": float(ks_2samp(fa["F4"], fb["F4"]).statistic),
        "F5": float(wasserstein_distance(fa["F5"], fb["F5"])),
    }


def fp_summary(f: dict) -> dict:
    return {"F1_mean_gravity_dir": f["F1"].mean(0).round(3).tolist(),
            "F2_axis_mean_abs": f["F2"].mean(0).round(2).tolist(),
            "F3_median_deg": round(float(np.median(f["F3"])), 1),
            "F3_pct_near_vertical(<20deg)": round(float(100 * np.mean(f["F3"] < 20)), 1),
            "F4_p50": round(float(np.percentile(f["F4"], 50)), 1),
            "F4_p99": round(float(np.percentile(f["F4"], 99)), 1),
            "F5_mag_median": round(float(np.median(f["F5"])), 1), "rest_fallback": f["rest_fallback"],
            "F5_mean_vec": f["F5_mean_vec"].round(0).tolist()}


def relations(sig: dict) -> dict:
    """F6 on a set of 3 sensors sharing a clock (real: absolute, synthetic: generator clock)."""
    keys = sorted(sig)
    t0 = max(sig[k]["t"][0] for k in keys)
    t1 = min(sig[k]["t"][-1] for k in keys)
    g = np.arange(t0, t1, 0.1)
    act, wz, ang = {}, {}, {}
    for k in keys:
        s = sig[k]
        am = np.interp(g, s["t"], np.linalg.norm(s["A"], axis=1))
        act[k] = pd.Series(am).rolling(10, center=True, min_periods=1).std().to_numpy()
        f = np.isfinite(s["om_wz"])
        wz[k] = np.interp(g, s["t"][f], s["om_wz"][f])
        sp = np.nan_to_num(s["speed"])
        ang[k] = np.interp(g, s["t"], sp)
    out = {}
    for i in range(3):
        for j in range(i + 1, 3):
            a, b = keys[i], keys[j]
            tag = f"{a[-1]}-{b[-1]}"
            out[f"act_corr_{tag}"] = float(np.corrcoef(act[a], act[b])[0, 1])
            both = (np.abs(wz[a]) > MOVE_DEG_S) & (np.abs(wz[b]) > MOVE_DEG_S)
            out[f"counter_rot_pct_{tag}"] = float(100 * np.mean(np.sign(wz[a][both]) != np.sign(wz[b][both]))) if both.any() else float("nan")
    # per-cycle rotation amplitude (integrated speed) ratio vs sensor_1
    n = int((t1 - t0) // CYCLE_S)
    per = {k: np.array([ang[k][int(c * CYCLE_S * 10):int((c + 1) * CYCLE_S * 10)].sum() * 0.1 for c in range(n)]) for k in keys}
    for k in keys[1:]:
        r = per[k] / np.maximum(per[keys[0]], 1e-6)
        out[f"amp_ratio_{k[-1]}/{keys[0][-1]}_median"] = float(np.median(r))
    return out


# ── classifier ────────────────────────────────────────────────────────────────

def _channels(s: dict, feature_set: str) -> np.ndarray:
    chans = [s["A"], s["om"], s["speed"][:, None], s["grav"]]
    if feature_set in ("all", "no_mag"):
        chans.insert(0, s["Q"])
    if feature_set == "all":
        chans.append(s["M"])
    return np.hstack(chans)


def window_features(s: dict, feature_set: str, t_origin: float = None):
    """Return (X, window_start_times). Stats per channel per 10 s window."""
    C = _channels(s, feature_set)
    t = s["t"]
    t0 = t[0] if t_origin is None else t_origin
    idx = ((t - t0) // WIN_S).astype(int)
    X, starts = [], []
    for w in np.unique(idx):
        m = idx == w
        if m.sum() < 0.8 * WIN_S * 10:
            continue
        seg = C[m]
        with np.errstate(all="ignore"):
            X.append(np.concatenate([np.nanmean(seg, 0), np.nanstd(seg, 0), np.nanpercentile(seg, 5, 0),
                                     np.nanpercentile(seg, 50, 0), np.nanpercentile(seg, 95, 0)]))
        starts.append(t0 + w * WIN_S)
    return np.nan_to_num(np.array(X)), np.array(starts)


def real_split(starts: np.ndarray, t0: float):
    """Interleaved per cycle: cycle%5==0 -> test, %5 in {1,4} -> buffer (dropped), else train."""
    c = (((starts - t0) + WIN_S / 2) // CYCLE_S).astype(int) % 5
    return c in (2, 3) if np.isscalar(c) else np.isin(c, (2, 3)), c == 0


def train_classifier(real_sig: dict, feature_set: str, seed: int = 0):
    from sklearn.ensemble import RandomForestClassifier
    keys = sorted(real_sig)
    t0 = max(real_sig[k]["t"][0] for k in keys)
    Xtr, ytr, Xte, yte = [], [], [], []
    for lab, k in enumerate(keys):
        X, st = window_features(real_sig[k], feature_set, t_origin=t0)
        tr, te = real_split(st, t0)
        Xtr.append(X[tr]); ytr += [lab] * int(tr.sum())
        Xte.append(X[te]); yte += [lab] * int(te.sum())
    clf = RandomForestClassifier(n_estimators=300, random_state=seed, n_jobs=-1)
    clf.fit(np.vstack(Xtr), np.array(ytr))
    return clf, np.vstack(Xte), np.array(yte), keys, t0


def confusion(clf, X, y, n=3):
    p = clf.predict(X)
    cm = np.zeros((n, n), int)
    for a, b in zip(y, p):
        cm[a, b] += 1
    recall = cm.diagonal() / np.maximum(cm.sum(1), 1)
    return cm, recall


def syn_windows(syn_sig: dict, keys, feature_set):
    X, y = [], []
    for lab, k in enumerate(keys):
        Xi, _ = window_features(syn_sig[k], feature_set)
        X.append(Xi); y += [lab] * len(Xi)
    return np.vstack(X), np.array(y)


# ── gate ──────────────────────────────────────────────────────────────────────

def identity_checks(syn_paths: dict, real_paths: dict, report):
    from physics_gate import Check
    keys = sorted(syn_paths)
    real = {k: signals(real_paths[k], use_abs_time=True) for k in keys}
    syn = {k: signals(syn_paths[k], use_abs_time=False) for k in keys}
    fr = {k: fingerprint(real[k]) for k in keys}
    fs = {k: fingerprint(syn[k]) for k in keys}
    for k in keys:
        d_own = fp_distance(fs[k], fr[k])
        d_oth = {j: fp_distance(fs[k], fr[j]) for j in keys if j != k}
        for F in ("F1", "F2", "F3", "F4"):
            nearest_other = min(d_oth[j][F] for j in d_oth)
            report.add(Check(f"id_{F}", k, d_own[F], f"< nearest other real sensor ({nearest_other:.4f})",
                             d_own[F] < nearest_other))
    clf, Xte, yte, ck, _ = train_classifier(real, "all")
    _, rec_real = confusion(clf, Xte, yte)
    Xs, ys = syn_windows(syn, ck, "all")
    _, rec_syn = confusion(clf, Xs, ys)
    for i, k in enumerate(ck):
        report.add(Check("id_clf", k, float(rec_syn[i]), f">= 0.9 x real-holdout recall ({rec_real[i]:.3f})",
                         rec_syn[i] >= 0.9 * rec_real[i]))
