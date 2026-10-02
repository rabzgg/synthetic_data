"""
sensor_identity.py — can synthetic sensor_k be told apart from real sensor_k? (Level 1 only)

Level 1: synthetic sensor_k vs real sensor_k of the same device/position.
Level 2 (which arm link a sensor is on) is NOT answered here: the mapping is [USER TO VERIFY].

Tools (used by physics_gate.py, derive_gate_thresholds.py and identity_report.py):
  * C2ST — classifier two-sample test, real_k vs synthetic_k, motion features only (quat, accel,
    mag, body angular velocity, gravity from quat; never temp/light/humidity/pressure/id/timestamp),
    10 s windows, folds = contiguous blocks of 10 cycles. Compared with a real-vs-real baseline
    (interleaved halves of the same span). 0.5 = indistinguishable.
  * Fingerprints F1-F5 (heading-independent: each XDK has its own magnetometer heading):
       F1 gravity direction at rest (body frame)     F2 body-frame rotation-axis distribution
       F3 rotation axis vs gravity angle             F4 angular speed while moving
       F5 magnetometer magnitude at rest
    compared as d(synthetic_k, real_k) next to d(real_k half A, real_k half B).
  * F6 counter-rotation about the vertical between sensors, on quaternions slerped to a 10 Hz grid,
    with per-sensor relative thresholds and per motion episode.

An earlier "is sensor_k recognised as sensor_k" classifier was removed: the old per-column
generator passed it too (the sensors differ so much in mounting that any per-sensor marginal
match is recognised), so it had no power.
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
FEATURE_SETS = ("all", "no_mag", "frame_safe")   # "all" is used by the gate


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


# ── window features (C2ST) ─────────────────────────────────────────────────────

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


# ══ F6 and C2ST ═══════════════════════════════════════════════════════════════

GRID_HZ = 10.0
REL_MOVE = 0.2            # a sensor is "yawing" when |wz| > 20 % of its own p95 |wz|
EPISODE_MERGE_S = 1.0     # merge motion runs closer than this
EPISODE_MIN_S = 1.0
EPISODE_MIN_YAW_DEG = 1.0


def slerp_grid(path: str, smooth: bool = False) -> dict:
    """Quaternion slerped onto an absolute 10 Hz grid (unwrapped first, duplicate/non-increasing
    timestamps dropped) and the world-vertical yaw rate wz = [R_i·rotvec(R_i^-1 R_{i+1})]_z / dt."""
    from scipy.spatial.transform import Slerp
    from scipy.signal import savgol_filter
    d = pd.read_csv(path).rename(columns=REAL_ALIASES)
    t = _abs_seconds(d["timestamp"])
    x, y, z = (d[c].to_numpy(float) for c in Q_COLS)
    w = np.sqrt(np.clip(1 - (x * x + y * y + z * z), 0, None))
    q = np.c_[w, x, y, z]
    for i in range(1, len(q)):                        # unwrap
        if np.dot(q[i], q[i - 1]) < 0:
            q[i] = -q[i]
    keep = np.r_[True, np.diff(t) > 0]
    keep &= np.r_[True, np.maximum.accumulate(t)[:-1] < t[1:]] if len(t) > 1 else keep
    t, q = t[keep], q[keep]
    if smooth:
        q = savgol_filter(q, 5, 2, axis=0)
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    g = np.arange(np.ceil(t[0] * GRID_HZ) / GRID_HZ, t[-1], 1.0 / GRID_HZ)
    rot = Slerp(t, Rotation.from_quat(np.c_[q[:, 1:], q[:, 0]]))(g)
    rv = (rot[:-1].inv() * rot[1:]).as_rotvec()
    wz = np.degrees(rot[:-1].apply(rv)[:, 2]) * GRID_HZ
    return {"g": g[:-1], "wz": wz}


def _align(a: dict, b: dict):
    ia = np.round(a["g"] * GRID_HZ).astype(np.int64)
    ib = np.round(b["g"] * GRID_HZ).astype(np.int64)
    common, xa, xb = np.intersect1d(ia, ib, return_indices=True)
    return a["wz"][xa], b["wz"][xb]


def counter_rotation(a: dict, b: dict) -> dict:
    """Counter-rotation about the vertical between two sensors, per sample and per motion episode,
    with per-sensor relative thresholds."""
    wa, wb = _align(a, b)
    ta = REL_MOVE * np.percentile(np.abs(wa), 95)
    tb = REL_MOVE * np.percentile(np.abs(wb), 95)
    both = (np.abs(wa) > ta) & (np.abs(wb) > tb)
    per_sample = float(100 * np.mean(np.sign(wa[both]) != np.sign(wb[both]))) if both.any() else float("nan")
    moving = (np.abs(wa) > ta) | (np.abs(wb) > tb)
    edges = np.diff(np.r_[0, moving.astype(int), 0])
    st, en = list(np.where(edges == 1)[0]), list(np.where(edges == -1)[0])
    merged = []
    for s_, e_ in zip(st, en):
        if merged and (s_ - merged[-1][1]) / GRID_HZ < EPISODE_MERGE_S:
            merged[-1][1] = e_
        else:
            merged.append([s_, e_])
    n_ep, n_counted, n_counter = 0, 0, 0
    for s_, e_ in merged:
        if (e_ - s_) / GRID_HZ < EPISODE_MIN_S:
            continue
        n_ep += 1
        ya, yb = wa[s_:e_].sum() / GRID_HZ, wb[s_:e_].sum() / GRID_HZ
        if abs(ya) >= EPISODE_MIN_YAW_DEG and abs(yb) >= EPISODE_MIN_YAW_DEG:
            n_counted += 1
            n_counter += int(np.sign(ya) != np.sign(yb))
    return {"per_sample_pct": per_sample, "thr_a": float(ta), "thr_b": float(tb),
            "episodes": n_ep, "episodes_both_yaw": n_counted,
            "episode_counter_pct": float(100 * n_counter / n_counted) if n_counted else float("nan")}


def relations_v2(paths: dict, smooth: bool = False) -> dict:
    keys = sorted(paths)
    sg = {k: slerp_grid(paths[k], smooth) for k in keys}
    out = {}
    for i in range(3):
        for j in range(i + 1, 3):
            out[f"{keys[i][-1]}-{keys[j][-1]}"] = counter_rotation(sg[keys[i]], sg[keys[j]])
    return out


# ── C2ST ──────────────────────────────────────────────────────────────────────

def subset(s: dict, mask: np.ndarray) -> dict:
    return {k: (v[mask] if isinstance(v, np.ndarray) and len(v) == len(mask) else v)
            for k, v in s.items() if k != "rot"}


def windows_with_cycles(s: dict, feature_set: str = "all"):
    X, st = window_features(s, feature_set)
    cyc = (((st - s["t"][0]) + WIN_S / 2) // CYCLE_S).astype(int)
    return X, cyc


FOLD_BLOCK_CYCLES = 10    # C2ST folds are contiguous blocks of 10 cycles (~6 min)


def c2st(XA, fA, XB, fB, seed: int = 0, n_folds: int = 5, return_model: bool = False):
    """Mean balanced accuracy of a random forest separating set A from set B, cross-validated
    over fold ids fA/fB (block-of-cycles folds, see block_fold)."""
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import balanced_accuracy_score
    accs, imps = [], []
    for f in range(n_folds):
        trA, teA, trB, teB = fA % n_folds != f, fA % n_folds == f, fB % n_folds != f, fB % n_folds == f
        if teA.sum() == 0 or teB.sum() == 0:
            continue
        X = np.vstack([XA[trA], XB[trB]]); y = np.r_[np.zeros(trA.sum()), np.ones(trB.sum())]
        clf = RandomForestClassifier(n_estimators=200, random_state=seed, n_jobs=-1,
                                     class_weight="balanced").fit(X, y)
        Xt = np.vstack([XA[teA], XB[teB]]); yt = np.r_[np.zeros(teA.sum()), np.ones(teB.sum())]
        accs.append(balanced_accuracy_score(yt, clf.predict(Xt)))
        imps.append(clf.feature_importances_)
    return (float(np.mean(accs)), np.mean(imps, 0)) if return_model else float(np.mean(accs))


def block_fold(cyc: np.ndarray) -> np.ndarray:
    """Folds are contiguous blocks of cycles. With interleaved (cycle-level) folds, features that
    carry slow drift make the nearest training neighbour of every test window belong to the other
    half, which drives a real-vs-real C2ST far BELOW 0.5 (measured 0.18). Block folds remove both
    classes of a whole time block together."""
    return cyc // FOLD_BLOCK_CYCLES


def real_span(s_real: dict, span_s: float, start_s: float = 0.0) -> dict:
    el = s_real["t"] - s_real["t"][0]
    return subset(s_real, (el >= start_s) & (el < start_s + span_s))


def c2st_real_baseline(s_real_span: dict, seeds=(0, 1, 2, 3, 4), feature_set: str = "all") -> list:
    """Real vs real: interleaved halves (even/odd cycles, and cycle pairs) of the same span,
    block folds, x RF seeds."""
    X, cyc = windows_with_cycles(s_real_span, feature_set)
    out = []
    for scheme in ("even_odd", "pairs"):
        a = cyc % 2 == 0 if scheme == "even_odd" else (cyc % 4) < 2
        fold = block_fold(cyc)
        for sd in seeds:
            out.append(c2st(X[a], fold[a], X[~a], fold[~a], seed=sd))
    return out


def c2st_syn(s_real_span: dict, s_syn: dict, seed: int = 0, feature_set: str = "all", return_model=False):
    XR, cR = windows_with_cycles(s_real_span, feature_set)
    XS, cS = windows_with_cycles(s_syn, feature_set)
    return c2st(XR, block_fold(cR), XS, block_fold(cS), seed=seed, return_model=return_model)


def c2st_permutation_null(s_real_span: dict, s_syn: dict, n_perm: int = 100, seed: int = 0,
                          feature_set: str = "all") -> list:
    """Null distribution of the real-vs-synthetic C2ST under exchangeable labels: the SAME windows
    and the SAME block folds as c2st_syn, with the real/synthetic labels shuffled across the pooled
    windows (class sizes kept). Each permutation is one full cross-validated C2ST."""
    XR, cR = windows_with_cycles(s_real_span, feature_set)
    XS, cS = windows_with_cycles(s_syn, feature_set)
    X = np.vstack([XR, XS])
    fold = np.r_[block_fold(cR), block_fold(cS)]
    nR = len(XR)
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n_perm):
        lab = rng.permutation(len(X)) < nR            # True -> "real"
        out.append(c2st(X[lab], fold[lab], X[~lab], fold[~lab], seed=seed))
    return out


def fingerprint_split_distance(s_real_span: dict) -> dict:
    """d(real_A, real_B) for interleaved even/odd cycles of the same span."""
    cyc = (((s_real_span["t"] - s_real_span["t"][0])) // CYCLE_S).astype(int)
    a = cyc % 2 == 0
    return fp_distance(fingerprint(subset(s_real_span, a)), fingerprint(subset(s_real_span, ~a)))
