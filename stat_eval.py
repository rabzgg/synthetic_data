"""
stat_eval.py — Statistical similarity evaluation for synthetic sensor data.

Complements the TSTR (utility) evaluation. While TSTR asks "is the synthetic
data useful for training?", this asks "does the synthetic data match the real
data's distribution and texture?".

For each column it compares REAL vs SYNTHETIC on four metrics:
  1. Wasserstein (value)     : distance between value distributions, /range
  2. KS statistic            : Kolmogorov-Smirnov two-sample test
  3. Wasserstein (increment) : distance between per-step change distributions
                               (captures texture: how the signal moves step to step)
  4. Autocorr diff           : mean abs difference of autocorrelation functions
                               (captures temporal structure: stickiness, wander)

All metrics: LOWER = more similar.

Usage
-----
# single column
python3 stat_eval.py --real real.csv --syn syn.csv --col pressure

# several columns at once -> summary table
python3 stat_eval.py --real real.csv --syn syn.csv --cols pressure mag_res humidity

# with histogram + ACF overlay plot
python3 stat_eval.py --real real.csv --syn syn.csv --col pressure --plot pressure_sim.png
"""

import argparse
import os
import sys
import numpy as np
import pandas as pd
from scipy.stats import wasserstein_distance, ks_2samp


# ── Helpers ──────────────────────────────────────────────────────────────────

def load_series(path, col):
    df = pd.read_csv(path)
    if col not in df.columns:
        print(f"Error: column '{col}' not in {path}")
        print(f"  Available: {[c for c in df.columns if c != 'timestamp']}")
        sys.exit(1)
    return df[col].values.astype(float)


def autocorr(x, max_lag):
    """Normalized autocorrelation up to max_lag (acf[0] = 1)."""
    x = x - np.mean(x)
    var = np.var(x)
    if var < 1e-12:
        return np.zeros(max_lag + 1)
    acf = np.correlate(x, x, mode="full")[len(x) - 1:]
    return (acf / (var * len(x)))[:max_lag + 1]


def subsample(a, b, seed=42):
    """Match lengths by random subsampling the longer array (fair comparison)."""
    n = min(len(a), len(b))
    rng = np.random.default_rng(seed)
    a_s = a if len(a) == n else a[rng.choice(len(a), n, replace=False)]
    b_s = b if len(b) == n else b[rng.choice(len(b), n, replace=False)]
    return a_s, b_s, n


def verdict(value, good, ok):
    """Three-level verdict from a similarity metric (lower = better)."""
    if value < good:
        return "GOOD"
    if value < ok:
        return "OK"
    return "POOR"


def compute_metrics(real, syn, max_lag=300):
    """Return dict of the four similarity metrics for one column."""
    col_range = real.max() - real.min()
    if col_range < 1e-12:
        return None  # constant column, skip

    r_s, s_s, _ = subsample(real, syn)

    # 1. value distribution
    w_value = wasserstein_distance(r_s, s_s) / col_range
    ks_stat, _ = ks_2samp(r_s, s_s)

    # 2. increment distribution (texture)
    dr, ds = np.diff(real), np.diff(syn)
    incr_range = (dr.max() - dr.min())
    incr_range = incr_range if incr_range > 1e-12 else 1.0
    w_incr = wasserstein_distance(dr, ds) / incr_range

    # 3. autocorrelation (temporal structure)
    acf_r = autocorr(real, max_lag)
    acf_s = autocorr(syn, max_lag)
    acf_diff = float(np.mean(np.abs(acf_r - acf_s)))

    return {
        "wasserstein_value": w_value,
        "ks_stat": ks_stat,
        "wasserstein_incr": w_incr,
        "autocorr_diff": acf_diff,
        "real_mean": real.mean(), "syn_mean": syn.mean(),
        "real_std": real.std(),   "syn_std": syn.std(),
        "acf_r": acf_r, "acf_s": acf_s,
    }


# ── Output ───────────────────────────────────────────────────────────────────

