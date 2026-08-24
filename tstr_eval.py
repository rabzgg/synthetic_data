"""
tstr_eval.py — Train-on-Synthetic, Test-on-Real (TSTR) evaluation.

Compares three forecasting strategies on a single sensor column:
  TRTR   : Train on first --train-ratio of real data, test on rest of real
  TSTR   : Train on first --train-ratio of synthetic, test on rest of real
  Naive  : Predict last known value (persistence model)

Usage
-----
python3 tstr_eval.py \
    --real  out/robot_arm/sensor_1_1hour.csv \
    --syn   out/robot_arm/xdk_joint1_syn.csv \
    --col   temperature

Optional flags
--------------
--train-ratio   fraction of data used for training   (default: 0.1)
--window        lag feature window in timesteps       (default: 50)
--detrend       remove rolling-mean trend before forecasting (recommended for drifting signals)
--detrend-window  rolling window size in timesteps for detrend (default: auto = n//20)
--plot          save a comparison plot to FILE
--no-scale      skip StandardScaler (faster, less accurate for RF)
"""

import argparse
import sys
import os
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_squared_error, mean_absolute_error


# ── Helpers ──────────────────────────────────────────────────────────────────

def load_series(path: str, col: str) -> np.ndarray:
    df = pd.read_csv(path)
    if col not in df.columns:
        print(f"Error: column '{col}' not in {path}")
        print(f"  Available: {list(df.columns)}")
        sys.exit(1)
    return df[col].values.astype(float)


def make_lag_features(series: np.ndarray, window: int):
    """Return (X, y) where X[i] = series[i:i+window], y[i] = series[i+window]."""
    n = len(series) - window
    X = np.lib.stride_tricks.sliding_window_view(series[:-1], window)
    y = series[window:]
    return X[:n], y[:n]


def rmse(y_true, y_pred):
    return np.sqrt(mean_squared_error(y_true, y_pred))


def mae(y_true, y_pred):
    return mean_absolute_error(y_true, y_pred)


def relative_to_naive(score, naive_score):
    """Score relative to naive (1.0 = same as naive, <1 = better, >1 = worse)."""
    if naive_score == 0:
        return float("nan")
    return score / naive_score


