"""
fridge_inspect.py — inspect dan visualisasi data fridge XDK.

Usage:
  python3 fridge_inspect.py --csv path/to/fridge.csv
"""

import argparse
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ACCEL_COLS   = ["acceleration_x", "acceleration_y", "acceleration_z"]
ROLLING_SEC  = 30    # window RMS rolling (detik)
TAIL_MINUTES = 30    # zoom ke N menit terakhir


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", required=True)
    p.add_argument("--tail", type=int, default=60, help="Zoom N menit terakhir (default: 60)")
    p.add_argument("--zoom-start", type=int, default=None, help="Zoom dari menit ke-N")
    p.add_argument("--zoom-end", type=int, default=None, help="Zoom sampai menit ke-N")
    return p.parse_args()


def load_csv(path):
    print(f"\n[1] Loading {path} ...")
    df = pd.read_csv(path)
    print(f"    Rows    : {len(df):,}")
    print(f"    Columns : {list(df.columns)}")
    return df


def parse_timestamps(df):
    ts_candidates = [c for c in df.columns if "time" in c.lower() or c.lower() == "ts"]
    if not ts_candidates:
        print("\n[2] Tidak ada kolom timestamp, pakai index")
        df["t_sec"] = df.index / 10.0
        return df

    col = ts_candidates[0]
    raw = df[col]

    # Deteksi unit timestamp dari magnitude nilainya
    median_val = raw.median()
    if median_val > 1e15:
        unit = "ns"
        divisor = 1e9
    elif median_val > 1e12:
        unit = "ms"
        divisor = 1e3
    elif median_val > 1e9:
        unit = "s (unix)"
        divisor = 1
    else:
        # Kemungkinan microseconds tapi epoch lokal (kayak data lo)
        unit = "ms (relative)"
        divisor = 1e3

    print(f"\n[2] Timestamp column: '{col}' (detected unit: {unit})")

    # Hitung t_sec sebagai detik dari awal recording
    df["t_sec"] = (raw - raw.iloc[0]) / divisor

    duration = df["t_sec"].iloc[-1]
    print(f"    Rows        : {len(df):,}")
    print(f"    Duration    : {duration:.1f} s  =  {duration/60:.1f} min  =  {duration/3600:.2f} h")
    print(f"    t_sec range : {df['t_sec'].iloc[0]:.3f} → {df['t_sec'].iloc[-1]:.3f}")
    return df


def estimate_sampling_rate(df):
    diffs = df["t_sec"].diff().dropna()
    # Buang outlier (jitter ekstrem)
    diffs_clean = diffs[diffs > 0]
    if len(diffs_clean) == 0:
        print("\n[3] Tidak bisa estimasi sampling rate")
        return 10.0  # fallback
    median_dt = diffs_clean.median()
    fs = 1.0 / median_dt
    print(f"\n[3] Sampling rate: median dt = {median_dt*1000:.1f} ms  →  ~{fs:.1f} Hz")
    return fs


def print_column_stats(df):
    print("\n[4] Statistik per kolom:")
    skip = {"t_sec", "timestamp", "sensor_id"}
    cols = [c for c in df.columns if c not in skip
            and df[c].dtype in [np.float64, np.float32, np.int64, np.int32]]
    stats = df[cols].describe().T[["mean", "std", "min", "max"]]
    print(stats.to_string())


def compute_accel_resultant(df):
    present = [c for c in ACCEL_COLS if c in df.columns]
    if len(present) == 3:
        df["accel_res"] = np.sqrt(df[present[0]]**2 + df[present[1]]**2 + df[present[2]]**2)
        # De-mean untuk hilangkan gravitasi (komponen statis ~1g)
        df["accel_vib"] = df["accel_res"] - df["accel_res"].median()
        print(f"\n[5] Accel resultant: {present}")
        print(f"    accel_vib = resultant - median (hilangkan gravitasi statis)")
    elif len(present) > 0:
        df["accel_vib"] = df[present[0]] - df[present[0]].median()
        print(f"\n[5] Hanya {present}, pakai |{present[0]}| de-meaned")
    else:
        df["accel_vib"] = np.nan
        print("\n[5] WARNING: tidak ada kolom accel")
    return df


