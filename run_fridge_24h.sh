#!/usr/bin/env bash
# Generate synthetic fridge 24 jam dari dua sumber fitting:
#   1. full  : xdk_fridge_normal.csv        (~331 menit)
#   2. 25pct : xdk_fridge_normal_25pct.csv  (~86 menit pertama)
# lalu bandingkan keduanya ke data real via compare_fridge.py.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA="$SCRIPT_DIR/data"

RAW_CSV="$DATA/fridge/xdk_near_compressor_14112025_mvp_raw.csv"
NORMAL_CSV="$DATA/fridge/xdk_fridge_normal.csv"
PCT25_CSV="$DATA/fridge/xdk_fridge_normal_25pct.csv"
ANOMALY_TAIL_MIN=12

DURATION=86400   # 24 jam

mkdir -p "$SCRIPT_DIR/configs/fridge" "$SCRIPT_DIR/out/fridge"

# ─── Step 0: pastikan normal segment ada (cut ekor anomali) ──────────────────
if [ ! -f "$NORMAL_CSV" ]; then
    echo "=== Step 0: Cut normal segment (buang $ANOMALY_TAIL_MIN menit terakhir) ==="
    python3 - << PYEOF
import pandas as pd
df = pd.read_csv("$RAW_CSV")
t_sec = (df["timestamp"] - df["timestamp"].iloc[0]) / 1e3
cutoff = t_sec.iloc[-1] - $ANOMALY_TAIL_MIN * 60
df[t_sec <= cutoff].to_csv("$NORMAL_CSV", index=False)
print("Saved:", "$NORMAL_CSV")
PYEOF
fi

# ─── Step 1: fit config dari dua sumber ──────────────────────────────────────
echo ""
echo "=== Step 1a: Extract config (full) ==="
python3 "$SCRIPT_DIR/extract_config.py" \
    --csv "$NORMAL_CSV" \
    --output "$SCRIPT_DIR/configs/fridge/fridge_01_normal.json" \
    --domain fridge

echo ""
echo "=== Step 1b: Extract config (25pct) ==="
python3 "$SCRIPT_DIR/extract_config.py" \
    --csv "$PCT25_CSV" \
    --output "$SCRIPT_DIR/configs/fridge/fridge_25pct.json" \
    --domain fridge

# ─── Step 2: generate 24 jam dari masing-masing config ───────────────────────
echo ""
echo "=== Step 2a: Generate 24h (fit full) ==="
python3 "$SCRIPT_DIR/main.py" \
    --config "$SCRIPT_DIR/configs/fridge/fridge_01_normal.json" \
    --output "$SCRIPT_DIR/out/fridge/fridge_full_24h.csv" \
    --duration $DURATION

echo ""
echo "=== Step 2b: Generate 24h (fit 25pct) ==="
python3 "$SCRIPT_DIR/main.py" \
    --config "$SCRIPT_DIR/configs/fridge/fridge_25pct.json" \
    --output "$SCRIPT_DIR/out/fridge/fridge_25pct_24h.csv" \
    --duration $DURATION

# ─── Step 3: bandingkan ke data real ─────────────────────────────────────────
echo ""
echo "=== Step 3: Compare vs real ==="
python3 "$SCRIPT_DIR/compare_fridge.py" \
    --syn "fit full 24h=$SCRIPT_DIR/out/fridge/fridge_full_24h.csv" \
    --syn "fit 25pct 24h=$SCRIPT_DIR/out/fridge/fridge_25pct_24h.csv" \
    --out-prefix "$SCRIPT_DIR/results_fridge_24h"

echo ""
echo "Done:"
echo "  $SCRIPT_DIR/out/fridge/fridge_full_24h.csv"
echo "  $SCRIPT_DIR/out/fridge/fridge_25pct_24h.csv"
echo "  $SCRIPT_DIR/results_fridge_24h.png"
