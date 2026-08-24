"""
validate_physics.py — physical-validity checker for synthetic XDK sensor output.

Measurement only. No generator changes. Every synthetic metric is reported next
to its REAL baseline. See PHYSICS_REPORT.md for the write-up.

Checks
------
1  Quaternion validity : s = x²+y²+z²  (max, %>1, %>1.001)
2  Gravity consistency : angle between accel and gravity predicted from the
                         quaternion, on quiet samples. Frame convention resolved
                         on the ARM (moving data); aquarium confirms.
3  Magnetic stability  : std of mag rotated into world frame (÷ mean|mag|); and
                         std|mag| as a quaternion-free control.
4  Angular velocity    : omega from consecutive quaternions (double-cover safe),
                         actual per-sample dt, large-gap intervals dropped.
5  Cross-column corr   : Pearson within each sensor group, real vs syn + delta.
6a clip-floor probe    : config/SensorRealism scan for explicit bounds (joint 1).
6b doublet-period probe: inter-peak spacing distribution in real joint 1.

Amendments applied (A1–A4): Step 2 reports both "all quiet" and "quiet & s≤1";
w for s>1 is clamped to 0 and that is stated; the quiet mask is a quantile
(quietest-half) with an added absolute-threshold run; joint-3 synthetic coverage
is a first-class row; the 4-combination frame test is run on the arm.

CLI
---
# single pair
python3 validate_physics.py --real R.csv --syn S.csv --name arm_j1 --out physics_out/

# full baseline suite (3 arm joints + aquarium variants)
python3 validate_physics.py --suite --out physics_out/ --json baseline_before.json

# compare a fresh suite run against a saved baseline (delta per metric)
python3 validate_physics.py --suite --out physics_out/ --baseline baseline_before.json
"""
import argparse, json, os, sys
import numpy as np
import pandas as pd

# ── IO ────────────────────────────────────────────────────────────────────────

def load(path):
    d = pd.read_csv(path); d.columns = [str(c).strip().strip('"') for c in d.columns]
    return d

def col(d, *names):
    for n in names:
        if n in d.columns:
            return pd.to_numeric(d[n], errors="coerce").to_numpy(float)
    return None

def elapsed_seconds(d):
    """Seconds from start. Handles ISO datetime, epoch-ms, epoch-seconds."""
    t = d["timestamp"]; tn = pd.to_numeric(t, errors="coerce")
    if tn.notna().mean() > 0.9:
        v = tn.to_numpy(float)
        dt = np.median(np.diff(v))
        div = 1000.0 if dt >= 10 else 1.0          # ms vs epoch-seconds
        return (v - v[0]) / div
    td = pd.to_datetime(t, errors="coerce", utc=True)
    return (td - td.iloc[0]).dt.total_seconds().to_numpy()

def quat_cols(d):
    qx = col(d, "quat_x", "orientation_x"); qy = col(d, "quat_y", "orientation_y")
    qz = col(d, "quat_z", "orientation_z"); qw = col(d, "quat_w", "orientation_w")
    return qx, qy, qz, qw

def accel_cols(d):
    return (col(d, "accel_x", "acceleration_x"), col(d, "accel_y", "acceleration_y"),
            col(d, "accel_z", "acceleration_z"))

def mag_cols(d):
    return col(d, "mag_x"), col(d, "mag_y"), col(d, "mag_z")

# ── quaternion helpers ─────────────────────────────────────────────────────────

def reconstruct_quat(qx, qy, qz, qw):
    """Return (Nx4 [w,x,y,z], w_source, s). If no w column, w = clamp(sqrt(1-s),0)
    (so s>1 → w=0, an INVALID rotation — reported, not hidden) and the whole
    quaternion sign is flipped for temporal continuity (double-cover)."""
    qx, qy, qz = np.nan_to_num(qx), np.nan_to_num(qy), np.nan_to_num(qz)
    s = qx**2 + qy**2 + qz**2
    if qw is not None:
        q = np.vstack([np.nan_to_num(qw), qx, qy, qz]).T
        return q, "stored", s
    w = np.sqrt(np.clip(1.0 - s, 0.0, None))       # s>1 -> w=0 (clamp)
    q = np.vstack([w, qx, qy, qz]).T
    for i in range(1, len(q)):
        if np.dot(q[i], q[i-1]) < 0:
            q[i] = -q[i]
    return q, "reconstructed(clamp w=0 for s>1)", s

