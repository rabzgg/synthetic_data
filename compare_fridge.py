"""
compare_fridge.py — bandingkan output synthetic fridge terhadap data real XDK.

Membandingkan output synthetic:
  1. fridge_01_normal.csv  (autofit dari data full, gated logging)
  2. fridge_25pct.csv      (autofit dari slice 25% pertama)
terhadap data real xdk_near_compressor_14112025_mvp_raw.csv.
File lain bisa ditambahkan via --syn label=path.csv.

Output:
  - tabel statistik ke stdout + results_fridge_threeway_stats.csv
  - plot results_fridge_threeway.png

Usage:
  python3 compare_fridge.py
  python3 compare_fridge.py --real path.csv --syn label=path.csv --syn label2=path2.csv
"""

import argparse
import os

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import ks_2samp, wasserstein_distance

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

DEFAULT_REAL = os.path.join(DATA, "fridge/xdk_near_compressor_14112025_mvp_raw.csv")
DEFAULT_SYN = [
    ("fit full",  os.path.join(HERE, "out/fridge/fridge_01_normal.csv")),
    ("fit 25pct", os.path.join(HERE, "out/fridge/fridge_25pct.csv")),
]

GAP_S = 60.0          # timestamp gap dianggap logging berhenti (kompresor OFF)
RMS_WINDOW_S = 30.0   # window rolling std buat deteksi ON/OFF
ON_THRESHOLD = None   # None = pakai Otsu dari data real, dipakai ke semua dataset

COLORS = {"real": "steelblue", 0: "darkorange", 1: "seagreen", 2: "mediumpurple"}


def parse_args():
    p = argparse.ArgumentParser(description="Bandingkan synthetic fridge vs real.")
    p.add_argument("--real", default=DEFAULT_REAL)
    p.add_argument("--syn", action="append", default=None,
                   help="label=path.csv (bisa berkali-kali; default: 3 output fridge)")
    p.add_argument("--out-prefix", default=os.path.join(HERE, "results_fridge_threeway"))
    return p.parse_args()


def load(path):
    df = pd.read_csv(path)
    t = (df["timestamp"].values - df["timestamp"].values[0]) / 1000.0  # detik
    return df, t


def otsu_threshold(values):
    """Threshold Otsu sederhana (sama seperti AutoFitter._detect_rhythm_on_column)."""
    v = np.sort(values[~np.isnan(values)])
    best_t, best_var = 0.0, float("inf")
    for pct in range(10, 90, 2):
        thr = np.percentile(v, pct)
        low, high = v[v <= thr], v[v > thr]
        if len(low) < 10 or len(high) < 10:
            continue
        var = len(low) / len(v) * np.var(low) + len(high) / len(v) * np.var(high)
        if var < best_var:
            best_var, best_t = var, thr
    return best_t


def rolling_rms(df, t):
    """Rolling std acceleration_z, window ~30s berdasarkan sampling rate file ini."""
    dt_med = np.median(np.diff(t))
    win = max(10, int(RMS_WINDOW_S / dt_med))
    return df["acceleration_z"].rolling(win, center=True).std().values


def duty_cycle_stats(t, activity, threshold):
    """
    Ukur duty cycle di waktu wall-clock: gap logging > GAP_S dihitung OFF.
    Return (on_fraction, on_blocks_min, off_blocks_min).
    """
    labels = np.where(np.isnan(activity), None,
                      np.where(activity > threshold, "on", "off"))
    segments = []  # (label, t_start, t_end)
    cur, start, prev_t = None, None, None
    for lab, ti in zip(labels, t):
        if prev_t is not None and (ti - prev_t) > GAP_S:
            if cur is not None:
                segments.append((cur, start, prev_t))
            segments.append(("off", prev_t, ti))  # gap = OFF
            cur = None
        if lab != cur:
            if cur is not None:
                segments.append((cur, start, ti))
            cur, start = lab, ti
        prev_t = ti
    if cur is not None:
        segments.append((cur, start, prev_t))

    merged = []
    for seg in segments:
        if seg[0] is None:
            continue
        if merged and merged[-1][0] == seg[0]:
            merged[-1][2] = seg[2]
        else:
            merged.append(list(seg))

    on_blocks = [(e - s) / 60 for lab, s, e in merged if lab == "on" and (e - s) > 30]
    off_blocks = [(e - s) / 60 for lab, s, e in merged if lab == "off" and (e - s) > 30]
    total = t[-1] - t[0]
    on_total = sum((e - s) for lab, s, e in merged if lab == "on")
    return on_total / total, on_blocks, off_blocks


