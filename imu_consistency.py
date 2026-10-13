"""
imu_consistency.py — cross-column IMU consistency metrics for the arm (quat ↔ accel, quat ↔ mag).

Both compare a DISTRIBUTION in the synthetic file with the same distribution in the real recording;
neither is expected to be 0 in real data.

1. Gravity consistency while MOVING
   Angle between the gravity direction implied by the quaternion (R^T·[0,0,1], q body→world, the
   convention of validate_physics) and the normalised accelerometer, on moving samples (orientation
   speed, rolling median over 10 samples, >= 3 °/s). Real is not 0 here: linear acceleration of the
   arm adds to gravity. Reported: median and p95 of that angle.

2. Mag ↔ orientation
   Earth's field is fixed in the world frame, so m_world = R·(m_body − b) should be nearly constant.
   b (hard-iron offset) is estimated ONCE from the real recording, by linear least squares on
   R_i·b + m = R_i·M_i (unknowns b and the world field m), i.e. the offset that makes the real
   world-frame field most constant, and then subtracted from real and synthetic in the same way.
   (A sphere fit is ill-posed here: the arm only sweeps a narrow range of orientations.)
   Reported: spread = RMS angle of m_world from its mean direction, on moving samples.

Reference: the real recording's first 60 min (the span a 60-min synthetic file replays; also the
C2ST span). Thresholds (derive_gate_thresholds.py → gate_thresholds.json, "imu_consistency"):
per sensor and metric, rel_tol = |real half A − real half B| / ref + 2 sd over seeds / ref, where
A and B are the two contiguous 30-min halves of that reference span.
"""
import numpy as np
import pandas as pd

import sensor_identity as SI

MOVE_DEG_S = 3.0          # same "moving" rate as sensor_identity
SMOOTH_N = 10             # rolling median of the per-step speed
METRICS = ("grav_moving_median_deg", "grav_moving_p95_deg", "mag_world_spread_moving_deg")


def moving_mask(s: dict) -> np.ndarray:
    sm = pd.Series(s["speed"]).rolling(SMOOTH_N, center=True, min_periods=1).median().to_numpy()
    return sm >= MOVE_DEG_S


def hard_iron_from_attitude(s_real: dict, n: int = 20000, seed: int = 0) -> np.ndarray:
    """Hard-iron offset b from the real recording: least squares on R_i b + m = R_i M_i."""
    idx = np.random.default_rng(seed).choice(len(s_real["M"]), min(n, len(s_real["M"])), replace=False)
    Rm = s_real["rot"][idx].as_matrix()
    A = np.concatenate([Rm, np.broadcast_to(np.eye(3), Rm.shape)], axis=2).reshape(-1, 6)
    y = np.einsum("nij,nj->ni", Rm, s_real["M"][idx]).reshape(-1)
    sol, *_ = np.linalg.lstsq(A, y, rcond=None)
    return sol[:3]


def metrics(s: dict, b: np.ndarray, mask: np.ndarray = None) -> dict:
    """The three metrics on signals s (sensor_identity.signals), optionally restricted to mask."""
    mv = moving_mask(s)
    if mask is not None:
        mv = mv & mask
    An = s["A"] / np.linalg.norm(s["A"], axis=1, keepdims=True)
    e = np.degrees(np.arccos(np.clip(np.sum(s["grav"] * An, axis=1), -1, 1)))[mv]
    mw = s["rot"][mv].apply(s["M"][mv] - b)
    mw /= np.linalg.norm(mw, axis=1, keepdims=True)
    mu = mw.mean(0)
    mu /= np.linalg.norm(mu)
    ang = np.degrees(np.arccos(np.clip(mw @ mu, -1, 1)))
    return {"grav_moving_median_deg": float(np.median(e)), "grav_moving_p95_deg": float(np.percentile(e, 95)),
            "mag_world_spread_moving_deg": float(np.sqrt(np.mean(ang ** 2))), "moving_pct": float(100 * mv.mean())}


def real_reference(real_path: str, span_s: float = 3600.0) -> dict:
    """Hard-iron offset b (from the whole real recording) and the real reference metrics on the
    first span_s seconds (the span a synthetic file of that length replays; the same span as the
    C2ST), plus the two contiguous halves of that span. The mag spread grows with the span (the
    world-frame direction drifts slowly), so the reference span must match the synthetic one."""
    s = SI.signals(real_path, True)
    b = hard_iron_from_attitude(s)
    el = s["t"] - s["t"][0]
    w = el < span_s
    return {"b": b, "ref": metrics(s, b, w), "half_a": metrics(s, b, w & (el < span_s / 2)),
            "half_b": metrics(s, b, w & (el >= span_s / 2))}


def synthetic_metrics(syn_path: str, b: np.ndarray) -> dict:
    return metrics(SI.signals(syn_path, False), b)