def rolling_mean_detrend(series: np.ndarray, window: int):
    """Remove rolling-mean trend from the full series. Returns (residuals, trend).

    Uses centered window on the full series so trend is accurate everywhere —
    no extrapolation, no edge distortion from a short training slice.
    """
    trend = pd.Series(series).rolling(window=window, center=True, min_periods=1).mean().values
    return series - trend, trend


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="TSTR evaluation for synthetic sensor data.")
    parser.add_argument("--real",        required=True,             help="Path to real data CSV")
    parser.add_argument("--syn",         required=True,             help="Path to synthetic data CSV")
    parser.add_argument("--col",         default="temperature",     help="Column to evaluate (default: temperature)")
    parser.add_argument("--train-ratio", type=float, default=0.1,   help="Fraction used for training (default: 0.1)")
    parser.add_argument("--window",      type=int,   default=50,    help="Lag window in timesteps (default: 50)")
    parser.add_argument("--detrend",        action="store_true",     help="Remove rolling-mean trend before forecasting")
    parser.add_argument("--detrend-window", type=int, default=None, help="Rolling window for detrend (default: auto = n//20)")
    parser.add_argument("--plot",           default=None,           help="Save plot to this file path")
    parser.add_argument("--no-scale",    action="store_true",       help="Skip StandardScaler")
    args = parser.parse_args()

    if not os.path.exists(args.real):
        print(f"Error: real CSV not found: {args.real}")
        sys.exit(1)
    if not os.path.exists(args.syn):
        print(f"Error: synthetic CSV not found: {args.syn}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  TSTR Evaluation — column: {args.col}")
    print(f"  real      : {args.real}")
    print(f"  synthetic : {args.syn}")
    print(f"  train ratio: {args.train_ratio:.0%}   window: {args.window}   detrend: {args.detrend}")
    print(f"{'='*60}")

    # ── Load data ─────────────────────────────────────────────────────────────
    real_series = load_series(args.real, args.col)
    syn_series  = load_series(args.syn,  args.col)

    n_real  = len(real_series)
    n_train = max(args.window + 1, int(n_real * args.train_ratio))
    n_test  = n_real - n_train

    print(f"\n  Real rows   : {n_real}  (train={n_train}, test={n_test})")
    print(f"  Synth rows  : {len(syn_series)}")

    if n_test < args.window + 1:
        print(f"\nError: test set too small ({n_test} rows < window {args.window}). "
              "Lower --train-ratio or --window.")
        sys.exit(1)

    # ── Split ─────────────────────────────────────────────────────────────────
    real_train = real_series[:n_train]
    syn_train  = syn_series[:n_train] if len(syn_series) >= n_train else syn_series

    if len(syn_train) < args.window + 1:
        print(f"Error: synthetic training set too small ({len(syn_train)} rows). "
              "Either generate more synthetic data or lower --window.")
        sys.exit(1)

    # ── Detrend (optional) ────────────────────────────────────────────────────
    # Apply rolling-mean detrend to the FULL series before slicing, so the
    # trend is computed with global context — no extrapolation from a short slice.
    if args.detrend:
        rw = args.detrend_window if args.detrend_window else max(100, n_real // 20)
        real_residuals, _ = rolling_mean_detrend(real_series, rw)
        syn_residuals,  _ = rolling_mean_detrend(syn_series,  rw)

        real_train        = real_residuals[:n_train]
        full_test_context = real_residuals[n_train - args.window:]
        syn_train         = syn_residuals[:n_train] if len(syn_residuals) >= n_train else syn_residuals

        print(f"\n  Detrend: rolling-mean window={rw} (~{rw/n_real*100:.1f}% of real data)")
        print(f"  (RMSE below is on residuals after trend removal)")
    else:
        full_test_context = real_series[n_train - args.window:]

    # ── Lag features ──────────────────────────────────────────────────────────
    X_test, y_test = make_lag_features(full_test_context, args.window)

    X_real_train, y_real_train = make_lag_features(real_train, args.window)
    X_syn_train,  y_syn_train  = make_lag_features(syn_train,  args.window)

    print(f"\n  Train samples: real={len(X_real_train)}, synth={len(X_syn_train)}")
    print(f"  Test  samples: {len(X_test)}")

    # ── Scale ─────────────────────────────────────────────────────────────────
    if not args.no_scale:
        # Fit scaler on real training distribution
        scaler_X = StandardScaler().fit(X_real_train)
        scaler_y = StandardScaler().fit(y_real_train.reshape(-1, 1))

        X_real_train_s = scaler_X.transform(X_real_train)
        y_real_train_s = scaler_y.transform(y_real_train.reshape(-1, 1)).ravel()

        X_syn_train_s  = scaler_X.transform(X_syn_train)
        y_syn_train_s  = scaler_y.transform(y_syn_train.reshape(-1, 1)).ravel()

        X_test_s = scaler_X.transform(X_test)

        def predict(model, X_s):
            return scaler_y.inverse_transform(model.predict(X_s).reshape(-1, 1)).ravel()
    else:
        X_real_train_s, y_real_train_s = X_real_train, y_real_train
        X_syn_train_s,  y_syn_train_s  = X_syn_train,  y_syn_train
        X_test_s = X_test

        def predict(model, X_s):
            return model.predict(X_s)

    # ── Train models ──────────────────────────────────────────────────────────
    rf_params = dict(n_estimators=100, n_jobs=-1, random_state=42)

    print("\n  Training TRTR model (real) ...", end=" ", flush=True)
    model_real = RandomForestRegressor(**rf_params)
    model_real.fit(X_real_train_s, y_real_train_s)
    print("done")

    print("  Training TSTR model (synthetic) ...", end=" ", flush=True)
    model_syn = RandomForestRegressor(**rf_params)
    model_syn.fit(X_syn_train_s, y_syn_train_s)
    print("done")

    # ── Predict ───────────────────────────────────────────────────────────────
    pred_real  = predict(model_real, X_test_s)
    pred_syn   = predict(model_syn,  X_test_s)
    pred_naive = full_test_context[:len(y_test)]   # lag-1 (last known value)

    # ── Metrics ───────────────────────────────────────────────────────────────
    rmse_real  = rmse(y_test, pred_real)
    rmse_syn   = rmse(y_test, pred_syn)
    rmse_naive = rmse(y_test, pred_naive)

    mae_real   = mae(y_test, pred_real)
    mae_syn    = mae(y_test, pred_syn)
    mae_naive  = mae(y_test, pred_naive)

    # NRMSE normalised by the range of whatever series was actually modelled
    norm_range = (y_test.max() - y_test.min()) if args.detrend else (real_series.max() - real_series.min())
    nrmse_real  = rmse_real  / norm_range if norm_range else float("nan")
    nrmse_syn   = rmse_syn   / norm_range if norm_range else float("nan")
    nrmse_naive = rmse_naive / norm_range if norm_range else float("nan")

    rel_real  = relative_to_naive(rmse_real,  rmse_naive)
    rel_syn   = relative_to_naive(rmse_syn,   rmse_naive)

    residual_note = " (on detrended residuals)" if args.detrend else ""
    print(f"\n{'─'*60}")
    print(f"  Results for column: {args.col}{residual_note}")
    print(f"  Value range: {real_series.min():.3g} – {real_series.max():.3g}")
    print(f"{'─'*60}")
    # Column name embedded in the table header so a screenshot of just the table
    # region is self-describing (the caption above can get cropped out).
    model_hdr = f"Model / col={args.col}"
    print(f"  {model_hdr:<22} {'RMSE':>10} {'NRMSE':>8} {'MAE':>10} {'vs Naive':>10}")
    print(f"  {'─'*22} {'─'*10} {'─'*8} {'─'*10} {'─'*10}")
    print(f"  {'TRTR (real)':<22} {rmse_real:>10.4f} {nrmse_real:>8.3%} {mae_real:>10.4f} {rel_real:>9.3f}x")
    print(f"  {'TSTR (synthetic)':<22} {rmse_syn:>10.4f} {nrmse_syn:>8.3%} {mae_syn:>10.4f} {rel_syn:>9.3f}x")
    print(f"  {'Naive (lag-1)':<22} {rmse_naive:>10.4f} {nrmse_naive:>8.3%} {mae_naive:>10.4f} {'(baseline)':>10}")
    print(f"{'─'*60}")

    # ratio < 1 → TSTR better than TRTR; > 1 → TSTR worse
    tstr_trtr_ratio = (rmse_syn / rmse_real) if rmse_real else float("nan")
    print(f"\n  TSTR/TRTR ratio : {tstr_trtr_ratio:.3f}  (< 1 = synthetic better, > 1 = worse)")

    beats_naive_real = rel_real < 1.0
    beats_naive_syn  = rel_syn  < 1.0
    syn_much_better  = tstr_trtr_ratio < 0.5
    syn_similar      = 0.5 <= tstr_trtr_ratio <= 2.0

    if beats_naive_real and beats_naive_syn:
        if syn_similar:
            quality = "TSTR ≈ TRTR, both beat naive — synthetic is a strong substitute for real"
        elif syn_much_better:
            quality = "TSTR beats both TRTR and naive — synthetic generalises better than the real slice"
        else:
            quality = "TRTR beats TSTR, both beat naive — synthetic partially useful but real is better"
    elif beats_naive_syn and not beats_naive_real:
        quality = "TSTR beats naive but TRTR doesn't — synthetic covers a wider distribution than the real training slice"
    elif beats_naive_real and not beats_naive_syn:
        quality = "TRTR beats naive but TSTR doesn't — synthetic training distribution is insufficient"
    else:
        # neither beats naive
        if syn_much_better:
            quality = (
                "neither beats naive (signal too slowly varying for lag model), "
                f"but TSTR is {1/tstr_trtr_ratio:.1f}x better than TRTR — "
                "synthetic generalises better than the real training slice"
            )
        elif syn_similar:
            quality = "neither beats naive — synthetic and real are equivalent; signal may be non-stationary or data too small"
        else:
            quality = f"neither beats naive — TSTR is {tstr_trtr_ratio:.1f}x worse than TRTR; synthetic distribution differs from real"
    print(f"  Verdict         : {quality}")

    # ── Plot ──────────────────────────────────────────────────────────────────
    if args.plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        n_show = min(500, len(y_test))
        t = np.arange(n_show)

        fig, axes = plt.subplots(3, 1, figsize=(14, 9), sharex=True)
        fig.suptitle(f"TSTR Evaluation — {args.col}  (first {n_show} test steps)", fontsize=13)

        for ax, pred, label, color in zip(
            axes,
            [pred_real, pred_syn, pred_naive],
            ["TRTR (real train)", "TSTR (synth train)", "Naive (lag-1)"],
            ["steelblue", "darkorange", "gray"],
        ):
            ax.plot(t, y_test[:n_show], color="black",  lw=0.8, label="actual (real)", alpha=0.7)
            ax.plot(t, pred[:n_show],   color=color,    lw=0.8, label=label, alpha=0.85)
            ax.legend(loc="upper right", fontsize=8)
            ax.set_ylabel(args.col)
            rmse_here = rmse(y_test[:n_show], pred[:n_show])
            ax.set_title(f"{label}  RMSE={rmse_here:.4f}", fontsize=9)
            ax.grid(True, alpha=0.3)

        axes[-1].set_xlabel("test step")
        plt.tight_layout()
        os.makedirs(os.path.dirname(args.plot) or ".", exist_ok=True)
        plt.savefig(args.plot, dpi=150)
        print(f"\n  Plot saved → {args.plot}")

    print()


if __name__ == "__main__":
    main()