def Rmat(w, x, y, z):
    return np.array([
        [1-2*(y*y+z*z), 2*(x*y-w*z),   2*(x*z+w*y)],
        [2*(x*y+w*z),   1-2*(x*x+z*z), 2*(y*z-w*x)],
        [2*(x*z-w*y),   2*(y*z+w*x),   1-2*(x*x+y*y)]])

def grav_pred_sensor(q_row, zsign=+1, transpose=True):
    """Gravity direction in sensor frame. Default = R^T·[0,0,+1] (q body->world),
    the convention resolved on the arm. Returned normalised."""
    R = Rmat(*q_row); z = np.array([0.0, 0.0, float(zsign)])
    v = (R.T @ z) if transpose else (R @ z)
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v

# ── quiet-sample masks ─────────────────────────────────────────────────────────

def accel_mag(d):
    ax, ay, az = accel_cols(d)
    A = np.vstack([ax, ay, az]).T
    return A, np.linalg.norm(A, axis=1)

def quiet_mask(amag, mode="quantile", win=20):
    """mode='quantile' -> quietest half (|accel-1|<0.05 AND rolling-std below its
    own median). mode='absolute' -> ||accel|-1|<0.02 AND rolling-std<0.01."""
    finite = np.isfinite(amag)
    rs = pd.Series(amag).rolling(win, center=True, min_periods=1).std().to_numpy()
    if mode == "absolute":
        return finite & (np.abs(amag-1) < 0.02) & (rs < 0.01)
    cut = np.nanpercentile(rs[finite], 50) if finite.any() else np.inf
    return finite & (np.abs(amag-1) < 0.05) & (rs < cut)

# ── Check 1: quaternion validity ───────────────────────────────────────────────

def check_validity(d):
    qx, qy, qz, _ = quat_cols(d)
    s = (np.nan_to_num(qx)**2 + np.nan_to_num(qy)**2 + np.nan_to_num(qz)**2)
    s = s[np.isfinite(s)]
    return {"max_s": float(s.max()), "pct_gt_1": float(100*np.mean(s > 1.0)),
            "pct_gt_1p001": float(100*np.mean(s > 1.001))}

# ── Check 2: gravity consistency (A1, A2, A3) ──────────────────────────────────

def _grav_errors(d, q, mask):
    An, _ = accel_mag(d); An = An / np.linalg.norm(An, axis=1, keepdims=True)
    idx = np.where(mask)[0]
    if len(idx) == 0:
        return np.array([]), idx
    if len(idx) > 25000:
        idx = np.random.default_rng(0).choice(idx, 25000, replace=False)
    e = np.empty(len(idx))
    for i, sidx in enumerate(idx):
        pred = grav_pred_sensor(q[sidx])
        e[i] = np.degrees(np.arccos(np.clip(np.dot(pred, An[sidx]), -1, 1)))
    return e, idx

def check_gravity(d, tag):
    A, amag = accel_mag(d)
    qx, qy, qz, qw = quat_cols(d)
    q, wsrc, s = reconstruct_quat(qx, qy, qz, qw)
    out = {"w_source": wsrc}
    for mode in ["quantile", "absolute"]:
        base = quiet_mask(amag, mode)
        # (i) all quiet samples ; (ii) quiet AND s<=1
        for sub, name in [(base, "all"), (base & (s <= 1.0), "s_le_1")]:
            e, idx = _grav_errors(d, q, sub)
            am = amag[sub] if np.any(sub) else np.array([])
            am = am[np.isfinite(am)]
            key = f"{mode}_{name}"
            out[key] = {
                "quiet_pct": float(100*np.mean(sub)),
                "n_used": int(len(idx)),
                "median": float(np.median(e)) if len(e) else None,
                "p90": float(np.percentile(e, 90)) if len(e) else None,
                "max": float(np.max(e)) if len(e) else None,
                # B1: how "still" the mask actually is — |accel| inside the mask
                "accel_median": float(np.median(am)) if len(am) else None,
                "accel_std": float(np.std(am)) if len(am) else None,
            }
    return out

