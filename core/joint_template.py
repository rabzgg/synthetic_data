"""
joint_template.py — joint-template motion engine for multi-XDK robot-arm data.

Why this exists
---------------
The per-column engines (cycle_template, periodic_motion, ...) generate every
motion column independently, each with its own template pick and its own
period. For a rotating sensor that breaks the coupling between the quaternion
axes (s = x²+y²+z² > 1, partial hemisphere flips → omega p99 722°/s), between
orientation and accel (gravity error 36°) and between the three sensors on the
arm (Check 7). See PHYSICS_REPORT.md, "Joint template".

This engine instead replays WHOLE real cycles: one template is one real arm
cycle holding [quat, accel, mag] of every sensor over the same time span, and
one cycle schedule (template index + start time + time warp) is shared by all
sensors. Physical consistency is therefore inherited from the recording.

Pipeline
--------
1. build_bank(real_paths, out_path)            — once, from the real recordings
2. JointTemplateEngine(bank, sensor).generate() — per sensor, from SyntheticXDKGenerator
   when the scenario has  "motion": {"joint_template": true, ...}  (default OFF).

The schedule is a pure function of (bank, duration_s, seed), so separate
main.py runs for sensor_1/2/3 with the same --seed and --duration produce the
same schedule without talking to each other.

Noise model (measured on the real XDK, see PHYSICS_REPORT.md):
  * quaternion: rest = sample-and-hold (the fused quaternion only updates with
    the measured per-sample probability, 23-37%); motion = small rotation-vector
    noise at the measured floor. Output quantised to 1e-4, canonical w >= 0.
  * accel / mag: smoothed template shape + the residual (raw - smooth) of a
    DIFFERENT real cycle at the same phase. Real accel noise is clustered in
    time and depends on whether the arm moves, so a stationary Gaussian does
    not reproduce it. Quantised to 0.001 g / integer.
"""
import json
import os

import numpy as np
import pandas as pd
from scipy.signal import savgol_filter
from scipy.spatial.transform import Rotation

Q_COLS = ("orientation_x", "orientation_y", "orientation_z")
A_COLS = ("acceleration_x", "acceleration_y", "acceleration_z")
M_COLS = ("mag_x", "mag_y", "mag_z")
REAL_ALIASES = {"quat_x": "orientation_x", "quat_y": "orientation_y", "quat_z": "orientation_z",
                "accel_x": "acceleration_x", "accel_y": "acceleration_y", "accel_z": "acceleration_z"}

Q_DECIMALS, A_DECIMALS = 4, 3          # XDK output resolution (1e-4, 0.001 g); mag is integer
SG_Q, SG_AM = (5, 2), (7, 2)           # savgol (window, order) for quat / accel+mag smoothing
SG_Q_RESID = np.sqrt(1 - 17 / 35)      # white-noise residual factor of savgol(5,2)
BANK_VERSION = 1


# ── quaternion helpers ─────────────────────────────────────────────────────────

def canonicalize(q: np.ndarray) -> np.ndarray:
    """[w,x,y,z] rows -> w >= 0. A flip negates ALL four components together."""
    q = np.array(q, dtype=float, copy=True)
    q[q[:, 0] < 0] *= -1.0
    return q


def unwrap(q: np.ndarray) -> np.ndarray:
    """Remove hemisphere flips: negate q_i when dot(q_i, q_{i-1}) < 0."""
    q = np.array(q, dtype=float, copy=True)
    for i in range(1, len(q)):
        if np.dot(q[i], q[i - 1]) < 0:
            q[i] = -q[i]
    return q


def reconstruct_w(x, y, z) -> np.ndarray:
    s = x * x + y * y + z * z
    return np.vstack([np.sqrt(np.clip(1.0 - s, 0.0, None)), x, y, z]).T


def gravity_body(q: np.ndarray) -> np.ndarray:
    """Gravity direction in the sensor frame, R^T·[0,0,1] (convention resolved on the arm)."""
    return Rotation.from_quat(np.c_[q[:, 1:], q[:, 0]]).inv().apply([0.0, 0.0, 1.0])