def compute_rolling_rms(df, fs):
    window = max(10, int(ROLLING_SEC * fs))
    df["rolling_rms"] = (
        df["accel_vib"]
        .pow(2)
        .rolling(window, center=True, min_periods=1)
        .mean()
        .pow(0.5)
    )
    print(f"\n[6] Rolling RMS: window = {window} samples ({ROLLING_SEC}s @ {fs:.1f}Hz)")
    return df


def plot_overview(df, out_dir):
    fig, axes = plt.subplots(3, 1, figsize=(14, 9), sharex=True)
    t = df["t_sec"] / 60  # menit

    axes[0].plot(t, df["accel_vib"], lw=0.15, color="steelblue", alpha=0.7)
    axes[0].set_ylabel("Accel Vibration (g)")
    axes[0].set_title("Full Recording — Accel Vibration (de-meaned, gravitasi dihilangkan)")
    axes[0].grid(alpha=0.3)

    axes[1].plot(t, df["rolling_rms"], lw=0.5, color="darkorange")
    axes[1].set_ylabel(f"Rolling RMS ({ROLLING_SEC}s)")
    axes[1].set_title("Rolling RMS — intensitas vibrasi compressor")
    axes[1].grid(alpha=0.3)

    if "pressure" in df.columns:
        axes[2].plot(t, df["pressure"], lw=0.3, color="green")
        axes[2].set_ylabel("Pressure (Pa)")
        axes[2].set_title("Pressure")
        axes[2].grid(alpha=0.3)
    else:
        axes[2].set_visible(False)

    axes[-1].set_xlabel("Waktu (menit dari awal recording)")
    plt.tight_layout()
    out = os.path.join(out_dir, "fridge_overview.png")
    plt.savefig(out, dpi=130, bbox_inches="tight")
    plt.close()
    print(f"\n[7] Saved: {out}")


def plot_tail(df, out_dir, tail_minutes=60, zoom_start=None, zoom_end=None):
    total_sec = df["t_sec"].iloc[-1]

    if zoom_start is not None or zoom_end is not None:
        # Mode zoom ke range menit tertentu
        t_start = (zoom_start or 0) * 60
        t_end   = (zoom_end or total_sec/60) * 60
        df_tail = df[(df["t_sec"] >= t_start) & (df["t_sec"] <= t_end)].copy()
        label = f"Menit {zoom_start or 0}–{zoom_end or int(total_sec/60)}"
    else:
        # Mode N menit terakhir
        cutoff  = max(0, total_sec - tail_minutes * 60)
        df_tail = df[df["t_sec"] >= cutoff].copy()
        label   = f"Last {tail_minutes} Minutes"

    t = (df_tail["t_sec"] - df_tail["t_sec"].iloc[0]) / 60

    fig, axes = plt.subplots(2, 1, figsize=(14, 6), sharex=True)

    axes[0].plot(t, df_tail["accel_vib"], lw=0.2, color="steelblue", alpha=0.7)
    axes[0].set_ylabel("Accel Vibration (g)")
    axes[0].set_title(f"{label} — cari perubahan pola compressor")
    axes[0].grid(alpha=0.3)

    axes[1].plot(t, df_tail["rolling_rms"], lw=0.5, color="red")
    axes[1].set_ylabel(f"Rolling RMS ({ROLLING_SEC}s)")
    axes[1].set_title("Rolling RMS — drop = compressor off / anomali")
    axes[1].grid(alpha=0.3)

    axes[-1].set_xlabel("Waktu (menit)")
    plt.tight_layout()
    out = os.path.join(out_dir, "fridge_tail_anomaly.png")
    plt.savefig(out, dpi=130, bbox_inches="tight")
    plt.close()
    print(f"[8] Saved: {out}")


def plot_compressor_rhythm(df, out_dir):
    """Zoom 5 menit di tengah untuk lihat ritme compressor normal."""
    total_sec = df["t_sec"].iloc[-1]
    mid = total_sec / 2
    w = 5 * 60
    df_mid = df[(df["t_sec"] >= mid - w/2) & (df["t_sec"] <= mid + w/2)].copy()
    t = df_mid["t_sec"] - df_mid["t_sec"].iloc[0]

    fig, axes = plt.subplots(2, 1, figsize=(14, 6), sharex=True)
    axes[0].plot(t, df_mid["accel_vib"], lw=0.2, color="purple", alpha=0.8)
    axes[0].set_ylabel("Accel Vibration (g)")
    axes[0].set_title("Compressor Rhythm — 5 menit di tengah (normal operation)")
    axes[0].grid(alpha=0.3)

    axes[1].plot(t, df_mid["rolling_rms"], lw=0.5, color="darkorange")
    axes[1].set_ylabel(f"Rolling RMS ({ROLLING_SEC}s)")
    axes[1].set_title("Rolling RMS — pola on/off compressor normal")
    axes[1].grid(alpha=0.3)

    axes[-1].set_xlabel("Waktu (detik)")
    plt.tight_layout()
    out = os.path.join(out_dir, "fridge_compressor_rhythm.png")
    plt.savefig(out, dpi=130, bbox_inches="tight")
    plt.close()
    print(f"[9] Saved: {out}")