# ── Check 3: magnetic world-frame stability ────────────────────────────────────

def check_mag(d):
    mx, my, mz = mag_cols(d)
    if mx is None:
        return {"has_mag": False}
    qx, qy, qz, qw = quat_cols(d)
    q, _, _ = reconstruct_quat(qx, qy, qz, qw)
    M = np.vstack([mx, my, mz]).T
    mmag = np.linalg.norm(M, axis=1)
    m = np.isfinite(mmag) & np.isfinite(q[:, 0])
    idx = np.where(m)[0]
    if len(idx) > 25000:
        idx = np.random.default_rng(1).choice(idx, 25000, replace=False)
    world = np.empty((len(idx), 3))
    for i, sidx in enumerate(idx):
        world[i] = Rmat(*q[sidx]) @ M[sidx]        # sensor -> world
    meanmag = float(np.nanmean(mmag))
    return {"has_mag": True, "mean_mag": meanmag,
            "std_mag_control": float(np.nanstd(mmag)),
            "world_std": [float(np.std(world[:, k])) for k in range(3)],
            "world_std_norm": [float(np.std(world[:, k])/meanmag) for k in range(3)] if meanmag else None}

# ── Check 4: angular velocity (actual dt, drop big gaps) ────────────────────────

def omega_series(d):
    """Angular speed (deg/s) between consecutive samples. Returns the array over
    good (non-gap) intervals, and the same restricted to transitions where BOTH
    endpoints are valid rotations (s<=1). Actual per-sample dt; gaps>2x median
    dropped (B2 / Step-4 note)."""
    qx, qy, qz, qw = quat_cols(d)
    q, _, s = reconstruct_quat(qx, qy, qz, qw)
    t = elapsed_seconds(d)
    dt = np.diff(t)
    med = np.median(dt[np.isfinite(dt) & (dt > 0)])
    good = np.isfinite(dt) & (dt > 0) & (dt <= 2*med)      # drop >2x median gaps
    qn = q.copy()                                          # double-cover align
    flip = np.where(np.sum(qn[1:]*qn[:-1], axis=1) < 0)[0] + 1
    qn[flip] *= -1
    cd = np.clip(np.sum(qn[1:]*qn[:-1], axis=1), -1, 1)    # cos(theta/2)
    omega = np.degrees(2*np.arccos(cd)) / np.where(dt > 0, dt, np.nan)
    valid_step = (s[:-1] <= 1.0) & (s[1:] <= 1.0)          # both ends valid
    om_all = omega[good & np.isfinite(omega)]
    om_sle1 = omega[good & valid_step & np.isfinite(omega)]
    return {"all": om_all, "s_le_1": om_sle1,
            "dt_median_s": float(med), "pct_dropped_gaps": float(100*np.mean(~good))}

def check_omega(d):
    s = omega_series(d)
    def stats(a):
        return {"median": float(np.median(a)), "p99": float(np.percentile(a, 99)),
                "max": float(np.max(a))} if len(a) else {"median": None, "p99": None, "max": None}
    out = {"dt_median_s": s["dt_median_s"], "pct_dropped_gaps": s["pct_dropped_gaps"],
           "all": stats(s["all"]), "s_le_1": stats(s["s_le_1"])}
    # kept for backward-compat / compare mode
    out.update(out["all"])
    return out

# ── Check 5: cross-column correlation ──────────────────────────────────────────

GROUPS = {"accel": ["ax", "ay", "az"], "mag": ["mx", "my", "mz"], "orient": ["qx", "qy", "qz"]}

def _axes(d):
    ax, ay, az = accel_cols(d); mx, my, mz = mag_cols(d); qx, qy, qz, _ = quat_cols(d)
    return {"ax": ax, "ay": ay, "az": az, "mx": mx, "my": my, "mz": mz,
            "qx": qx, "qy": qy, "qz": qz}

def _corr(a, b):
    if a is None or b is None:
        return None
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 10 or np.std(a[m]) < 1e-12 or np.std(b[m]) < 1e-12:
        return None
    return float(np.corrcoef(a[m], b[m])[0, 1])

