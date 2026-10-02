"""
physics_gate.py — mandatory physics gate for synthetic arm data (joint-template engine).

A gate, not a report: any failed check -> exit code 1 and a line naming the
sensor, the check, the value and the threshold. Thresholds are fixed here and
must not be tuned to make a run pass.

Checks (per sensor unless noted; real reference values are computed from the
real recording at gate time):
  validity     0 % samples with s = x²+y²+z² > 1 + 1e-3 (after quantisation)
  gravity      median quiet-sample gravity angle error < 2°
  omega        omega p99 within a per-sensor tolerance of the real p99, derived from data
               (gate_thresholds.json: real 60-min-window variation + 2 sd over seeds; ±25 % only
               when no thresholds file is given)
  jumps        0 one-sample quaternion jumps that are NOT a full q -> -q flip
  copy         % of cycle-length windows with max corr > 0.99 vs the real recording <= 5 %
               (sensor_3 excluded, see COPY_EXCLUDE)
  c2st         [per sensor, REPORTED ONLY — does not decide the gate] classifier two-sample test,
               real vs synthetic (motion features, 10 s windows, block folds): balanced accuracy
               vs a threshold = 95th percentile of a label-permutation null (same windows, same
               folds) + 2 sd over seeds (gate_thresholds.json)
  check7b      [cross-sensor] all-three moving-mask agreement >= 85 %
  check7c      [cross-sensor] activity cross-correlation lag = 0 ms for every pair

CLI
---
python3 physics_gate.py --syn sensor_1=a.csv --syn sensor_2=b.csv --syn sensor_3=c.csv \\
                        --bank configs/robot_arm/joint_bank_arm.npz [--no-cross]
"""
import argparse
import os
import sys
from dataclasses import dataclass

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_physics as V

THRESHOLDS = {
    "s_tol": 1e-3,            # validity tolerance on s
    "grav_median_deg": 2.0,
    "omega_rel_tol": 0.25,
    "jump_component": 0.3,    # one-sample change of a quaternion component that counts as a jump
    "flip_match": 0.1,        # |xyz_b + xyz_a| per component below this = full q -> -q flip
    "check7b_min_pct": 85.0,
    "check7c_lag_ms": 0.0,
    "copy_corr": 0.99,
    "copy_max_pct": 5.0,
}
COPY_EXCLUDE = {
    "sensor_3": "real sensor_3 cycles are near-identical to each other (held-out real vs "
                "training real max-corr 0.997), so similarity to the recording cannot separate "
                "replay from genuine data; the check is uninformative there.",
}
MOTION9 = ["orientation_x", "orientation_y", "orientation_z", "acceleration_x", "acceleration_y",
           "acceleration_z", "mag_x", "mag_y", "mag_z"]
ALIASES = {"quat_x": "orientation_x", "quat_y": "orientation_y", "quat_z": "orientation_z",
           "accel_x": "acceleration_x", "accel_y": "acceleration_y", "accel_z": "acceleration_z"}


@dataclass
class Check:
    name: str
    sensor: str
    value: float
    threshold: str
    passed: bool
    note: str = ""
    informational: bool = False      # shown, but does not decide the gate

    def line(self) -> str:
        tag = ("INFO-" if self.informational else "") + ("PASS" if self.passed else "FAIL")
        v = f"{self.value:.3f}" if isinstance(self.value, (float, int, np.floating)) else str(self.value)
        return f"[{tag}] {self.sensor:9} {self.name:10} value={v:>10}  required {self.threshold}" + \
               (f"   ({self.note})" if self.note else "")


class GateReport:
    def __init__(self):
        self.checks = []

    def add(self, c: Check):
        self.checks.append(c)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks if not c.informational)

    def to_dict(self) -> dict:
        return {"passed": self.passed,
                "checks": [{"name": c.name, "sensor": c.sensor,
                            "value": (float(c.value) if isinstance(c.value, (int, float, np.floating, np.integer)) else c.value),
                            "threshold": c.threshold, "passed": bool(c.passed), "note": c.note,
                            "informational": c.informational} for c in self.checks]}

    def format(self) -> str:
        lines = [c.line() for c in self.checks]
        failed = [c for c in self.checks if not c.passed and not c.informational]
        lines.append("PHYSICS GATE: " + ("PASSED" if not failed else
                     f"FAILED ({len(failed)} check(s): " + ", ".join(f"{c.sensor}/{c.name}" for c in failed) + ")"))
        return "\n".join(lines)


def _load(path):
    return V.load(path).rename(columns=ALIASES)


# ── per-sensor checks ─────────────────────────────────────────────────────────