def angle_deg(qa: np.ndarray, qb: np.ndarray) -> np.ndarray:
    """Rotation angle between unit quaternions (double-cover safe)."""
    return np.degrees(2 * np.arccos(np.clip(np.abs(np.sum(qa * qb, axis=-1)), 0.0, 1.0)))


def tilt_deg(qa: np.ndarray, qb: np.ndarray) -> np.ndarray:
    ga, gb = gravity_body(np.atleast_2d(qa)), gravity_body(np.atleast_2d(qb))
    return np.degrees(np.arccos(np.clip(np.sum(ga * gb, axis=-1), -1.0, 1.0)))


# ── real-data loading / analysis ───────────────────────────────────────────────

def _abs_seconds(ts: pd.Series) -> np.ndarray:
    tn = pd.to_numeric(ts, errors="coerce")
    if tn.notna().mean() > 0.9:
        v = tn.to_numpy(float)
        return v / 1000.0 if np.median(np.diff(v)) >= 10 else v
    epoch = pd.Timestamp("1970-01-01", tz="UTC")
    return (pd.to_datetime(ts, errors="coerce", utc=True) - epoch).dt.total_seconds().to_numpy()


def load_real(path: str) -> dict:
    d = pd.read_csv(path).rename(columns=REAL_ALIASES)
    t = _abs_seconds(d["timestamp"])
    q = unwrap(reconstruct_w(*(d[c].to_numpy(float) for c in Q_COLS)))
    return {"t": t, "q_raw_xyz": d[list(Q_COLS)].to_numpy(float), "q": q,
            "A": d[list(A_COLS)].to_numpy(float), "M": d[list(M_COLS)].to_numpy(float)}


def omega_smooth(t: np.ndarray, q: np.ndarray, win_s: float = 1.0) -> np.ndarray:
    dt = np.diff(t)
    om = angle_deg(q[1:], q[:-1]) / np.where(dt > 0, dt, np.nan)
    om = np.r_[om[0], om]
    n = max(1, int(round(win_s / np.median(dt))))
    return pd.Series(om).rolling(n, center=True, min_periods=1).median().fillna(0).to_numpy()


def motion_threshold(om: np.ndarray) -> float:
    return max(2.0, 0.15 * np.percentile(om, 95))


def detect_period(grid_dt: float, activity: np.ndarray, lo_s: float = 10.0, hi_s: float = 120.0) -> float:
    """Dominant cycle period of the combined activity signal (first strong autocorr peak)."""
    from scipy.signal import find_peaks
    a = activity - activity.mean()
    n = min(len(a), int(20 * hi_s / grid_dt))
    a = a[:n]
    f = np.fft.rfft(a, 2 * n)
    ac = np.fft.irfft(f * np.conj(f))[:n]
    ac /= ac[0]
    lo, hi = int(lo_s / grid_dt), int(hi_s / grid_dt)
    pk, _ = find_peaks(ac[lo:hi], height=0.5)
    if len(pk) == 0:
        raise ValueError("no cycle period found in the combined motion signal")
    return float((pk[0] + lo) * grid_dt)


def detect_cycles(t: np.ndarray, om: np.ndarray, thr: float, period: float) -> np.ndarray:
    """Cycle windows bounded by the middle of the longest quiet run in each period-sized slot,
    so splices happen while the arm is at rest. A slot without a quiet run restarts the
    search; the pair across that break is not a cycle."""
    quiet = om < thr
    edges = np.diff(np.r_[0, quiet.astype(int), 0])
    starts, ends = np.where(edges == 1)[0], np.where(edges == -1)[0]
    runs = [(t[s], t[e - 1]) for s, e in zip(starts, ends) if t[e - 1] - t[s] >= 1.0]
    if not runs:
        return np.empty((0, 2))
    mids = np.array([(a + b) / 2 for a, b in runs])
    lens = np.array([b - a for a, b in runs])
    first_slot = mids < t[0] + period
    bounds = [mids[first_slot][np.argmax(lens[first_slot])] if first_slot.any() else mids[0]]
    cycles = []
    while True:
        m = (mids > bounds[-1] + 0.7 * period) & (mids < bounds[-1] + 1.3 * period)
        if m.any():
            nb = mids[m][np.argmax(lens[m])]
            cycles.append((bounds[-1], nb))
            bounds.append(nb)
            continue
        later = mids > bounds[-1] + 1.3 * period
        if not later.any():
            break
        bounds.append(mids[later][0])
    return np.array(cycles)