def estimate_anomaly_boundary(df):
    if "rolling_rms" not in df.columns:
        return
    total_sec = df["t_sec"].iloc[-1]

    # Baseline dari 70% awal (jauh dari area anomali)
    cutoff_idx = int(len(df) * 0.70)
    baseline = df["rolling_rms"].iloc[:cutoff_idx]
    mu    = baseline.mean()
    sigma = baseline.std()

    print(f"\n[10] Baseline RMS (70% awal): mean={mu:.5f}, std={sigma:.5f}")

    # Anomali = RMS turun signifikan (compressor mati = vibrasi hilang)
    low_thresh  = mu - 2 * sigma
    # Anomali = RMS naik signifikan (vibrasi chaos)
    high_thresh = mu + 3 * sigma

    tail = df[df["t_sec"] >= total_sec * 0.70]

    # Deteksi drop
    drop_region = tail[tail["rolling_rms"] < max(low_thresh, mu * 0.3)]
    if len(drop_region) > 0:
        est = drop_region["t_sec"].iloc[0]
        print(f"    Kemungkinan anomali (vibrasi drop) mulai di:")
        print(f"    t = {est:.0f}s dari awal = {est/60:.1f} menit dari awal")
        print(f"    = {(total_sec - est)/60:.1f} menit sebelum akhir recording")
    else:
        print("    Tidak ada drop signifikan terdeteksi di 30% akhir")
        print("    → Cek fridge_tail_anomaly.png secara visual")

    # Deteksi chaos (RMS tinggi tapi irregular)
    chaos_region = tail[tail["rolling_rms"] > high_thresh]
    if len(chaos_region) > 0:
        est = chaos_region["t_sec"].iloc[0]
        print(f"    Kemungkinan anomali (vibrasi chaos) mulai di:")
        print(f"    t = {est:.0f}s dari awal = {est/60:.1f} menit dari awal")


def detect_gaps(df, fs):
    """Deteksi gap besar dalam timestamp (sensor restart / jeda recording)."""
    if "t_sec" not in df.columns:
        return
    expected_dt = 1.0 / fs
    diffs = df["t_sec"].diff().dropna()
    # Gap = lebih dari 10x interval normal
    gap_thresh = expected_dt * 10
    gaps = diffs[diffs > gap_thresh]
    if len(gaps) == 0:
        print(f"\n[11] Tidak ada gap besar terdeteksi (threshold: {gap_thresh:.2f}s)")
        return
    print(f"\n[11] Gap besar terdeteksi ({len(gaps)} gap, threshold: {gap_thresh:.1f}s):")
    for idx, gap_dt in gaps.items():
        t_gap = df.loc[idx, "t_sec"]
        print(f"     t = {t_gap/60:.1f} menit dari awal  →  gap {gap_dt:.1f}s ({gap_dt/60:.1f} menit)")


def main():
    args = parse_args()
    out_dir = os.path.dirname(os.path.abspath(args.csv))

    df = load_csv(args.csv)
    df = parse_timestamps(df)
    fs = estimate_sampling_rate(df)
    print_column_stats(df)
    df = compute_accel_resultant(df)
    df = compute_rolling_rms(df, fs)

    plot_overview(df, out_dir)
    plot_tail(df, out_dir, tail_minutes=args.tail, zoom_start=args.zoom_start, zoom_end=args.zoom_end)
    plot_compressor_rhythm(df, out_dir)
    detect_gaps(df, fs)
    estimate_anomaly_boundary(df)

    print("\n=== Done ===")
    print("Cek 3 PNG di folder CSV-nya.")
    print("Fokus ke fridge_tail_anomaly.png untuk identifikasi anomali.")


if __name__ == "__main__":
    main()