def nonflip_jumps(d, omega_limit: float = None) -> tuple:
    """(n_jumps, n_gap_violations, n_gap_jumps).
    n_jumps: one-sample transitions (dt <= 2x median, same rule as the omega metric) where a
    quaternion component changes by > jump_component and the step is not a full q -> -q flip.
    Across a timestamp gap the sensor keeps rotating, so a component change there is not a
    one-sample jump; those transitions are instead checked by their double-cover-safe angular
    speed, which must not exceed omega_limit (real p99 +25 %, the omega band) (n_gap_violations)."""
    x = d[["orientation_x", "orientation_y", "orientation_z"]].to_numpy(float)
    a, b = x[:-1], x[1:]
    big = np.any(np.abs(b - a) > THRESHOLDS["jump_component"], axis=1)
    full_flip = np.all(np.abs(b + a) < THRESHOLDS["flip_match"], axis=1)
    t = V.elapsed_seconds(d)
    dt = np.diff(t)
    med = np.median(dt[dt > 0])
    normal = (dt > 0) & (dt <= 2 * med)
    n_jumps = int(np.sum(big & ~full_flip & normal))
    gap = big & ~full_flip & ~normal
    n_gap_viol = 0
    if gap.any() and omega_limit is not None:
        q, _, _ = V.reconstruct_quat(x[:, 0], x[:, 1], x[:, 2], None)
        i = np.where(gap)[0]
        ang = np.degrees(2 * np.arccos(np.clip(np.abs(np.sum(q[i] * q[i + 1], 1)), 0, 1)))
        n_gap_viol = int(np.sum(ang / np.maximum(dt[i], 1e-3) > omega_limit))
    return n_jumps, n_gap_viol, int(gap.sum())


def _grid(d, cols=MOTION9):
    t = V.elapsed_seconds(d)
    g = np.arange(0, t[-1], 0.1)
    return np.vstack([np.interp(g, t, d[c].to_numpy(float)) for c in cols]).T


def window_max_corr(Z, X, L):
    """Per-channel-centred multichannel Pearson of each non-overlapping L-sample window of Z,
    maximised over every offset in X (FFT cross-correlation)."""
    N, C = X.shape
    noff = N - L + 1
    cs = np.cumsum(np.r_[np.zeros((1, C)), X], 0)
    cs2 = np.cumsum(np.r_[np.zeros((1, C)), X ** 2], 0)
    ssum, ssq = cs[L:] - cs[:-L], cs2[L:] - cs2[:-L]
    den_x = np.sqrt(np.clip((ssq - ssum ** 2 / L).sum(1), 1e-12, None))
    nfft = 1 << int(np.ceil(np.log2(N + L)))
    FX = np.fft.rfft(X, nfft, axis=0)
    out = []
    for i in range(0, len(Z) - L + 1, L):
        W = Z[i:i + L] - Z[i:i + L].mean(0)
        dw = np.sqrt((W ** 2).sum())
        if dw < 1e-12:
            out.append(np.nan)
            continue
        num = np.fft.irfft(FX * np.conj(np.fft.rfft(W, nfft, axis=0)), nfft, axis=0)[:noff].sum(1)
        out.append(float(np.max(num / (den_x * dw))))
    return np.array(out)


def copy_pct(d_syn, d_real, period_s) -> float:
    X = _grid(d_real)
    mu, sd = X.mean(0), np.where(X.std(0) > 1e-9, X.std(0), 1.0)
    mc = window_max_corr((_grid(d_syn) - mu) / sd, (X - mu) / sd, int(round(period_s * 10)))
    return float(100 * np.nanmean(mc > THRESHOLDS["copy_corr"]))


def load_thresholds(path):
    import json
    return json.load(open(path)) if path and os.path.exists(path) else None


