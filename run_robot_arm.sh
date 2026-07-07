#!/usr/bin/env bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA="$SCRIPT_DIR/data"

INPUT_CSV="$DATA/robot_arm/sensor_1_converted_10pct.csv"
CONFIG="$SCRIPT_DIR/configs/robot_arm/xdk_joint_1.json"
OUTPUT="$SCRIPT_DIR/out/robot_arm/xdk_joint1_syn.csv"

echo "=== Step 1: extract config ==="
python3 "$SCRIPT_DIR/extract_config.py" --csv "$INPUT_CSV" --output "$CONFIG"

echo ""
echo "=== Step 2: generate 24h ==="
python3 "$SCRIPT_DIR/main.py" --config "$CONFIG" --output "$OUTPUT" --duration 3600

echo ""
echo "Done: $OUTPUT"