def check_correlation(dr, ds):
    R, S = _axes(dr), _axes(ds)
    rows = []
    for g, ks in GROUPS.items():
        for i in range(3):
            for j in range(i+1, 3):
                a, b = ks[i], ks[j]
                cr, cs = _corr(R[a], R[b]), _corr(S[a], S[b])
                if cr is None and cs is None:
                    continue
                rows.append({"group": g, "pair": f"{a}-{b}", "real": cr, "syn": cs,
                             "delta": (abs(cr-cs) if (cr is not None and cs is not None) else None)})
    rows.sort(key=lambda r: (r["delta"] is not None, r["delta"] or 0), reverse=True)
    return rows

# ── Check 6a / 6b: open questions ──────────────────────────────────────────────

def check_clip_floor(config_path):
    if not config_path or not os.path.exists(config_path):
        return {"config": config_path, "found": None, "note": "config not found"}
    cfg = json.load(open(config_path)); hits = {}
    for cname, cc in cfg.get("columns", {}).items():
        if "orient" not in cname:
            continue
        realism = cc.get("realism", {}); params = cc.get("params", {})
        found = {k: realism[k] for k in ("clip_min", "clip_max", "min", "max", "range", "bounds") if k in realism}
        found.update({f"param.{k}": params[k] for k in ("clip_min", "clip_max", "min", "max") if k in params})
        hits[cname] = found or None
    return {"config": config_path, "orient_bounds": hits}

def count_cycles(d):
    """Number of detected peak-to-peak cycles in orientation_x (B3). Same detector
    as check_doublet, so a later doublet-detector fix can be shown as a delta."""
    from scipy.signal import find_peaks
    qx = col(d, "quat_x", "orientation_x")
    if qx is None:
        return None
    t = elapsed_seconds(d)
    g = np.arange(t[0], t[-1], 0.1); v = np.interp(g, t, np.nan_to_num(qx))
    sm = pd.Series(v).rolling(5, center=True, min_periods=1).mean().to_numpy()
    prom = (np.percentile(sm, 95) - np.percentile(sm, 5)) * 0.25
    pk, _ = find_peaks(sm, distance=int(0.5*10), prominence=prom)
    return int(len(pk))

def check_doublet(dr):
    """Inter-peak spacing distribution in real joint-1 orientation_x (bimodal?)."""
    from scipy.signal import find_peaks
    qx = col(dr, "quat_x", "orientation_x"); t = elapsed_seconds(dr)
    g = np.arange(t[0], t[-1], 0.1); v = np.interp(g, t, np.nan_to_num(qx))
    sm = pd.Series(v).rolling(5, center=True, min_periods=1).mean().to_numpy()
    prom = (np.percentile(sm, 95) - np.percentile(sm, 5)) * 0.25
    pk, _ = find_peaks(sm, distance=int(0.5*10), prominence=prom)
    gaps = np.diff(g[pk])
    if len(gaps) < 5:
        return {"n_peaks": int(len(pk)), "note": "too few peaks"}
    hist, edges = np.histogram(gaps, bins=20)
    return {"n_peaks": int(len(pk)), "gap_median_s": float(np.median(gaps)),
            "gap_mean_s": float(np.mean(gaps)), "gap_std_s": float(np.std(gaps)),
            "gap_p10_s": float(np.percentile(gaps, 10)), "gap_p90_s": float(np.percentile(gaps, 90)),
            "bimodal_hint": bool(np.percentile(gaps, 90) > 2.2*np.percentile(gaps, 10))}

# ── frame resolution (A4): 4-combo test on a moving dataset ─────────────────────

def frame_test(d):
    A, amag = accel_mag(d); An = A/np.linalg.norm(A, axis=1, keepdims=True)
    qx, qy, qz, qw = quat_cols(d)
    q, _, s = reconstruct_quat(qx, qy, qz, qw)
    mask = quiet_mask(amag, "quantile") & (s <= 1.0)
    idx = np.where(mask)[0]
    if len(idx) > 20000:
        idx = np.random.default_rng(0).choice(idx, 20000, replace=False)
    out = {}
    for transpose in (True, False):
        for zsign in (+1, -1):
            e = np.empty(len(idx))
            for i, sidx in enumerate(idx):
                pred = grav_pred_sensor(q[sidx], zsign=zsign, transpose=transpose)
                e[i] = np.degrees(np.arccos(np.clip(np.dot(pred, An[sidx]), -1, 1)))
            lbl = ("R^T" if transpose else "R") + f" z{zsign:+d}"
            out[lbl] = float(np.median(e))
    return out

