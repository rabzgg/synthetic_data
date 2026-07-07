#!/usr/bin/env bash
# Temporal holdout test — jawaban untuk "testing on the same data is only
# validation of the pipeline":
#   fit     : 60% awal sesi near_compressor (menit 0 - ~198)
#   holdout : 40% akhir (menit ~198 - 331), TIDAK pernah dilihat saat fitting
#   eval    : synthetic (durasi = durasi holdout) vs holdout
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA="$SCRIPT_DIR/data"

NORMAL_CSV="$DATA/fridge/xdk_fridge_normal.csv"
FIT_CSV="$DATA/fridge/xdk_fridge_fit60.csv"
HOLDOUT_CSV="$DATA/fridge/xdk_fridge_holdout40.csv"
CONFIG="$SCRIPT_DIR/configs/fridge/fridge_fit60.json"
OUTPUT="$SCRIPT_DIR/out/fridge/fridge_holdout_syn.csv"
FIT_RATIO=0.6

# ─── Step 1: split 60/40 berdasarkan waktu ───────────────────────────────────
echo "=== Step 1: Split fit (60% awal) / holdout (40% akhir) ==="
python3 - << PYEOF
import pandas as pd

df = pd.read_csv("$NORMAL_CSV")
t = (df["timestamp"] - df["timestamp"].iloc[0]) / 1e3
total_s = t.iloc[-1]
cut_s = total_s * $FIT_RATIO

fit = df[t <= cut_s]
hold = df[t > cut_s]
fit.to_csv("$FIT_CSV", index=False)
hold.to_csv("$HOLDOUT_CSV", index=False)
print(f"Total    : {total_s/60:.1f} menit")
print(f"Fit      : 0 - {cut_s/60:.1f} menit  ({len(fit):,} baris)")
print(f"Holdout  : {cut_s/60:.1f} - {total_s/60:.1f} menit  ({len(hold):,} baris)")
print(f"HOLDOUT_S={total_s - cut_s:.0f}")
PYEOF

HOLDOUT_S=$(python3 - << PYEOF
import pandas as pd
df = pd.read_csv("$HOLDOUT_CSV")
print(int((df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]) / 1e3))
PYEOF
)

# ─── Step 2: fit config HANYA dari 60% awal ──────────────────────────────────
echo ""
echo "=== Step 2: Extract config dari fit set ==="
python3 "$SCRIPT_DIR/extract_config.py" \
    --csv "$FIT_CSV" \
    --output "$CONFIG" \
    --domain fridge

# ─── Step 3: generate synthetic sepanjang durasi holdout ─────────────────────
echo ""
echo "=== Step 3: Generate synthetic (${HOLDOUT_S}s = durasi holdout) ==="
python3 "$SCRIPT_DIR/main.py" \
    --config "$CONFIG" \
    --output "$OUTPUT" \
    --duration "$HOLDOUT_S"

# ─── Step 4: eval vs holdout (data yang tidak pernah dilihat) ────────────────
echo ""
echo "=== Step 4a: Struktur & duty cycle vs holdout ==="
python3 "$SCRIPT_DIR/compare_fridge.py" \
    --real "$HOLDOUT_CSV" \
    --syn "syn (fit 60% awal)=$OUTPUT" \
    --out-prefix "$SCRIPT_DIR/results_fridge_holdout"

echo ""
echo "=== Step 4b: Statistical similarity vs holdout ==="
python3 "$SCRIPT_DIR/stat_eval.py" \
    --real "$HOLDOUT_CSV" --syn "$OUTPUT" \
    --cols acceleration_z rolling_std temperature humidity pressure

echo ""
echo "=== Step 4c: TSTR (train on synthetic, test on holdout real) ==="
python3 "$SCRIPT_DIR/tstr_eval.py" \
    --real "$HOLDOUT_CSV" --syn "$OUTPUT" --col rolling_std

echo ""
echo "Done: $SCRIPT_DIR/results_fridge_holdout.png"
