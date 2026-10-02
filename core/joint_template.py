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

Noise and timing model (measured on the real XDK, see PHYSICS_REPORT.md):
  * timing: the XDK samples on a regular internal clock (100.003 ms) and only the logged timestamp
    is offset: a heavy-tailed delivery delay (late sample then catch-up; backlogs delivered within a
    few ms) that is shared between sensors. Templates sit on the real internal clock; motion is
    evaluated on a regular synthetic clock and the written timestamp = clock + a real offset block
    (empirical_log_offsets; the same real time span for all sensors).
  * quaternion: the recorded quaternion, replayed as whole samples (no smoothing, nothing
    added), with the real per-sample freeze pattern (the XDK repeats its fused quaternion
    only while truly static). Output quantised to 1e-4, canonical w >= 0.
  * accel / mag: smoothed template shape + the residual (raw - smooth) of a DIFFERENT real
    cycle at the same phase. Real accel noise is clustered in time and depends on whether
    the arm moves, so a stationary Gaussian does not reproduce it. Quantised to 0.001 g / integer.
"""
import json
import os

import numpy as np
import pandas as pd
from scipy.signal import butter, savgol_filter, sosfiltfilt, welch
from scipy.spatial.transform import Rotation

Q_COLS = ("orientation_x", "orientation_y", "orientation_z")
A_COLS = ("acceleration_x", "acceleration_y", "acceleration_z")
M_COLS = ("mag_x", "mag_y", "mag_z")
REAL_ALIASES = {"quat_x": "orientation_x", "quat_y": "orientation_y", "quat_z": "orientation_z",
                "accel_x": "acceleration_x", "accel_y": "acceleration_y", "accel_z": "acceleration_z"}

Q_DECIMALS, A_DECIMALS = 4, 3          # XDK output resolution (1e-4, 0.001 g); mag is integer
SG_Q, SG_AM = (5, 2), (7, 2)           # savgol (window, order) for quat / accel+mag smoothing
SG_Q_RESID = np.sqrt(1 - 17 / 35)      # white-noise residual factor of savgol(5,2)
BANK_VERSION = 4                       # v2: per-sample real XDK freeze flag; v3: internal-clock template time;
                                       # v4: full real logged timestamps (empirical logging offsets)


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


def internal_clock(t: np.ndarray) -> np.ndarray:
    """Sample times on the XDK's regular internal clock. The logged timestamp = clock + logging
    jitter (outliers down to ~1 ms / up to ~150 ms between samples), so within each run without
    missing samples (dt < 1.5x nominal) the k-th sample sits at a fitted offset + k x period."""
    t = np.asarray(t, float)
    dt = np.diff(t)
    nominal = float(np.median(dt))
    breaks = np.r_[0, np.where(dt > 1.5 * nominal)[0] + 1, len(t)]
    out = np.empty_like(t)
    for a, b in zip(breaks[:-1], breaks[1:]):
        j = np.arange(b - a, dtype=float)
        if b - a >= 20:
            slope, icpt = np.polyfit(j, t[a:b], 1)
        else:
            slope, icpt = nominal, float(np.median(t[a:b] - j * nominal))
        out[a:b] = icpt + j * slope
    return np.maximum.accumulate(out)


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
               rest_pose_tol_deg: float = 2.0, smooth_quat: bool = False,
               am_split: str = "savgol") -> dict:
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
        # the real XDK repeats its fused quaternion exactly while truly static (93-95 % of
        # samples below 0.2°/s, ~0 % above): keep that per-sample pattern for the engine
        r["frozen"] = np.r_[False, np.all(r["q_raw_xyz"][1:] == r["q_raw_xyz"][:-1], axis=1)]

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
        if smooth_quat:
            qc = savgol_filter(r["q"], *SG_Q, axis=0)
            qc /= np.linalg.norm(qc, axis=1, keepdims=True)
        else:                       # unwrapped real quaternion as recorded
            qc = r["q"].copy()
        if am_split == "lowpass":
            # zero-phase low-pass whose rest residual matches the real rest noise spectrum
            fa = rest_matched_cutoff(r["A"], r["rest"])
            fm = rest_matched_cutoff(r["M"], r["rest"])
            Ac, Mc = lowpass(r["A"], fa), lowpass(r["M"], fm)
            r["cutoffs"] = {"accel_hz": fa, "mag_hz": fm}
        else:
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
                        "smooth_quat": bool(smooth_quat), "am_split": am_split,
                        "am_cutoffs": {s: R[s].get("cutoffs") for s in sensors}, "noise": {}}
    arrays["windows"] = (keep - t0).astype(np.float64)
    for s in sensors:
        r = R[s]
        m = (r["t"] >= keep[0, 0]) & (r["t"] <= keep[-1, 1])
        # template time axis = the real internal sample clock, not the jittered logged timestamp
        arrays[f"{s}/t"] = (internal_clock(r["t"])[m] - t0).astype(np.float64)
        for key in ("qc", "Ac", "Mc", "rA", "rM"):
            arrays[f"{s}/{key}"] = r[key][m].astype(np.float32)
        arrays[f"{s}/rest"] = r["rest"][m]
        arrays[f"{s}/frozen"] = r["frozen"][m]
        # boundary poses per window (start, end)
        arrays[f"{s}/pose_start"] = np.array([_pose_at(s, a) for a, _ in keep])
        arrays[f"{s}/pose_end"] = np.array([_pose_at(s, b) for _, b in keep])
        meta["noise"][s] = _noise_params(r)
        # whole real logged time axis (s, relative to t0): source of the empirical logging offsets
        arrays[f"{s}/log_t"] = (r["t"] - t0).astype(np.float64)
    arrays["meta"] = np.frombuffer(json.dumps(meta).encode(), dtype=np.uint8)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    np.savez_compressed(out_path, **arrays)
    return meta


CUTOFF_GRID_HZ = (0.3, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0)


def lowpass(X: np.ndarray, cutoff_hz: float, fs: float = 10.0, order: int = 4) -> np.ndarray:
    """Zero-phase Butterworth low-pass (sosfiltfilt) along the sample axis."""
    return sosfiltfilt(butter(order, cutoff_hz, fs=fs, output="sos"), X, axis=0)


def _rest_runs(rest: np.ndarray, min_len: int = 42, trim: int = 5) -> list:
    m = np.diff(np.r_[0, rest.astype(int), 0])
    return [(a + trim, b - trim) for a, b in zip(np.where(m == 1)[0], np.where(m == -1)[0]) if b - a >= min_len]


def rest_matched_cutoff(X: np.ndarray, rest: np.ndarray, grid=CUTOFF_GRID_HZ, fs: float = 10.0) -> float:
    """Cutoff whose low-pass residual, on the real rest periods, has the spectrum closest to the
    real rest noise (sample minus a linear trend per rest run): minimum over the grid of the mean
    |log2 PSD ratio| above 0.5 Hz (Welch, 32 samples)."""
    runs = [(a, b) for a, b in _rest_runs(rest) if b - a >= 32]
    noise = []
    for a, b in runs:
        seg = X[a:b]
        j = np.arange(len(seg))
        co = np.polyfit(j, seg, 1)
        noise.append((seg - (np.outer(j, co[0]) + co[1]))[:32])
    f, Pn = welch(np.vstack(noise), fs=fs, nperseg=32, axis=0)
    band = f >= 0.5
    best, err_best = grid[0], np.inf
    for fc in grid:
        res = X - lowpass(X, fc, fs)
        _, Pr = welch(np.vstack([res[a:a + 32] for a, b in runs]), fs=fs, nperseg=32, axis=0)
        err = float(np.mean(np.abs(np.log2(Pr[band].mean(1) / Pn[band].mean(1)))))
        if err < err_best:
            best, err_best = fc, err
    return float(best)


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
    # sd of the "gaussian" log_jitter model (bank v3 behaviour): treats the timestamp offset as
    # i.i.d., per-timestamp sd = sd(dt)/sqrt(2). The real offset is heavy tailed and bursty; the
    # default "empirical" model replays real offset blocks instead (empirical_log_offsets).
    d = np.diff(t)
    d = d[(d > 0.5 * np.median(d)) & (d < 1.5 * np.median(d))]
    return {"p_update_rest": float(1.0 - same[rr].mean()), "sig_rotvec_rad": 2.0 * sig_q,
            "log_jitter_ms": float(1000 * np.std(d) / np.sqrt(2))}


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
                                                     "pose_start", "pose_end", "frozen", "log_t")
                         if f"{s}/{k}" in z.files} for s in self.sensors}
        self.has_frozen = all("frozen" in self.data[s] for s in self.sensors)
        self.has_log_t = all("log_t" in self.data[s] for s in self.sensors)

    def real_path(self, sensor: str) -> str:
        return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(self.path)),
                                             self.meta["real_paths"][sensor]))

    def segment(self, sensor: str, i: int) -> dict:
        a, b = self.windows[i]
        d = self.data[sensor]
        lo, hi = np.searchsorted(d["t"], a), np.searchsorted(d["t"], b, side="right")
        return {"tau": d["t"][lo:hi] - a, "q": d["qc"][lo:hi].astype(float), "A": d["Ac"][lo:hi].astype(float),
                "M": d["Mc"][lo:hi].astype(float), "rA": d["rA"][lo:hi].astype(float),
                "rM": d["rM"][lo:hi].astype(float), "rest": d["rest"][lo:hi], "len": float(b - a),
                "frozen": d["frozen"][lo:hi] if "frozen" in d else None}


# ── schedule (shared by all sensors) ───────────────────────────────────────────

def build_schedule(bank: JointBank, duration_s: float, seed: int, local_window_s: float = 150.0,
                   warp_sd: float = 0.01, pose_tol_deg: float = 2.0, yaw_tol_deg: float = 3.0,
                   tick_s: float = None) -> tuple:
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
    if tick_s:                                  # cycle starts on the sample-clock grid
        s_t = np.round(s_t / tick_s) * tick_s
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
        warp = 1.0 + rng.normal(0, warp_sd) if warp_sd > 0 else 1.0
        sched.append({"start_s": float(s_t), "template": i, "warp": float(warp), "residual_donor": donor,
                      "phase": phase, "source_session_s": float(starts[i])})
        s_t += (np.round(lens[i] * warp / tick_s) * tick_s) if tick_s else lens[i] * warp
        prev = i
    info = {"n_cycles": len(sched), "n_pool_cycles": sum(c["phase"] == "pool" for c in sched),
            "n_pose_fallback": n_fallback,
            "splice_tilt_max_deg": float(max(gaps_tilt)) if gaps_tilt else 0.0,
            "splice_full_max_deg": float(max(gaps_full)) if gaps_full else 0.0,
            "beyond_recording": bool(duration_s > bank.recording_s)}
    return sched, info


# ── engine ─────────────────────────────────────────────────────────────────────

def _interp_segment(seg: dict, tau: np.ndarray, nearest: bool = False):
    tt = seg["tau"]
    tau = np.clip(tau, tt[0], tt[-1])
    if nearest:   # whole real samples (keeps the per-step noise texture of the recording)
        k = np.clip(np.searchsorted(tt, tau), 0, len(tt) - 1)
        k = np.where((k > 0) & (np.abs(tt[np.maximum(k - 1, 0)] - tau) < np.abs(tt[k] - tau)), k - 1, k)
        frozen = seg["frozen"][k] if seg.get("frozen") is not None else np.zeros(len(tau), bool)
        return seg["q"][k], seg["A"][k], seg["M"][k], seg["rest"][k], frozen
    j = np.clip(np.searchsorted(tt, tau) - 1, 0, len(tt) - 2)
    f = ((tau - tt[j]) / np.maximum(tt[j + 1] - tt[j], 1e-9))[:, None]
    q = seg["q"][j] * (1 - f) + seg["q"][j + 1] * f
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    A = seg["A"][j] * (1 - f) + seg["A"][j + 1] * f
    M = seg["M"][j] * (1 - f) + seg["M"][j + 1] * f
    near = np.clip(np.searchsorted(tt, tau), 0, len(tt) - 1)
    frozen = seg["frozen"][near] if seg.get("frozen") is not None else np.zeros(len(tau), bool)
    return q, A, M, seg["rest"][near], frozen


# ── logging-offset model (timestamp = internal clock tick + offset) ─────────────

def clock_period_ms(t: np.ndarray, span: int = 200, calm_ms: float = 4.0) -> float:
    """XDK internal sample period (ms) from calm-to-calm spans of `span` samples without missing
    ticks. (The median logged dt is biased: late samples skew it, e.g. 100.6 ms vs 100.0.)"""
    tm = np.asarray(t, float) * 1000.0
    p0 = float(np.median((tm[20:] - tm[:-20]) / 20))                 # robust first guess (short spans:
                                                                     # most hold no missing tick)
    dt = np.diff(tm)
    calm = np.r_[False, (np.abs(dt[:-1] - p0) < calm_ms) & (np.abs(dt[1:] - p0) < calm_ms), False]
    idx = np.where(calm[:-span])[0]
    idx = idx[calm[idx + span]]
    per = (tm[idx + span] - tm[idx]) / span
    per = per[np.abs(per - p0) < 0.5 * p0 / span]                    # drop spans that contain a missing tick
    return float(np.median(per)) if len(per) else p0


def _calm(tm: np.ndarray, P: float, calm_ms: float) -> np.ndarray:
    dt = np.diff(tm)
    return np.r_[False, (np.abs(dt[:-1] - P) < calm_ms) & (np.abs(dt[1:] - P) < calm_ms), False]


def _anchor_ticks(tm, P, calm, a, L, extra, tol_ms):
    """{tick: sample index} for ticks L..L+extra after calm sample a where the sample is calm and
    its offset is back within tol_ms of the start level."""
    hi = min(len(tm), a + L + extra + L // 10 + 20)
    g = np.round((tm[a:hi] - tm[a]) / P).astype(np.int64)
    res = tm[a:hi] - tm[a] - g * P
    ok = np.where((g >= L) & (g <= L + extra) & calm[a:hi] & (np.abs(res) <= tol_ms))[0]
    out = {}
    for i in ok:
        out.setdefault(int(g[i]), int(i))
    return out


def _offset_block(tm, P, a, b, L):
    """(offsets ms, present) for ticks 0..L-1 of the real block from calm sample a to anchor
    sample a+b (tick L). Ticks are assigned backwards from the anchor (the last sample of a backlog
    is the punctual one): u_i = min(u_{i+1} - 1, round((t_i - t_a) / P)). present[k] is False for
    a tick the real logger dropped (its offset is interpolated). None if the assignment is
    inconsistent."""
    u = np.round((tm[a:a + b + 1] - tm[a]) / P).astype(np.int64)
    u[-1] = L
    for i in range(b - 1, -1, -1):
        u[i] = min(u[i + 1] - 1, u[i])
    if u[0] != 0:
        return None
    o = tm[a:a + b + 1] - tm[a] - u * P
    present = np.zeros(L, bool)
    present[u[u < L]] = True
    return np.interp(np.arange(L), u, o), present


def empirical_log_offsets(bank: "JointBank", n_ticks: int, seed: int, block: int = 600,
                          extra: int = 60, calm_ms: float = 4.0, max_tries: int = 100000,
                          with_presence: bool = False):
    """Per-tick logging offsets (ms) for every sensor, block-resampled from the real recording.

    Real logged timestamps = regular internal tick + a delivery offset that is heavy tailed and
    comes in bursts (late sample then catch-up; backlogs of several samples delivered within a few
    ms), and the bursts are shared between sensors (same gateway). So whole real blocks of offsets
    are replayed, taken from the SAME real time span for all sensors: a block starts at a random
    real time tau, per sensor at its first calm sample (|dt - P| < calm_ms on both sides) after tau,
    and ends at the first tick L' in [block, block + extra] where every sensor has a calm sample
    whose offset is back within calm_ms of the start level, so consecutive blocks join with a
    step that is itself calm. Ticks the real logger dropped get interpolated offsets; with
    with_presence=True a second dict {sensor: present[tick]} is returned so the engine can drop
    the same ticks (real drop rate and pattern). The draw depends on (bank, seed) only, so
    separate runs of sensor_1/2/3 get the same block sequence."""
    rng = np.random.default_rng([seed, 7])
    prep = {}
    for s in bank.sensors:
        tm = bank.data[s]["log_t"] * 1000.0
        P = clock_period_ms(tm / 1000.0)
        calm = _calm(tm, P, calm_ms)
        prep[s] = (tm, P, calm, np.where(calm)[0])
    lo = max(v[0][0] for v in prep.values())
    hi = min(v[0][-1] for v in prep.values()) - 1.2 * (block + extra) * 100.0
    out = {s: [] for s in bank.sensors}
    pres = {s: [] for s in bank.sensors}
    got, tries = 0, 0
    while got < n_ticks:
        tries += 1
        if tries > max_tries:
            raise RuntimeError("could not draw clean logging-offset blocks")
        tau = rng.uniform(lo, hi)
        starts, anchors = {}, None
        for s, (tm, P, calm, ci) in prep.items():
            j = np.searchsorted(ci, np.searchsorted(tm, tau))
            if j >= len(ci):
                anchors = {}
                break
            starts[s] = int(ci[j])
            at = _anchor_ticks(tm, P, calm, starts[s], block, extra, calm_ms)
            anchors = set(at) if anchors is None else anchors & set(at)
            starts[s] = (starts[s], at)
        if not anchors:
            continue
        L = min(anchors)
        blk = {s: _offset_block(prep[s][0], prep[s][1], starts[s][0], starts[s][1][L], L) for s in prep}
        if any(v is None for v in blk.values()):
            continue
        for s in bank.sensors:
            out[s].append(blk[s][0])
            pres[s].append(blk[s][1])
        got += L
    offs = {s: np.concatenate(v)[:n_ticks] for s, v in out.items()}
    if with_presence:
        return offs, {s: np.concatenate(v)[:n_ticks] for s, v in pres.items()}
    return offs


def _dtw_map(a: np.ndarray, b: np.ndarray, band: int = 30) -> np.ndarray:
    """For each row of a, the index of b it aligns to under DTW (Sakoe-Chiba band, rows standardised
    by a's per-channel sd). Used to put a donor cycle's residual at the same motion phase."""
    sd = np.where(a.std(0) > 1e-9, a.std(0), 1.0)
    a, b = a / sd, b / sd
    n, m = len(a), len(b)
    D = np.full((n + 1, m + 1), np.inf)
    D[0, 0] = 0.0
    for i in range(1, n + 1):
        c = int(round((i - 1) * (m - 1) / max(n - 1, 1)))
        lo, hi = max(1, c + 1 - band), min(m, c + 1 + band)
        cost = np.sum((b[lo - 1:hi] - a[i - 1]) ** 2, axis=1)
        row = D[i, :]
        prev = D[i - 1, :]
        for jj, j in enumerate(range(lo, hi + 1)):
            row[j] = cost[jj] + min(prev[j], prev[j - 1], row[j - 1])
    # backtrack
    i, j, out = n, m, np.zeros(n, np.int64)
    while i > 0:
        out[i - 1] = j - 1
        k = np.argmin([D[i - 1, j - 1], D[i - 1, j], D[i, j - 1]])
        if k == 0:
            i, j = i - 1, j - 1
        elif k == 1:
            i -= 1
        else:
            j -= 1
        j = max(j, 1)
    return out


def _shape_distance(sa: dict, sb: dict, n: int = 100) -> float:
    """Distance between two cycles' smooth accel+mag shapes on a common normalised time axis."""
    u = np.linspace(0, 1, n)
    f = lambda sg, key: np.column_stack([np.interp(u * sg["tau"][-1], sg["tau"], sg[key][:, c]) for c in range(3)])
    da = np.c_[f(sa, "A"), f(sa, "M")]
    db = np.c_[f(sb, "A"), f(sb, "M")]
    sd = np.where(da.std(0) > 1e-9, da.std(0), 1.0)
    return float(np.mean(((da - db) / sd) ** 2))


class JointTemplateEngine:
    def __init__(self, bank_path: str, sensor: str, local_window_s: float = 150.0,
                 crossfade_s: float = 1.0, warp_sd: float = 0.01, pose_tol_deg: float = 2.0,
                 yaw_tol_deg: float = 3.0, rotvec_noise_scale: float = None,
                 regular_clock: bool = True, frequency_hz: float = 10.0, resample: str = "nearest",
                 log_jitter: str = None, log_block: int = 600, residual: str = "donor",
                 log_drops: bool = None):
        self.bank = JointBank(bank_path)
        if sensor not in self.bank.sensors:
            raise ValueError(f"sensor '{sensor}' not in bank {self.bank.sensors}")
        self.sensor = sensor
        self.local_window_s = local_window_s
        self.crossfade_s = crossfade_s
        self.warp_sd = warp_sd
        self.pose_tol_deg = pose_tol_deg
        self.yaw_tol_deg = yaw_tol_deg
        # raw templates already carry the real orientation noise: add none unless asked;
        # smoothed (savgol) templates get the measured motion floor back
        if rotvec_noise_scale is None:
            rotvec_noise_scale = 1.0 if self.bank.meta.get("smooth_quat", True) else 0.0
        self.rotvec_noise_scale = rotvec_noise_scale
        self.regular_clock = regular_clock
        if resample not in ("linear", "nearest"):
            raise ValueError("resample must be 'linear' or 'nearest'")
        self.resample = resample
        self.frequency_hz = frequency_hz
        # logged-timestamp offset model: "empirical" (real offset blocks, bank v4), "gaussian"
        # (bank v3 behaviour) or "none" (perfect ticks; diagnosis only)
        if log_jitter is None:
            log_jitter = "empirical" if self.bank.has_log_t else "gaussian"
        if log_jitter not in ("empirical", "gaussian", "none"):
            raise ValueError("log_jitter must be 'empirical', 'gaussian' or 'none'")
        if log_jitter == "empirical" and not self.bank.has_log_t:
            raise ValueError("log_jitter='empirical' needs a v4 bank (rebuild with build_joint_bank.py)")
        self.log_jitter = log_jitter
        self.log_block = log_block
        # drop the ticks the real logger dropped in the same offset blocks (empirical only)
        self.log_drops = (log_jitter == "empirical") if log_drops is None else bool(log_drops)
        if self.log_drops and log_jitter != "empirical":
            raise ValueError("log_drops needs log_jitter='empirical'")
        self.keep = None
        # accel/mag noise texture: "donor" = residual of another real cycle (production);
        # "own" = the template's own residual, i.e. raw accel/mag replay (diagnosis only)
        # "similar" = donor is the most similar cycle (accel+mag shape) in the same candidate set;
        # "aligned" = random donor, residual mapped to the template by motion phase (DTW on accel)
        # "lattice" = random donor, but its residual taken on the output lattice
        # (raw_donor - round(smooth_donor)) and added to round(smooth_template): the real raw value
        # already holds one quantisation error, adding a float residual and rounding again doubles it
        if residual not in ("donor", "own", "similar", "aligned", "lattice"):
            raise ValueError("residual must be 'donor', 'own', 'similar', 'aligned' or 'lattice'")
        self.residual = residual
        self.schedule, self.info = None, None

    def _similar_donor(self, template: int, phase: str) -> int:
        """Most similar other cycle (smooth accel+mag shape) among the schedule's donor candidates."""
        cache = self.__dict__.setdefault("_sim_cache", {})
        if (template, phase) not in cache:
            starts = self.bank.windows[:, 0]
            cand = (np.where(np.abs(starts - starts[template]) <= self.local_window_s)[0] if phase == "local"
                    else np.arange(len(starts)))
            cand = [j for j in cand if j != template]
            if not cand:
                cache[(template, phase)] = template
            else:
                seg = self.bank.segment(self.sensor, template)
                dist = [_shape_distance(seg, self.bank.segment(self.sensor, j)) for j in cand]
                cache[(template, phase)] = int(cand[int(np.argmin(dist))])
        return cache[(template, phase)]

    def _aligned_map(self, template: int, donor: int) -> np.ndarray:
        cache = self.__dict__.setdefault("_dtw_cache", {})
        if (template, donor) not in cache:
            a = self.bank.segment(self.sensor, template)["A"]
            b = self.bank.segment(self.sensor, donor)["A"]
            cache[(template, donor)] = _dtw_map(a, b)
        return cache[(template, donor)]

    @classmethod
    def from_config(cls, cfg: dict) -> "JointTemplateEngine":
        keys = ("local_window_s", "crossfade_s", "warp_sd", "pose_tol_deg", "yaw_tol_deg", "rotvec_noise_scale",
                "regular_clock", "frequency_hz", "resample", "log_jitter", "log_block", "residual", "log_drops")
        return cls(cfg["bank"], cfg["sensor"], **{k: cfg[k] for k in keys if k in cfg})

    def generate(self, timestamps_ms: np.ndarray, duration_s: float, seed: int,
                 origin_ms: float = None) -> dict:
        # Motion is a function of time on the generator's shared clock (origin_ms = the
        # scenario start), not of each file's first sample, so sensors stay aligned.
        origin = timestamps_ms[0] if origin_ms is None else origin_ms
        sensor_index = self.bank.sensors.index(self.sensor)
        noise = self.bank.meta["noise"][self.sensor]
        log_ts = None
        if self.regular_clock:
            # The XDK samples on a regular internal clock; only the LOGGED timestamp is offset
            # (real: step angle uncorrelated with dt). Motion is evaluated on that clock (gaps
            # kept as whole missing ticks); timestamps = clock + logging offset.
            nominal = 1000.0 / self.frequency_hz
            tsm = np.asarray(timestamps_ms, float)
            steps = np.r_[np.round((tsm[0] - origin) / nominal), np.maximum(1, np.round(np.diff(tsm) / nominal))]
            clock = origin + np.cumsum(steps) * nominal
            if self.log_jitter == "empirical":
                # offsets indexed by tick number, so sensors stay aligned across missing ticks
                tick = np.cumsum(steps).astype(np.int64)
                tick -= tick[0]
                off, pres = empirical_log_offsets(self.bank, int(tick[-1]) + 1, seed, self.log_block,
                                                  with_presence=True)
                log_ts = np.round(clock + off[self.sensor][tick])
                if self.log_drops:
                    self.keep = pres[self.sensor][tick]
            elif self.log_jitter == "gaussian":
                jit = np.random.default_rng([seed, sensor_index, 7]).normal(0, noise.get("log_jitter_ms", 0.0), len(clock))
                log_ts = np.round(clock + np.clip(jit, -0.45 * nominal, 0.45 * nominal))
            else:
                log_ts = np.round(clock)
            log_ts = np.maximum.accumulate(log_ts)                  # never out of order
            dup = np.r_[False, np.diff(log_ts) <= 0]
            while dup.any():                                        # keep timestamps strictly increasing
                log_ts[dup] += 1
                dup = np.r_[False, np.diff(log_ts) <= 0]
            ts = (clock - origin) / 1000.0
        else:
            ts = (np.asarray(timestamps_ms, float) - origin) / 1000.0
        tick = 1.0 / self.frequency_hz if (self.resample == "nearest" and self.regular_clock) else None
        sched, info = build_schedule(self.bank, max(duration_s, ts[-1]), seed, self.local_window_s,
                                     0.0 if tick else self.warp_sd, self.pose_tol_deg, self.yaw_tol_deg,
                                     tick_s=tick)
        self.schedule, self.info = sched, info
        rng = np.random.default_rng([seed, sensor_index])

        n = len(ts)
        Q = np.zeros((n, 4)); A = np.zeros((n, 3)); M = np.zeros((n, 3)); rest = np.zeros(n, bool)
        frozen = np.zeros(n, bool); xfade = np.zeros(n, bool)
        prev_end = None
        for ci, c in enumerate(sched):
            seg = self.bank.segment(self.sensor, c["template"])
            w = c["warp"]
            # a cycle runs until the next one starts, so every sample is owned by exactly one cycle
            end = sched[ci + 1]["start_s"] if ci + 1 < len(sched) else np.inf
            m = (ts >= c["start_s"]) & (ts < end)
            if m.any():
                el = ts[m] - c["start_s"]
                q, a, mg, rs, fz = _interp_segment(seg, el / w, self.resample == "nearest")
                # residual texture of another real cycle at the same phase (nearest sample)
                donor = c["residual_donor"]
                if self.residual == "similar":
                    donor = self._similar_donor(c["template"], c["phase"])
                don = self.bank.segment(self.sensor, donor)
                tau_d = np.clip(el / w * don["len"] / seg["len"], 0, don["tau"][-1])
                k = np.clip(np.searchsorted(don["tau"], tau_d), 0, len(don["tau"]) - 1)
                if self.residual == "aligned":
                    tt = seg["tau"]
                    ko = np.clip(np.searchsorted(tt, np.clip(el / w, tt[0], tt[-1])), 0, len(tt) - 1)
                    k = self._aligned_map(c["template"], donor)[ko]
                ra, rm = don["rA"][k], don["rM"][k]
                if self.residual == "lattice":
                    ad, md = don["A"][k], don["M"][k]
                    ra = np.round(ad + ra, A_DECIMALS) - np.round(ad, A_DECIMALS)
                    rm = np.round(md + rm) - np.round(md)
                    a, mg = np.round(a, A_DECIMALS), np.round(mg)
                if self.residual == "own":          # raw replay: same sample as the template shape
                    tt = seg["tau"]
                    tau = np.clip(el / w, tt[0], tt[-1])
                    ko = np.clip(np.searchsorted(tt, tau), 0, len(tt) - 1)
                    ko = np.where((ko > 0) & (np.abs(tt[np.maximum(ko - 1, 0)] - tau) < np.abs(tt[ko] - tau)), ko - 1, ko)
                    ra, rm = seg["rA"][ko], seg["rM"][ko]
                if prev_end is not None:            # crossfade from the previous cycle's end (at rest)
                    al = np.clip(el / self.crossfade_s, 0, 1)
                    al = (al * al * (3 - 2 * al))[:, None]
                    pq, pa, pm = prev_end
                    pq = np.where((q @ pq)[:, None] < 0, -pq, pq)
                    q = pq * (1 - al) + q * al
                    q /= np.linalg.norm(q, axis=1, keepdims=True)
                    a = pa * (1 - al) + a * al
                    mg = pm * (1 - al) + mg * al
                Q[m], A[m], M[m], rest[m], frozen[m] = q, a + ra, mg + rm, rs, fz
                if prev_end is not None:
                    xfade[m] = el < self.crossfade_s
            e = _interp_segment(seg, np.array([seg["tau"][-1]]))
            prev_end = (e[0][0], e[1][0], e[2][0])

        # orientation: motion noise in rotation space, canonical sign, XDK quantisation, rest hold
        r = Rotation.from_quat(np.c_[Q[:, 1:], Q[:, 0]]) * \
            Rotation.from_rotvec(rng.normal(0, noise["sig_rotvec_rad"] * self.rotvec_noise_scale, (n, 3)))
        xyzw = r.as_quat()
        Q = canonicalize(np.c_[xyzw[:, 3], xyzw[:, :3]])
        Qq = np.round(Q[:, 1:], Q_DECIMALS)
        if self.bank.has_frozen:
            # replay the real XDK freeze pattern of the template sample (not during a splice crossfade)
            hold = frozen & ~xfade
            for i in range(1, n):
                if hold[i]:
                    Qq[i] = Qq[i - 1]
        else:                                   # v1 banks: random hold at rest (old behaviour)
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
        if log_ts is not None:
            out["timestamp"] = log_ts.astype(np.int64)
        return out
