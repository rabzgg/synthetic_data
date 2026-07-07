#!/usr/bin/env bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA="$SCRIPT_DIR/data"

# ─── Input ────────────────────────────────────────────────────────────────────
RAW_CSV="$DATA/fridge/xdk_near_compressor_14112025_mvp_raw.csv"

# Cut 12 menit terakhir (area anomali, ~330-342 menit).
# Sisanya (~330 menit) dipakai buat fitting — cukup banyak cycles compressor
# supaya AutoFitter._detect_rhythm() dapet cukup sample buat ukur durasi ON/OFF.
NORMAL_CSV="$DATA/fridge/xdk_fridge_normal.csv"
ANOMALY_TAIL_MIN=12

# ─── Output ───────────────────────────────────────────────────────────────────
mkdir -p "$SCRIPT_DIR/configs/fridge"
mkdir -p "$SCRIPT_DIR/out/fridge"

CONFIG="$SCRIPT_DIR/configs/fridge/fridge_01_normal.json"
OUTPUT="$SCRIPT_DIR/out/fridge/fridge_01_normal.csv"
DURATION=20574

# ─── Step 1: Cut normal segment ───────────────────────────────────────────────
echo "=== Step 1: Cut normal segment (buang $ANOMALY_TAIL_MIN menit terakhir) ==="
python3 - << PYEOF
import pandas as pd

df = pd.read_csv("$RAW_CSV")
ts  = df["timestamp"]
t_sec = (ts - ts.iloc[0]) / 1e3
total_min = t_sec.iloc[-1] / 60
tail_min = $ANOMALY_TAIL_MIN
keep_min = total_min - tail_min

print(f"Total duration : {total_min:.1f} menit")
print(f"Cut tail       : {tail_min} menit (anomali)")
print(f"Fitting window : {keep_min:.1f} menit")

cutoff_sec = keep_min * 60
df_normal  = df[t_sec <= cutoff_sec].copy()
print(f"Rows normal    : {len(df_normal):,} / {len(df):,}")

df_normal.to_csv("$NORMAL_CSV", index=False)
print(f"Saved          : $NORMAL_CSV")
PYEOF

echo ""
echo "=== Step 2: Extract config (AutoFitter, domain=fridge) ==="
python3 "$SCRIPT_DIR/extract_config.py" \
    --csv "$NORMAL_CSV" \
    --output "$CONFIG" \
    --domain fridge

echo ""
echo "=== Step 3: Generate synthetic (duration=${DURATION}s) ==="
python3 "$SCRIPT_DIR/main.py" \
    --config "$CONFIG" \
    --output "$OUTPUT" \
    --duration $DURATION

echo ""
echo "Done: $OUTPUT"