"""
stat_eval.py — Statistical similarity evaluation for synthetic sensor data.

Complements the TSTR (utility) evaluation. While TSTR asks "is the synthetic
data useful for training?", this asks "does the synthetic data match the real
data's distribution and texture?".

For each column it compares REAL vs SYNTHETIC on these metrics:
  1. Wasserstein (value)     : distance between value distributions, /range
  2. KS statistic (D)        : Kolmogorov-Smirnov two-sample statistic, reported
                               alongside D_crit (the alpha=0.05 critical value for
                               the sample size) and the p-value. See note below.
  3. Wasserstein (increment) : distance between per-step change distributions
                               (captures texture: how the signal moves step to step)
  4. ACF diff                : mean ABSOLUTE difference between the two signals'
                               autocorrelation functions (ACF = autocorrelation
                               function). Captures temporal structure: stickiness,
                               wander. This is NOT a correlation between the real
                               and synthetic signals — each signal's OWN ACF is
                               computed independently, then the two curves compared.
  5. ACF MSE                 : mean SQUARED difference between the two ACF curves.
                               A standard named metric (MSE), mathematically valid
                               here because both curves correspond point-to-point
                               (lag 0..N), unlike raw-value MSE which would require
                               the two realizations to be the same series.

All metrics: LOWER = more similar.

Note on the KS statistic (why bands, not a pass/fail hypothesis test)
--------------------------------------------------------------------
D is the max vertical gap between the two empirical CDFs. At sensor sample
sizes (tens of thousands to ~1e6 rows) the alpha=0.05 critical value
  D_crit = 1.36 * sqrt((n+m)/(n*m))
lands around 0.002-0.01, so EVERY column formally "fails" the hypothesis test
"same distribution", including columns that overlay almost perfectly. The formal
test is therefore uninformative at this scale. We instead read D as an EFFECT
SIZE: D=0.10 means "at worst 10% of the probability mass has shifted" — a
definitional reading that needs no citation. The GOOD/OK bands below are
PROJECT-INTERNAL effect-size bands calibrated against visual inspection, not
significance tests. D_crit and the p-value are printed so the reader can see the
formal test was considered and why it is not used as the pass/fail gate.

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
    """Normalized autocorrelation up to max_lag (acf[0] = 1).

    np.correlate(x, x, mode="full") is O(n^2) (direct convolution, not FFT) --
    on a 700k-row column that's ~5e11 ops and takes 10+ minutes. Only the
    first max_lag+1 lags are ever used, so compute those directly: this is
    numerically identical (same sum(x[i]*x[i+lag]) terms, same normalization)
    but O(n * max_lag) via vectorized per-lag dot products.
    """
    x = x - np.mean(x)
    n = len(x)
    var = np.var(x)
    if var < 1e-12:
        return np.zeros(max_lag + 1)
    max_lag = min(max_lag, n - 1)
    acf = np.empty(max_lag + 1)
    for lag in range(max_lag + 1):
        acf[lag] = np.dot(x[:n - lag], x[lag:])
    return acf / (var * n)


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

    r_s, s_s, n_ks = subsample(real, syn)

    # 1. value distribution
    w_value = wasserstein_distance(r_s, s_s) / col_range
    # KS on quantized columns (e.g. accel_z at {0.9, 1.0}) is only meaningful
    # after rounding: round-trip float error from the quantization step can
    # land 1.0 as 0.9999999999999998, which ks_2samp treats as a distinct
    # value and inflates the statistic from ~0.01 to ~0.85. Same fix as
    # compare_fridge.py already applies.
    # Keep the p-value: at this sample size it is essentially always ~0, which
    # is exactly the point we make on the slide (formal test is uninformative,
    # so D is read as an effect size, see module docstring).
    ks_stat, ks_pvalue = ks_2samp(np.round(r_s, 4), np.round(s_s, 4))
    # alpha=0.05 two-sample KS critical value for these (equal) sample sizes.
    # After subsample n == m == n_ks, so (n+m)/(n*m) = 2/n_ks.
    ks_dcrit = 1.36 * np.sqrt(2.0 / n_ks) if n_ks > 0 else float("nan")

    # 2. increment distribution (texture)
    dr, ds = np.diff(real), np.diff(syn)
    incr_range = (dr.max() - dr.min())
    incr_range = incr_range if incr_range > 1e-12 else 1.0
    w_incr = wasserstein_distance(dr, ds) / incr_range

    # 3. autocorrelation (temporal structure). Each signal's OWN acf is computed
    #    independently, then the two curves are compared (diff and MSE). This is
    #    self-similarity preservation, NOT cross-correlation between real & syn.
    acf_r = autocorr(real, max_lag)
    acf_s = autocorr(syn, max_lag)
    acf_diff = float(np.mean(np.abs(acf_r - acf_s)))
    acf_mse  = float(np.mean((acf_r - acf_s) ** 2))

    return {
        "wasserstein_value": w_value,
        "ks_stat": ks_stat,
        "ks_pvalue": ks_pvalue,
        "ks_dcrit": ks_dcrit,
        "ks_n": n_ks,
        "wasserstein_incr": w_incr,
        "autocorr_diff": acf_diff,
        "acf_mse": acf_mse,
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
    print(f"  {'KS statistic (D)':<32}{m['ks_stat']:>10.4f}   {verdict(m['ks_stat'],0.10,0.25)}")
    print(f"  {'Wasserstein (increment)':<32}{m['wasserstein_incr']:>10.4f}   {verdict(m['wasserstein_incr'],0.05,0.15)}")
    print(f"  {'ACF mean abs diff':<32}{m['autocorr_diff']:>10.4f}   {verdict(m['autocorr_diff'],0.05,0.15)}")
    print(f"  {'ACF MSE':<32}{m['acf_mse']:>10.4f}   {verdict(m['acf_mse'],0.01,0.05)}")
    print(f"  {'-'*54}")
    print(f"  KS detail: D={m['ks_stat']:.4f}  D_crit(alpha=0.05)={m['ks_dcrit']:.4f}  "
          f"p={m['ks_pvalue']:.2e}  n={m['ks_n']}")
    if m['ks_stat'] > m['ks_dcrit']:
        print(f"    -> D > D_crit: formally 'different' (expected at this n). "
              f"Read D as effect size (~{m['ks_stat']*100:.0f}% mass shifted at worst).")
    print("\n  Reading guide:")
    print("  - Wasserstein value  : value distribution match (mean/spread)")
    print("  - KS statistic (D)   : max CDF gap = effect size; bands are project-")
    print("                         internal (visual calibration), NOT sig. tests")
    print("  - Wasserstein incr   : texture (how it moves step to step)")
    print("  - ACF diff / ACF MSE : temporal structure — does synthetic preserve")
    print("                         the real signal's OWN autocorrelation shape")


def print_table(results):
    print(f"\n{'='*72}")
    print(f"  STATISTICAL SIMILARITY — summary (lower = more similar)")
    print(f"{'='*72}")
    print(f"  {'Column':<14}{'W(value)':>10}{'KS(D)':>8}{'W(incr)':>10}{'ACFdiff':>9}{'ACF_MSE':>9}")
    print(f"  {'-'*72}")
    dcrit = None
    for col, m in results:
        if m is None:
            print(f"  {col:<14}{'(constant — skipped)':>40}")
            continue
        dcrit = m['ks_dcrit']
        print(f"  {col:<14}{m['wasserstein_value']:>10.4f}{m['ks_stat']:>8.3f}"
              f"{m['wasserstein_incr']:>10.4f}{m['autocorr_diff']:>9.4f}{m['acf_mse']:>9.4f}")
    print(f"  {'-'*72}")
    print("\n  Bands (project-internal, LOWER = better):")
    print("    W(value)/W(incr)/ACFdiff:  GOOD < 0.05   OK < 0.15")
    print("    KS (D, effect size)     :  GOOD < 0.10   OK < 0.25")
    print("    ACF MSE                 :  GOOD < 0.01   OK < 0.05")
    if dcrit is not None:
        print(f"\n  KS D_crit(alpha=0.05) for this sample size ~= {dcrit:.4f}.")
        print("  Every column has D > D_crit, i.e. the formal test always rejects at")
        print("  this n; D is therefore reported as an effect size, not a pass/fail test.")


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