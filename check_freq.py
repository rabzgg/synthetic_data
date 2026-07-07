"""
check_freq.py — analisis frekuensi sampling per menit dari CSV fridge.

Usage:
  python3 check_freq.py --csv path/to/fridge.csv
"""

import argparse
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import os

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", required=True)
    return p.parse_args()

def main():
    args = parse_args()
    df = pd.read_csv(args.csv)
    ts = df["timestamp"]

    # t_sec dari awal (asumsi ms)
    t_sec = (ts - ts.iloc[0]) / 1e3

    print(f"Rows          : {len(df):,}")
    print(f"Duration (ms) : {ts.max() - ts.min():,}")
    print(f"Duration (sec): {t_sec.iloc[-1]:.1f}")
    print(f"Duration (min): {t_sec.iloc[-1]/60:.1f}")
    print(f"Duration (h)  : {t_sec.iloc[-1]/3600:.2f}")
    print()

    # Hitung rows per menit (actual sample count, bukan dari timestamp)
    # Bagi data ke bucket 1 menit berdasarkan t_sec
    t_min = t_sec / 60
    bucket = t_min.apply(np.floor).astype(int)
    rows_per_min = bucket.value_counts().sort_index()

    # Convert rows per menit → Hz (rows / 60 detik)
    hz_per_min = rows_per_min / 60.0

    print(f"Sampling rate per menit (Hz):")
    print(f"  Min : {hz_per_min.min():.2f} Hz")
    print(f"  Max : {hz_per_min.max():.2f} Hz")
    print(f"  Mean: {hz_per_min.mean():.2f} Hz")
    print(f"  Std : {hz_per_min.std():.2f} Hz")
    print()

    # Cari menit dengan spike (jauh dari median)
    median_hz = hz_per_min.median()
    spike_thresh = median_hz * 3
    spikes = hz_per_min[hz_per_min > spike_thresh]
    if len(spikes) > 0:
        print(f"Spike terdeteksi (> {spike_thresh:.1f} Hz = 3x median {median_hz:.1f} Hz):")
        for minute, hz in spikes.items():
            print(f"  Menit {minute:3d}: {hz:.1f} Hz  ({rows_per_min[minute]} rows)")
    else:
        print(f"Tidak ada spike > 3x median ({median_hz:.1f} Hz)")

    # Cari menit dengan gap (jauh di bawah median)
    gap_thresh = median_hz * 0.3
    gaps = hz_per_min[hz_per_min < gap_thresh]
    if len(gaps) > 0:
        print(f"\nGap terdeteksi (< {gap_thresh:.1f} Hz = 0.3x median):")
        for minute, hz in gaps.items():
            print(f"  Menit {minute:3d}: {hz:.1f} Hz  ({rows_per_min[minute]} rows)")

    # Plot Hz per menit
    out_dir = os.path.dirname(os.path.abspath(args.csv))
    fig, axes = plt.subplots(2, 1, figsize=(14, 7), sharex=True)

    axes[0].plot(hz_per_min.index, hz_per_min.values, lw=0.8, color="steelblue")
    axes[0].axhline(median_hz, color="green", lw=1, ls="--", label=f"Median {median_hz:.1f} Hz")
    axes[0].axhline(spike_thresh, color="red", lw=1, ls="--", label=f"Spike thresh {spike_thresh:.1f} Hz")
    axes[0].set_ylabel("Sampling Rate (Hz)")
    axes[0].set_title("Sampling Rate per Menit")
    axes[0].legend()
    axes[0].grid(alpha=0.3)

    # Rows per menit (raw count)
    axes[1].bar(rows_per_min.index, rows_per_min.values, width=0.8, color="darkorange", alpha=0.7)
    axes[1].set_ylabel("Rows per Menit")
    axes[1].set_xlabel("Waktu (menit dari awal recording)")
    axes[1].set_title("Jumlah Rows per Menit")
    axes[1].grid(alpha=0.3)

    plt.tight_layout()
    out = os.path.join(out_dir, "fridge_sampling_rate.png")
    plt.savefig(out, dpi=130, bbox_inches="tight")
    plt.close()
    print(f"\nSaved: {out}")

if __name__ == "__main__":
    main()