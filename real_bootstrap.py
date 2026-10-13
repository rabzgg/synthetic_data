"""
real_bootstrap.py — sampling uncertainty of a REAL statistic, by a moving-block bootstrap over arm cycles.

A 60-min synthetic file is compared with 60 min of real data. Even two genuine 60-min recordings of the
same arm would not give the same omega p99 or the same activity correlation between two sensors. This
module estimates that spread from the real recording itself:

  * the reference span (real first 60 min) is cut into consecutive cycles of the bank period, from the
    common start;
  * a bootstrap sample = blocks of BLOCK_CYCLES consecutive cycles, block starts drawn uniformly with
    replacement, until the sample holds as many cycles as the span (blocks keep the within-cycle and
    cycle-to-cycle dependence);
  * the statistic is recomputed on every sample; sigma_real = sd over N_BOOT samples.

Used by derive_gate_thresholds.py: tolerance = 2 * sqrt(sigma_seed^2 + sigma_real^2), the same rule for
every sensor (omega p99) and every sensor pair (activity correlation, check 7a).
"""
import numpy as np

BLOCK_CYCLES = 10
N_BOOT = 200


def block_masks(t, t0, span_s, period_s, block_cycles=BLOCK_CYCLES, n_boot=N_BOOT, seed=0):
    """Yield n_boot index arrays into t (seconds, same clock as t0): moving-block resamples of the
    cycles in [t0, t0 + span_s). Repeated blocks repeat their samples."""
    n_cyc = int(span_s // period_s)
    cyc = np.floor((np.asarray(t) - t0) / period_s).astype(int)
    by_cycle = [np.where(cyc == c)[0] for c in range(n_cyc)]
    n_blocks = int(np.ceil(n_cyc / block_cycles))
    rng = np.random.default_rng(seed)
    for _ in range(n_boot):
        starts = rng.integers(0, n_cyc - block_cycles + 1, n_blocks)
        cycles = np.concatenate([np.arange(s, s + block_cycles) for s in starts])[:n_cyc]
        yield np.concatenate([by_cycle[c] for c in cycles])


def omega_with_time(d, elapsed_seconds, quat_cols, reconstruct_quat):
    """(t_mid, omega deg/s) over the same steps as validate_physics.omega_series()['all']."""
    qx, qy, qz, qw = quat_cols(d)
    q, _, _ = reconstruct_quat(qx, qy, qz, qw)
    t = elapsed_seconds(d)
    dt = np.diff(t)
    med = np.median(dt[np.isfinite(dt) & (dt > 0)])
    good = np.isfinite(dt) & (dt > 0) & (dt <= 2 * med)
    qn = q.copy()
    flip = np.where(np.sum(qn[1:] * qn[:-1], axis=1) < 0)[0] + 1
    qn[flip] *= -1
    cd = np.clip(np.sum(qn[1:] * qn[:-1], axis=1), -1, 1)
    om = np.degrees(2 * np.arccos(cd)) / np.where(dt > 0, dt, np.nan)
    keep = good & np.isfinite(om)
    return (0.5 * (t[1:] + t[:-1]))[keep], om[keep]


def sd_boot(values):
    return float(np.std(values, ddof=1))
