#!/usr/bin/env bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA="$SCRIPT_DIR/data"

INPUT_CSV="$DATA/aquarium/xdk_01_09022026-10022026_60pct.csv"
CONFIG="$SCRIPT_DIR/configs/aquarium/aquarium_01_2d_final.json"
OUTPUT="$SCRIPT_DIR/out/aquarium/aquarium_xdk1_24h_final.csv"

echo "=== Step 1: extract config ==="
python3 "$SCRIPT_DIR/extract_config.py" --csv "$INPUT_CSV" --output "$CONFIG"

echo ""
echo "=== Step 2: generate 24h ==="
python3 "$SCRIPT_DIR/main.py" --config "$CONFIG" --output "$OUTPUT" --duration 86400 --start-time 10:00 --light-on 06:00 --light-off 17:00

echo ""
echo "Done: $OUTPUT"