# ── plots ──────────────────────────────────────────────────────────────────────

def make_plots(name, dr, ds, out):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    # gravity error histogram (real vs syn, quiet & s<=1)
    def errs(d):
        A, amag = accel_mag(d); qx, qy, qz, qw = quat_cols(d)
        q, _, s = reconstruct_quat(qx, qy, qz, qw)
        e, _ = _grav_errors(d, q, quiet_mask(amag, "quantile") & (s <= 1.0)); return e
    er, es = errs(dr), errs(ds)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    b = np.linspace(0, 180, 60)
    if len(er): ax.hist(er, bins=b, alpha=0.55, color="steelblue", density=True, label="real")
    if len(es): ax.hist(es, bins=b, alpha=0.55, color="darkorange", density=True, label="synthetic")
    ax.set_title(f"{name} — gravity angle error (quiet, s≤1)"); ax.set_xlabel("degrees"); ax.set_ylabel("density")
    ax.legend(); ax.grid(alpha=0.3); fig.tight_layout()
    fig.savefig(os.path.join(out, f"{name}_gravity_hist.png"), dpi=130); plt.close(fig)
    # s = x²+y²+z² time series with 1.0 line
    fig, ax = plt.subplots(figsize=(11, 4))
    for d, c, lb in [(dr, "steelblue", "real"), (ds, "darkorange", "synthetic")]:
        qx, qy, qz, _ = quat_cols(d); s = np.nan_to_num(qx)**2+np.nan_to_num(qy)**2+np.nan_to_num(qz)**2
        x = np.linspace(0, 1, len(s)); ax.plot(x, s, color=c, lw=0.6, alpha=0.7, label=lb)
    ax.axhline(1.0, color="red", ls="--", lw=1, label="validity limit s=1")
    ax.set_title(f"{name} — s = x²+y²+z² (>1 ⇒ not a rotation)"); ax.set_xlabel("normalized time"); ax.set_ylabel("s")
    ax.legend(fontsize=8); ax.grid(alpha=0.3); fig.tight_layout()
    fig.savefig(os.path.join(out, f"{name}_svalue_ts.png"), dpi=130); plt.close(fig)

# ── pair runner ─────────────────────────────────────────────────────────────────

def run_pair(real, syn, name, out, config_path=None, do_plots=True):
    dr, ds = load(real), load(syn)
    # B2: % of synthetic omega samples exceeding the REAL reference speeds
    om_r, om_s = omega_series(dr)["all"], omega_series(ds)["all"]
    real_max = float(np.max(om_r)) if len(om_r) else None
    real_p99 = float(np.percentile(om_r, 99)) if len(om_r) else None
    exceed = {
        "real_max_ref": real_max, "real_p99_ref": real_p99,
        "syn_pct_over_real_max": float(100*np.mean(om_s > real_max)) if (real_max and len(om_s)) else None,
        "syn_pct_over_real_p99": float(100*np.mean(om_s > real_p99)) if (real_p99 and len(om_s)) else None,
    }
    res = {"name": name, "real_path": real, "syn_path": syn,
           "validity": {"real": check_validity(dr), "syn": check_validity(ds)},
           "gravity": {"real": check_gravity(dr, "real"), "syn": check_gravity(ds, "syn")},
           "mag": {"real": check_mag(dr), "syn": check_mag(ds)},
           "omega": {"real": check_omega(dr), "syn": check_omega(ds), "exceed": exceed},
           "cycles": {"real": count_cycles(dr), "syn": count_cycles(ds)},   # B3
           "correlation": check_correlation(dr, ds)}
    if do_plots:
        os.makedirs(out, exist_ok=True); make_plots(name, dr, ds, out)
    return res

# ── suite ────────────────────────────────────────────────────────────────────