# ── bank ───────────────────────────────────────────────────────────────────────

def build_bank(real_paths: dict, out_path: str, length_tol: float = 0.04,
               rest_pose_tol_deg: float = 2.0) -> dict:
    """Fit a joint-template bank from the real recordings of all sensors on one arm.

    real_paths : {sensor_name: csv_path}, all recorded on the same clock.
    Keeps cycles whose length is within length_tol·period of the period and whose
    boundaries sit at rest for every sensor (start pose of each sensor within
    rest_pose_tol_deg of its pose at the previous cycle's end).
    """
    sensors = list(real_paths)
    R = {s: load_real(p) for s, p in real_paths.items()}
    for s in sensors:
        r = R[s]
        r["om"] = omega_smooth(r["t"], r["q"])
        r["rest"] = r["om"] < motion_threshold(r["om"])

    # shared windows from the combined (per-sensor normalised) speed
    t0 = max(R[s]["t"][0] for s in sensors)
    t1 = min(R[s]["t"][-1] for s in sensors)
    g = np.arange(t0, t1, 0.1)
    comb = np.zeros(len(g))
    for s in sensors:
        comb = np.maximum(comb, np.interp(g, R[s]["t"], R[s]["om"]) / motion_threshold(R[s]["om"]))
    period = detect_period(0.1, (comb > 1.0).astype(float))   # binary moving mask: clean 37 s peak
    windows = detect_cycles(g, comb, 1.0, period)

    out, keep = {}, []
    for s in sensors:
        r = R[s]
        qc = savgol_filter(r["q"], *SG_Q, axis=0)
        qc /= np.linalg.norm(qc, axis=1, keepdims=True)
        Ac = savgol_filter(r["A"], *SG_AM, axis=0)
        Mc = savgol_filter(r["M"], *SG_AM, axis=0)
        r.update(qc=qc, Ac=Ac, Mc=Mc, rA=r["A"] - Ac, rM=r["M"] - Mc)

    for wi, (a, b) in enumerate(windows):
        if abs((b - a) - period) > length_tol * period:
            continue
        ok = True
        for s in sensors:
            m = (R[s]["t"] >= a) & (R[s]["t"] <= b)
            if m.sum() < 0.8 * period * 10 or not (R[s]["rest"][m][0] and R[s]["rest"][m][-1]):
                ok = False
                break
        if ok:
            keep.append((a, b))
    if len(keep) < 5:
        raise ValueError(f"only {len(keep)} usable cycles found; need >= 5")

    # drop cycles that start far from the previous kept cycle's end pose in any sensor
    # (boundary detected mid-motion); the first cycle is kept.
    def _pose_at(s, tt):
        i = int(np.clip(np.searchsorted(R[s]["t"], tt), 0, len(R[s]["t"]) - 1))
        return R[s]["qc"][i]
    clean_keep = [keep[0]]
    for a, b in keep[1:]:
        pa, pb = clean_keep[-1]
        if abs(a - pb) < 1e-6:          # contiguous with the previous kept cycle
            if any(tilt_deg(_pose_at(s, pb), _pose_at(s, a))[0] > rest_pose_tol_deg for s in sensors):
                continue
        clean_keep.append((a, b))
    keep = np.array(clean_keep)

    arrays, meta = {}, {"version": BANK_VERSION, "sensors": sensors, "period_s": period,
                        "t0_abs": t0, "recording_s": float(t1 - t0),
                        "real_paths": {s: os.path.relpath(os.path.abspath(p), os.path.dirname(os.path.abspath(out_path)))
                                       for s, p in real_paths.items()},
                        "n_windows_detected": int(len(windows)), "n_windows_kept": int(len(keep)),
                        "noise": {}}
    arrays["windows"] = (keep - t0).astype(np.float64)
    for s in sensors:
        r = R[s]
        m = (r["t"] >= keep[0, 0]) & (r["t"] <= keep[-1, 1])
        arrays[f"{s}/t"] = (r["t"][m] - t0).astype(np.float64)
        for key in ("qc", "Ac", "Mc", "rA", "rM"):
            arrays[f"{s}/{key}"] = r[key][m].astype(np.float32)
        arrays[f"{s}/rest"] = r["rest"][m]
        # boundary poses per window (start, end)
        arrays[f"{s}/pose_start"] = np.array([_pose_at(s, a) for a, _ in keep])
        arrays[f"{s}/pose_end"] = np.array([_pose_at(s, b) for _, b in keep])
        meta["noise"][s] = _noise_params(r)
    arrays["meta"] = np.frombuffer(json.dumps(meta).encode(), dtype=np.uint8)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    np.savez_compressed(out_path, **arrays)
    return meta