def dataset_stats(name, df, t, threshold):
    dt = np.diff(t)
    gap_total = dt[dt > GAP_S].sum()
    duration_h = (t[-1] - t[0]) / 3600
    act = rolling_rms(df, t)
    on_frac, on_blocks, off_blocks = duty_cycle_stats(t, act, threshold)
    return {
        "dataset": name,
        "rows": len(df),
        "durasi_jam": round(duration_h, 2),
        "baris_per_jam": int(len(df) / duration_h),
        "gap_fraction": round(gap_total / (t[-1] - t[0]), 3),
        "on_fraction": round(on_frac, 3),
        "on_block_mean_min": round(np.mean(on_blocks), 1) if on_blocks else np.nan,
        "off_block_mean_min": round(np.mean(off_blocks), 1) if off_blocks else np.nan,
        "n_on_blocks": len(on_blocks),
        "accel_z_mean": round(float(np.nanmean(df["acceleration_z"])), 4),
        "accel_z_std": round(float(np.nanstd(df["acceleration_z"])), 4),
        "rolling_std_mean": round(float(np.nanmean(df["rolling_std"])), 4),
        "rolling_std_std": round(float(np.nanstd(df["rolling_std"])), 4),
    }, act


def distribution_metrics(real_df, syn_df, cols=("acceleration_z", "rolling_std")):
    out = {}
    for col in cols:
        # Bulatkan dulu: kolom terkuantisasi (accel = kelipatan 0.1) bisa beda
        # di floating point (0.9 vs 0.9000000000000001) dan bikin KS meledak
        # padahal distribusinya sama.
        a = real_df[col].dropna().round(4).values
        b = syn_df[col].dropna().round(4).values
        ks = ks_2samp(a, b)
        out[f"{col}_KS"] = round(float(ks.statistic), 3)
        out[f"{col}_wasserstein"] = round(float(wasserstein_distance(a, b)), 5)
    return out