SUITE = [
    ("arm_j1", "ppt/arm_robot/sensor_1_real.csv", "ppt/arm_robot/sensor_1_syn.csv", "configs/robot_arm/sensor_1_normal.json"),
    ("arm_j2", "ppt/arm_robot/sensor_2_real.csv", "ppt/arm_robot/sensor_2_syn.csv", "configs/robot_arm/sensor_2_normal.json"),
    ("arm_j3", "ppt/arm_robot/sensor_3_real.csv", "ppt/arm_robot/sensor_3_syn.csv", "configs/robot_arm/sensor_3_normal.json"),
    ("aquarium_fit100", "ppt/aquarium/aquarium_xdk1_real.csv", "ppt/aquarium/aquarium_xdk1_100pct_syn.csv", None),
    ("aquarium_fit50",  "ppt/aquarium/aquarium_xdk1_real.csv", "ppt/aquarium/aquarium_xdk1_50pct_syn.csv", None),
    ("aquarium_opus",   "ppt/aquarium/aquarium_xdk1_real.csv", "ppt/aquarium/aquarium_xdk1_opus_syn.csv", None),
]

def run_suite(out, do_plots=True):
    res = {"pairs": {}, "frame_resolution": {}, "open_questions": {}}
    dr1 = load(SUITE[0][1])
    res["frame_resolution"]["arm_j1_real"] = frame_test(dr1)
    res["frame_resolution"]["aquarium_real_confirm"] = frame_test(load(SUITE[3][1]))
    for name, real, syn, cfg in SUITE:
        print(f"  [{name}] ...", flush=True)
        res["pairs"][name] = run_pair(real, syn, name, out, cfg, do_plots)
    res["open_questions"]["clip_floor_j1"] = check_clip_floor(SUITE[0][3])
    res["open_questions"]["doublet_period_j1"] = check_doublet(dr1)
    return res

# ── compare mode ────────────────────────────────────────────────────────────

def _g(pair, side, mode="quantile_s_le_1", key="median"):
    try: return pair["gravity"][side][mode][key]
    except Exception: return None

def compare(cur, base):
    print(f"\n{'pair':18}{'metric':26}{'baseline':>12}{'current':>12}{'delta':>10}")
    print("-"*80)
    for name in cur["pairs"]:
        c = cur["pairs"][name]; b = base["pairs"].get(name)
        if not b: continue
        rows = [
            ("grav syn median (s≤1)", _g(c,"syn"), _g(b,"syn")),
            ("validity syn %s>1", c["validity"]["syn"]["pct_gt_1"], b["validity"]["syn"]["pct_gt_1"]),
            ("omega syn max", c["omega"]["syn"]["max"], b["omega"]["syn"]["max"]),
        ]
        for lbl, cv, bv in rows:
            if cv is None or bv is None: continue
            print(f"{name:18}{lbl:26}{bv:>12.3f}{cv:>12.3f}{cv-bv:>+10.3f}")

# ── main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Physical-validity checker (measurement only).")
    ap.add_argument("--real"); ap.add_argument("--syn"); ap.add_argument("--name", default="pair")
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", default="physics_out/")
    ap.add_argument("--suite", action="store_true")
    ap.add_argument("--json", default=None, help="write results JSON here")
    ap.add_argument("--baseline", default=None, help="compare suite run to this baseline JSON")
    ap.add_argument("--no-plots", action="store_true")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    if args.suite:
        res = run_suite(args.out, do_plots=not args.no_plots)
        outjson = args.json or os.path.join(args.out, "physics_suite.json")
        json.dump(res, open(outjson, "w"), indent=2)
        print(f"\nwrote {outjson}")
        if args.baseline and os.path.exists(args.baseline):
            compare(res, json.load(open(args.baseline)))
        return
    if not args.real or not args.syn:
        print("Provide --real and --syn, or --suite."); sys.exit(1)
    res = run_pair(args.real, args.syn, args.name, args.out, args.config, do_plots=not args.no_plots)
    outjson = args.json or os.path.join(args.out, f"physics_{args.name}.json")
    json.dump(res, open(outjson, "w"), indent=2)
    print(f"wrote {outjson}")

if __name__ == "__main__":
    main()