def _noise_params(r: dict) -> dict:
    t, q, Qraw, rest = r["t"], r["q"], r["q_raw_xyz"], r["rest"]
    rr = rest[1:] & rest[:-1] & (np.diff(t) < 0.2)
    same = np.all(Qraw[1:] == Qraw[:-1], axis=1)
    dt = np.maximum(np.diff(t), 1e-3)
    speed = np.r_[angle_deg(q[1:], q[:-1]) / dt, 0.0]
    resid = np.linalg.norm(q[:, 1:] - savgol_filter(q[:, 1:], *SG_Q, axis=0), axis=1) / np.sqrt(3)
    m = ~rest & (speed < 6) & np.r_[np.diff(t) < 0.2, False]
    if m.sum() < 100:
        m = ~rest & (speed < 10)
    sig_q = float(np.sqrt(np.mean(resid[m] ** 2)) / SG_Q_RESID)
    return {"p_update_rest": float(1.0 - same[rr].mean()), "sig_rotvec_rad": 2.0 * sig_q}


class JointBank:
    def __init__(self, path: str):
        z = np.load(path)
        self.path = path
        self.meta = json.loads(bytes(z["meta"]).decode())
        self.windows = z["windows"]
        self.sensors = self.meta["sensors"]
        self.period = self.meta["period_s"]
        self.recording_s = self.meta["recording_s"]
        self.data = {s: {k: z[f"{s}/{k}"] for k in ("t", "qc", "Ac", "Mc", "rA", "rM", "rest",
                                                     "pose_start", "pose_end")} for s in self.sensors}

    def real_path(self, sensor: str) -> str:
        return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(self.path)),
                                             self.meta["real_paths"][sensor]))

    def segment(self, sensor: str, i: int) -> dict:
        a, b = self.windows[i]
        d = self.data[sensor]
        lo, hi = np.searchsorted(d["t"], a), np.searchsorted(d["t"], b, side="right")
        return {"tau": d["t"][lo:hi] - a, "q": d["qc"][lo:hi].astype(float), "A": d["Ac"][lo:hi].astype(float),
                "M": d["Mc"][lo:hi].astype(float), "rA": d["rA"][lo:hi].astype(float),
                "rM": d["rM"][lo:hi].astype(float), "rest": d["rest"][lo:hi], "len": float(b - a)}


# ── schedule (shared by all sensors) ───────────────────────────────────────────