def main():
    args = parse_args()
    syn_specs = DEFAULT_SYN if args.syn is None else [
        (s.split("=", 1)[0], s.split("=", 1)[1]) for s in args.syn
    ]
    missing = [(l, pth) for l, pth in syn_specs if not os.path.exists(pth)]
    syn_specs = [(l, pth) for l, pth in syn_specs if os.path.exists(pth)]
    for label, pth in missing:
        print(f"[skip] '{label}': belum ada ({pth}) — jalankan run script-nya dulu")
    if not syn_specs:
        print("Tidak ada file synthetic untuk dibandingkan.")
        return

    real_df, real_t = load(args.real)
    real_act = rolling_rms(real_df, real_t)
    threshold = ON_THRESHOLD or otsu_threshold(real_act[~np.isnan(real_act)])
    print(f"Real      : {args.real}")
    print(f"Threshold ON/OFF (Otsu dari real): {threshold:.4f}\n")

    rows = []
    real_stats, _ = dataset_stats("REAL", real_df, real_t, threshold)
    rows.append(real_stats)

    syn_data = []
    for label, path in syn_specs:
        df, t = load(path)
        st, act = dataset_stats(label, df, t, threshold)
        st.update(distribution_metrics(real_df, df))
        rows.append(st)
        syn_data.append((label, df, t, act))

    stats = pd.DataFrame(rows).set_index("dataset")
    pd.set_option("display.width", 200)
    print(stats.T.to_string())
    stats.to_csv(args.out_prefix + "_stats.csv")
    print(f"\nSaved stats : {args.out_prefix}_stats.csv")

    # ── Plot ──────────────────────────────────────────────────────────────
    n_syn = len(syn_data)
    fig = plt.figure(figsize=(15, 4 + 2.6 * (1 + n_syn)))
    gs = fig.add_gridspec(1 + n_syn + 1, 3, height_ratios=[1] * (1 + n_syn) + [1.4],
                          hspace=0.55, wspace=0.3)

    # Baris 1..N: time series RMS (real dulu, lalu tiap synthetic)
    ax = fig.add_subplot(gs[0, :])
    ax.plot(real_t / 60, real_act, lw=0.4, color=COLORS["real"])
    ax.axhline(threshold, color="gray", ls="--", lw=0.7)
    ax.set_title("REAL — rolling std acceleration_z (30s)")
    ax.set_ylim(0, 0.07); ax.grid(alpha=0.3)

    for i, (label, df, t, act) in enumerate(syn_data):
        ax = fig.add_subplot(gs[1 + i, :])
        ax.plot(t / 60, act, lw=0.4, color=COLORS[i])
        ax.axhline(threshold, color="gray", ls="--", lw=0.7)
        ax.set_title(f"{label} — rolling std acceleration_z (30s)")
        ax.set_ylim(0, 0.07); ax.grid(alpha=0.3)
    ax.set_xlabel("Waktu (menit)")

    # Baris terakhir: distribusi
    ax_h1 = fig.add_subplot(gs[-1, 0])
    ax_h2 = fig.add_subplot(gs[-1, 1])
    ax_h3 = fig.add_subplot(gs[-1, 2])

    bins_rs = np.linspace(0, 0.07, 60)
    ax_h1.hist(real_df["rolling_std"].dropna(), bins=bins_rs, density=True,
               histtype="step", lw=1.5, color=COLORS["real"], label="REAL")
    levels = np.array([0.8, 0.9, 1.0, 1.1])
    n_bars = 1 + len(syn_data)
    width = 0.08 / n_bars
    def level_fracs(vals):
        return [np.mean(np.isclose(vals, lv, atol=0.05)) for lv in levels]
    ax_h2.bar(levels - (n_bars - 1) / 2 * width, level_fracs(real_df["acceleration_z"].values),
              width=width, color=COLORS["real"], label="REAL")
    ax_h3.hist(real_act[~np.isnan(real_act)], bins=bins_rs, density=True,
               histtype="step", lw=1.5, color=COLORS["real"], label="REAL")

    for i, (label, df, t, act) in enumerate(syn_data):
        ax_h1.hist(df["rolling_std"].dropna(), bins=bins_rs, density=True,
                   histtype="step", lw=1.2, color=COLORS[i], label=label)
        ax_h2.bar(levels + (i + 1 - (n_bars - 1) / 2) * width,
                  level_fracs(df["acceleration_z"].values),
                  width=width, color=COLORS[i], label=label)
        ax_h3.hist(act[~np.isnan(act)], bins=bins_rs, density=True,
                   histtype="step", lw=1.2, color=COLORS[i], label=label)

    ax_h1.set_title("Distribusi kolom rolling_std"); ax_h1.legend(fontsize=7)
    ax_h2.set_title("Proporsi level acceleration_z"); ax_h2.legend(fontsize=7)
    ax_h2.set_xticks([0.8, 0.9, 1.0, 1.1])
    ax_h3.set_title("Distribusi rolling RMS 30s"); ax_h3.legend(fontsize=7)
    for a in (ax_h1, ax_h2, ax_h3):
        a.grid(alpha=0.3)

    out_png = args.out_prefix + ".png"
    fig.savefig(out_png, dpi=90, bbox_inches="tight")
    print(f"Saved plot  : {out_png}")


if __name__ == "__main__":
    main()