def print_single(col, m):
    print(f"\n{'='*60}")
    print(f"  STATISTICAL SIMILARITY — {col}")
    print(f"{'='*60}")
    print(f"  real : mean={m['real_mean']:.4f}  std={m['real_std']:.4f}")
    print(f"  syn  : mean={m['syn_mean']:.4f}  std={m['syn_std']:.4f}")
    print(f"\n  {'Metric':<32}{'Value':>10}   Verdict")
    print(f"  {'-'*54}")
    print(f"  {'Wasserstein (value, /range)':<32}{m['wasserstein_value']:>10.4f}   {verdict(m['wasserstein_value'],0.05,0.15)}")
    print(f"  {'KS statistic':<32}{m['ks_stat']:>10.4f}   {verdict(m['ks_stat'],0.10,0.25)}")
    print(f"  {'Wasserstein (increment)':<32}{m['wasserstein_incr']:>10.4f}   {verdict(m['wasserstein_incr'],0.05,0.15)}")
    print(f"  {'Autocorr mean abs diff':<32}{m['autocorr_diff']:>10.4f}   {verdict(m['autocorr_diff'],0.05,0.15)}")
    print(f"  {'-'*54}")
    print("\n  Reading guide:")
    print("  - Wasserstein value  : value distribution match (mean/spread)")
    print("  - KS statistic       : overall distribution distinguishability")
    print("  - Wasserstein incr   : texture (how it moves step to step)")
    print("  - Autocorr diff      : temporal structure (stickiness, wander)")


def print_table(results):
    print(f"\n{'='*72}")
    print(f"  STATISTICAL SIMILARITY — summary (lower = more similar)")
    print(f"{'='*72}")
    print(f"  {'Column':<14}{'W(value)':>10}{'KS':>8}{'W(incr)':>10}{'ACF diff':>10}")
    print(f"  {'-'*70}")
    for col, m in results:
        if m is None:
            print(f"  {col:<14}{'(constant — skipped)':>40}")
            continue
        print(f"  {col:<14}{m['wasserstein_value']:>10.4f}{m['ks_stat']:>8.3f}"
              f"{m['wasserstein_incr']:>10.4f}{m['autocorr_diff']:>10.4f}")
    print(f"  {'-'*70}")
    print("\n  Thresholds:  GOOD < 0.05   OK < 0.15   (KS: GOOD<0.10 OK<0.25)")


def make_plot(col, real, syn, m, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    dr, ds = np.diff(real), np.diff(syn)
    fig, ax = plt.subplots(1, 3, figsize=(16, 4))
    ax[0].hist(real, bins=60, alpha=0.5, label="real", density=True)
    ax[0].hist(syn, bins=60, alpha=0.5, label="syn", density=True)
    ax[0].set_title(f"{col} — value distribution"); ax[0].legend(); ax[0].grid(alpha=0.3)
    ax[1].hist(dr, bins=60, alpha=0.5, label="real", density=True)
    ax[1].hist(ds, bins=60, alpha=0.5, label="syn", density=True)
    ax[1].set_title("increment distribution (texture)"); ax[1].legend(); ax[1].grid(alpha=0.3)
    ax[2].plot(m["acf_r"], label="real"); ax[2].plot(m["acf_s"], label="syn")
    ax[2].set_title("autocorrelation"); ax[2].set_xlabel("lag"); ax[2].legend(); ax[2].grid(alpha=0.3)
    plt.tight_layout()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    plt.savefig(path, dpi=120)
    print(f"\n  Plot -> {path}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Statistical similarity evaluation.")
    ap.add_argument("--real", required=True)
    ap.add_argument("--syn", required=True)
    ap.add_argument("--col", default=None, help="Single column")
    ap.add_argument("--cols", nargs="+", default=None, help="Multiple columns -> summary table")
    ap.add_argument("--max-lag", type=int, default=300, help="Max autocorrelation lag (default 300)")
    ap.add_argument("--plot", default=None, help="Save plot (single-column mode only)")
    args = ap.parse_args()

    if not args.col and not args.cols:
        print("Error: provide --col COLUMN or --cols COL1 COL2 ...")
        sys.exit(1)

    if args.cols:
        results = []
        for col in args.cols:
            real = load_series(args.real, col)
            syn = load_series(args.syn, col)
            results.append((col, compute_metrics(real, syn, args.max_lag)))
        print_table(results)
    else:
        real = load_series(args.real, args.col)
        syn = load_series(args.syn, args.col)
        m = compute_metrics(real, syn, args.max_lag)
        if m is None:
            print(f"\n[!] Column '{args.col}' is constant in real data (range ~0). Skipped.")
            return
        print_single(args.col, m)
        if args.plot:
            make_plot(args.col, real, syn, m, args.plot)
    print()


if __name__ == "__main__":
    main()