def build_schedule(bank: JointBank, duration_s: float, seed: int, local_window_s: float = 150.0,
                   warp_sd: float = 0.01, pose_tol_deg: float = 2.0, yaw_tol_deg: float = 3.0) -> tuple:
    """Shared cycle schedule. Inside the recording span a cycle at synthetic time t is drawn
    from real cycles near session time t (drift is carried). Past the recording, cycles come
    from the whole pool, constrained so the end pose of cycle i matches the start pose of
    cycle i+1 in every sensor (tilt < pose_tol_deg, full angle < yaw_tol_deg).
    Returns (schedule list, info dict). Depends only on (bank, duration_s, seed, params)."""
    rng = np.random.default_rng(seed)
    W = bank.windows
    starts = W[:, 0]
    lens = W[:, 1] - W[:, 0]
    n = len(W)
    P = bank.period
    sensors = bank.sensors
    ps = {s: bank.data[s]["pose_start"] for s in sensors}
    pe = {s: bank.data[s]["pose_end"] for s in sensors}

    sched, s_t, prev = [], -rng.uniform(0, P), None
    n_fallback, gaps_tilt, gaps_full = 0, [], []
    while s_t < duration_s:
        t_sess = max(s_t, 0.0)
        if t_sess + P <= bank.recording_s:
            phase = "local"
            cand = np.where(np.abs(starts - t_sess) <= local_window_s)[0]
            if len(cand) == 0:
                cand = np.argsort(np.abs(starts - t_sess))[:3]
        else:
            phase = "pool"
            cand = np.arange(n)
        if prev is not None:
            tilt = np.max([tilt_deg(np.repeat(pe[s][prev][None], len(cand), 0), ps[s][cand]) for s in sensors], axis=0)
            full = np.max([angle_deg(pe[s][prev][None], ps[s][cand]) for s in sensors], axis=0)
            ok = (tilt < pose_tol_deg) & (full < yaw_tol_deg) if phase == "pool" else (tilt < pose_tol_deg)
            if ok.any():
                cand = cand[ok]
            else:
                n_fallback += 1
                cand = cand[[np.argmin(np.maximum(tilt / pose_tol_deg, full / yaw_tol_deg))]]
        i = int(rng.choice(cand))
        if prev is not None:
            gaps_tilt.append(max(float(tilt_deg(pe[s][prev], ps[s][i])[0]) for s in sensors))
            gaps_full.append(max(float(angle_deg(pe[s][prev], ps[s][i])) for s in sensors))
        donors = [j for j in (np.where(np.abs(starts - starts[i]) <= local_window_s)[0] if phase == "local"
                              else np.arange(n)) if j != i]
        donor = int(rng.choice(donors)) if donors else i
        warp = 1.0 + rng.normal(0, warp_sd)
        sched.append({"start_s": float(s_t), "template": i, "warp": float(warp), "residual_donor": donor,
                      "phase": phase, "source_session_s": float(starts[i])})
        s_t += lens[i] * warp
        prev = i
    info = {"n_cycles": len(sched), "n_pool_cycles": sum(c["phase"] == "pool" for c in sched),
            "n_pose_fallback": n_fallback,
            "splice_tilt_max_deg": float(max(gaps_tilt)) if gaps_tilt else 0.0,
            "splice_full_max_deg": float(max(gaps_full)) if gaps_full else 0.0,
            "beyond_recording": bool(duration_s > bank.recording_s)}
    return sched, info


# ── engine ─────────────────────────────────────────────────────────────────────

def _interp_segment(seg: dict, tau: np.ndarray):
    tt = seg["tau"]
    tau = np.clip(tau, tt[0], tt[-1])
    j = np.clip(np.searchsorted(tt, tau) - 1, 0, len(tt) - 2)
    f = ((tau - tt[j]) / np.maximum(tt[j + 1] - tt[j], 1e-9))[:, None]
    q = seg["q"][j] * (1 - f) + seg["q"][j + 1] * f
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    A = seg["A"][j] * (1 - f) + seg["A"][j + 1] * f
    M = seg["M"][j] * (1 - f) + seg["M"][j + 1] * f
    near = np.clip(np.searchsorted(tt, tau), 0, len(tt) - 1)
    return q, A, M, seg["rest"][near]


