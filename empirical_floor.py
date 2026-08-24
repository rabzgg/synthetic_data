"""
empirical_floor.py — measure the "real vs real" empirical floor for the bands.

The GOOD/OK bands in stat_eval.py were originally set by visual calibration.
This grounds them in data instead: split the REAL recording in two and score the
two halves against each other. Two samples of the same process are the best any
synthetic data could ever do, so their metric values are the empirical floor.

Three splits, because it matters:
  --split random  : rows assigned to A/B at random. Both halves share the SAME
                    marginal distribution, so the score is pure finite-sample
                    noise ≈ D_crit. It confirms the SCALE of "identical"; it does
                    not independently justify a threshold (it IS D_crit measured).
  --split chrono  : first half vs second half. For a non-stationary recording
                    (fridge temperature warms up, pressure drifts) this compares
                    "cold start" vs "warmed up" and is dominated by the trend,
                    NOT the noise floor — so it is a ceiling/《caveat》, not a floor.
  --split block   : interleaved contiguous blocks (odd vs even N-minute blocks).
                    Both sides cover the SAME time range (trend cancels) BUT the
                    temporal structure inside each block is kept (unlike random,
                    which destroys ordering). This is the REALISTIC target: how
                    close is the real process to itself under a fair comparison.

Usage:
  python3 empirical_floor.py --csv ppt/fridge/fridge_xdk1_real.csv \
      --cols temperature light humidity pressure acceleration_z rolling_std \
      --split block --block-min 10
"""
import argparse
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stat_eval import compute_metrics


def load(path):
    d = pd.read_csv(path)
    d.columns = [str(c).strip().strip('"') for c in d.columns]
    return d


def _elapsed_minutes(df):
    """Elapsed time in minutes from the first timestamp (ms or s auto-detected)."""
    tcol = "timestamp" if "timestamp" in df.columns else df.columns[0]
    ts = pd.to_numeric(df[tcol], errors="coerce").to_numpy(float)
    dt = np.median(np.diff(ts[np.isfinite(ts)]))
    div = 60000.0 if dt >= 10 else 60.0        # ms->min or s->min
    return (ts - ts[0]) / div


def split(df, how, seed, block_min=10.0):
    n = len(df)
    if how == "chrono":
        h = n // 2
        return df.iloc[:h], df.iloc[h:]
    if how == "block":
        # Odd vs even contiguous blocks of `block_min` minutes: both sides span
        # the whole recording (trend cancels) but keep within-block ordering.
        mins = _elapsed_minutes(df)
        blk = np.floor(mins / block_min).astype(int)
        m = (blk % 2 == 0)
        return df[m], df[~m]
    rng = np.random.default_rng(seed)
    m = rng.random(n) < 0.5
    return df[m], df[~m]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True, help="Real recording CSV")
    ap.add_argument("--cols", nargs="+", required=True)
    ap.add_argument("--split", choices=["random", "chrono", "block", "all"], default="all")
    ap.add_argument("--block-min", type=float, default=10.0, help="Block length in minutes (default 10)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    df = load(args.csv)
    modes = ["random", "block", "chrono"] if args.split == "all" else [args.split]

    tags = {
        "random": "RANDOM row split (same distribution -> ~D_crit, sets the SCALE of 'identical')",
        "block":  f"BLOCK split (odd vs even {args.block_min:.0f}-min blocks -> REALISTIC self-similarity target)",
        "chrono": "CHRONO split (1st vs 2nd half -> trend-dominated, a CEILING/caveat)",
    }
    for how in modes:
        A, B = split(df, how, args.seed, args.block_min)
        tag = tags[how]
        print(f"\n{'='*74}\n  {tag}\n  {os.path.basename(args.csv)}   A={len(A)} rows  B={len(B)} rows\n{'='*74}")
        print(f"  {'Column':<15}{'W(value)':>10}{'KS(D)':>8}{'W(incr)':>10}{'ACFdiff':>9}{'ACF_MSE':>9}")
        print(f"  {'-'*66}")
        for col in args.cols:
            if col not in df.columns:
                print(f"  {col:<15}(not found)")
                continue
            a = pd.to_numeric(A[col], errors="coerce").dropna().to_numpy(float)
            b = pd.to_numeric(B[col], errors="coerce").dropna().to_numpy(float)
            m = compute_metrics(a, b)
            if m is None:
                print(f"  {col:<15}{'(constant — skipped)':>40}")
                continue
            print(f"  {col:<15}{m['wasserstein_value']:>10.4f}{m['ks_stat']:>8.3f}"
                  f"{m['wasserstein_incr']:>10.4f}{m['autocorr_diff']:>9.4f}{m['acf_mse']:>9.4f}")
        print(f"  {'-'*66}")


if __name__ == "__main__":
    main()