def per_sensor_checks(syn_path, real_path, sensor, period_s, report: GateReport, thresholds=None,
                      c2st_span=None):
    T = THRESHOLDS
    ds, dr = _load(syn_path), _load(real_path)
    qx, qy, qz, qw = V.quat_cols(ds)
    s = np.nan_to_num(qx) ** 2 + np.nan_to_num(qy) ** 2 + np.nan_to_num(qz) ** 2
    pct = float(100 * np.mean(s > 1 + T["s_tol"]))
    report.add(Check("validity", sensor, pct, f"= 0 % of s > 1+{T['s_tol']}", pct == 0.0,
                     f"max s {s.max():.5f}"))

    g = V.check_gravity(ds, "syn")["quantile_all"]["median"]
    report.add(Check("gravity", sensor, g, f"< {T['grav_median_deg']}°", g < T["grav_median_deg"]))

    om_s = np.percentile(V.omega_series(ds)["all"], 99)
    om_real_all = V.omega_series(dr)["all"]
    om_r = np.percentile(om_real_all, 99)
    tol = thresholds["omega_p99"][sensor]["rel_tol"] if thresholds else T["omega_rel_tol"]
    src = "data-derived" if thresholds else "default"
    lo, hi = om_r * (1 - tol), om_r * (1 + tol)
    report.add(Check("omega_p99", sensor, om_s, f"in [{lo:.2f}, {hi:.2f}] °/s (real {om_r:.2f} ±{100*tol:.1f}%, {src})",
                     lo <= om_s <= hi))

    gap_limit = om_r * (1 + T["omega_rel_tol"])
    nj, ngv, ngap = nonflip_jumps(ds, gap_limit)
    report.add(Check("jumps", sensor, nj, "= 0 non-flip quaternion jumps (one-sample steps)", nj == 0,
                     f"{ngap} transition(s) across timestamp gaps checked by angular speed"))
    report.add(Check("gap_jumps", sensor, ngv, f"= 0 gap transitions faster than real p99 +25% "
                     f"({gap_limit:.1f}°/s)", ngv == 0))

    if sensor in COPY_EXCLUDE:
        report.add(Check("copy", sensor, "n/a", "excluded", True, COPY_EXCLUDE[sensor]))
    else:
        cp = copy_pct(ds, dr, period_s)
        report.add(Check("copy", sensor, cp, f"<= {T['copy_max_pct']} % windows corr>{T['copy_corr']}",
                         cp <= T["copy_max_pct"]))

    if thresholds and "c2st" in thresholds:
        import sensor_identity as SI
        ss = SI.signals(syn_path, use_abs_time=False)
        start, span = c2st_span if c2st_span else (0.0, float(ss["t"][-1] - ss["t"][0]))
        sr = SI.real_span(SI.signals(real_path, use_abs_time=True), span, start)
        acc = SI.c2st_syn(sr, ss)
        thr = thresholds["c2st"][sensor]
        # reported metric, not a blocking check (user decision); threshold from a label-permutation null
        report.add(Check("c2st", sensor, acc, f"<= {thr['threshold']:.3f} (permutation null p95 {thr['null_p95']:.3f}"
                         f" + 2 sd seeds {2 * thr['seed_sd']:.3f})", acc <= thr["threshold"],
                         f"real span {start/60:.0f}-{(start+span)/60:.0f} min; reported, does not block",
                         informational=True))


def cross_sensor_checks(syn_paths: dict, real_paths: dict, report: GateReport):
    T = THRESHOLDS
    order = sorted(syn_paths)
    # joint-template sensors share the generator clock -> align on absolute timestamps
    c = V.check_inter_sensor([real_paths[k] for k in order], [syn_paths[k] for k in order],
                             syn_use_abs=True)["syn"]
    report.add(Check("check7b", "all", c["all_agree_pct"], f">= {T['check7b_min_pct']} %",
                     c["all_agree_pct"] >= T["check7b_min_pct"]))
    lags = {k: v["lag_ms"] for k, v in c["xcorr_lag"].items()}
    ok = all(abs(v) <= T["check7c_lag_ms"] for v in lags.values())
    report.add(Check("check7c", "all", max(abs(v) for v in lags.values()), "lag = 0 ms for every pair", ok,
                     ", ".join(f"{k} {v:+.0f}ms" for k, v in lags.items())))


def check_physics_gate(syn_paths: dict, real_paths: dict, period_s: float, cross_sensor: bool = True,
                       thresholds: dict = None, c2st_span=None) -> GateReport:
    report = GateReport()
    for sensor in sorted(syn_paths):
        per_sensor_checks(syn_paths[sensor], real_paths[sensor], sensor, period_s, report, thresholds, c2st_span)
    if cross_sensor and len(syn_paths) >= 2:
        cross_sensor_checks(syn_paths, real_paths, report)
    return report


def _kv(items):
    out = {}
    for it in items or []:
        k, _, v = it.partition("=")
        out[k] = v
    return out


def main():
    ap = argparse.ArgumentParser(description="Physics gate for synthetic arm data (exit 1 on failure).")
    ap.add_argument("--syn", action="append", required=True, help="sensor_name=synthetic.csv")
    ap.add_argument("--real", action="append", default=None, help="sensor_name=real.csv (default: from --bank)")
    ap.add_argument("--bank", default=None, help="joint-template bank (.npz): real paths + cycle period")
    ap.add_argument("--period", type=float, default=None, help="cycle period s (default: from --bank)")
    ap.add_argument("--no-cross", action="store_true", help="skip cross-sensor checks")
    ap.add_argument("--thresholds", default=None, help="gate_thresholds.json (default: next to --bank)")
    args = ap.parse_args()
    syn, real, period = _kv(args.syn), _kv(args.real), args.period
    thresholds = load_thresholds(args.thresholds)
    if args.bank:
        from core.joint_template import JointBank
        bank = JointBank(args.bank)
        period = period or bank.period
        thresholds = load_thresholds(args.thresholds or os.path.join(os.path.dirname(os.path.abspath(args.bank)),
                                                                     "gate_thresholds.json"))
        for s in syn:
            real.setdefault(s, bank.real_path(s))
    if period is None or any(s not in real for s in syn):
        print("Error: need --bank, or --real for every sensor plus --period")
        sys.exit(2)
    rep = check_physics_gate(syn, real, period, cross_sensor=not args.no_cross, thresholds=thresholds)
    print(rep.format())
    sys.exit(0 if rep.passed else 1)


if __name__ == "__main__":
    main()