class JointTemplateEngine:
    def __init__(self, bank_path: str, sensor: str, local_window_s: float = 150.0,
                 crossfade_s: float = 1.0, warp_sd: float = 0.01, pose_tol_deg: float = 2.0,
                 yaw_tol_deg: float = 3.0):
        self.bank = JointBank(bank_path)
        if sensor not in self.bank.sensors:
            raise ValueError(f"sensor '{sensor}' not in bank {self.bank.sensors}")
        self.sensor = sensor
        self.local_window_s = local_window_s
        self.crossfade_s = crossfade_s
        self.warp_sd = warp_sd
        self.pose_tol_deg = pose_tol_deg
        self.yaw_tol_deg = yaw_tol_deg
        self.schedule, self.info = None, None

    @classmethod
    def from_config(cls, cfg: dict) -> "JointTemplateEngine":
        keys = ("local_window_s", "crossfade_s", "warp_sd", "pose_tol_deg", "yaw_tol_deg")
        return cls(cfg["bank"], cfg["sensor"], **{k: cfg[k] for k in keys if k in cfg})

    def generate(self, timestamps_ms: np.ndarray, duration_s: float, seed: int,
                 origin_ms: float = None) -> dict:
        # Motion is a function of time on the generator's shared clock (origin_ms = the
        # scenario start), not of each file's first sample, so sensors stay aligned.
        origin = timestamps_ms[0] if origin_ms is None else origin_ms
        ts = (np.asarray(timestamps_ms, float) - origin) / 1000.0
        sched, info = build_schedule(self.bank, max(duration_s, ts[-1]), seed, self.local_window_s,
                                     self.warp_sd, self.pose_tol_deg, self.yaw_tol_deg)
        self.schedule, self.info = sched, info
        sensor_index = self.bank.sensors.index(self.sensor)
        rng = np.random.default_rng([seed, sensor_index])
        noise = self.bank.meta["noise"][self.sensor]

        n = len(ts)
        Q = np.zeros((n, 4)); A = np.zeros((n, 3)); M = np.zeros((n, 3)); rest = np.zeros(n, bool)
        prev_end = None
        for c in sched:
            seg = self.bank.segment(self.sensor, c["template"])
            w = c["warp"]
            m = (ts >= c["start_s"]) & (ts < c["start_s"] + seg["len"] * w)
            if m.any():
                el = ts[m] - c["start_s"]
                q, a, mg, rs = _interp_segment(seg, el / w)
                # residual texture of another real cycle at the same phase (nearest sample)
                don = self.bank.segment(self.sensor, c["residual_donor"])
                tau_d = np.clip(el / w * don["len"] / seg["len"], 0, don["tau"][-1])
                k = np.clip(np.searchsorted(don["tau"], tau_d), 0, len(don["tau"]) - 1)
                ra, rm = don["rA"][k], don["rM"][k]
                if prev_end is not None:            # crossfade from the previous cycle's end (at rest)
                    al = np.clip(el / self.crossfade_s, 0, 1)
                    al = (al * al * (3 - 2 * al))[:, None]
                    pq, pa, pm = prev_end
                    pq = np.where((q @ pq)[:, None] < 0, -pq, pq)
                    q = pq * (1 - al) + q * al
                    q /= np.linalg.norm(q, axis=1, keepdims=True)
                    a = pa * (1 - al) + a * al
                    mg = pm * (1 - al) + mg * al
                Q[m], A[m], M[m], rest[m] = q, a + ra, mg + rm, rs
            e = _interp_segment(seg, np.array([seg["tau"][-1]]))
            prev_end = (e[0][0], e[1][0], e[2][0])

        # orientation: motion noise in rotation space, canonical sign, XDK quantisation, rest hold
        r = Rotation.from_quat(np.c_[Q[:, 1:], Q[:, 0]]) * \
            Rotation.from_rotvec(rng.normal(0, noise["sig_rotvec_rad"], (n, 3)))
        xyzw = r.as_quat()
        Q = canonicalize(np.c_[xyzw[:, 3], xyzw[:, :3]])
        Qq = np.round(Q[:, 1:], Q_DECIMALS)
        upd = rng.random(n) < noise["p_update_rest"]
        for i in range(1, n):
            if rest[i] and rest[i - 1] and not upd[i]:
                Qq[i] = Qq[i - 1]
        Aq = np.round(A, A_DECIMALS)
        Mq = np.round(M)
        out = {c: Qq[:, j] for j, c in enumerate(Q_COLS)}
        out.update({c: Aq[:, j] for j, c in enumerate(A_COLS)})
        out.update({c: Mq[:, j] for j, c in enumerate(M_COLS)})
        out["mag_res"] = np.linalg.norm(Mq, axis=1)
        return out
