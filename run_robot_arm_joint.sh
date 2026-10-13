#!/usr/bin/env bash
# Generate every arm sensor of one joint-template bank (shared cycle schedule)
# and run the full physics gate (per-sensor + cross-sensor). Exit code != 0 on gate failure.
#
# Usage: ./run_robot_arm_joint.sh [seed=42] [duration_s=3600] [outdir=out/robot_arm_joint] [config_dir=configs/robot_arm]
#   sensors 4-6: ./run_robot_arm_joint.sh 42 3600 out/robot_arm_joint_456 configs/robot_arm_456
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SEED="${1:-42}"
DURATION="${2:-3600}"
OUTDIR="${3:-$SCRIPT_DIR/out/robot_arm_joint}"
CFG_DIR="${4:-$SCRIPT_DIR/configs/robot_arm}"
case "$CFG_DIR" in /*) ;; *) CFG_DIR="$SCRIPT_DIR/$CFG_DIR" ;; esac
mkdir -p "$OUTDIR"

SYN_ARGS=()
for cfg in "$CFG_DIR"/sensor_*_joint.json; do
  s="$(basename "$cfg" _joint.json)"
  echo "=== $s (seed $SEED, ${DURATION}s) ==="
  # same --seed and --duration for every sensor -> identical shared cycle schedule
  python3 "$SCRIPT_DIR/main.py" --config "$cfg" \
      --output "$OUTDIR/${s}_seed${SEED}.csv" --duration "$DURATION" --seed "$SEED" --no-physics-gate
  SYN_ARGS+=(--syn "$s=$OUTDIR/${s}_seed${SEED}.csv")
  BANK="$CFG_DIR/$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['motion']['bank'])" "$cfg")"
done

echo ""
echo "=== physics gate (all sensors) ==="
python3 "$SCRIPT_DIR/physics_gate.py" --bank "$BANK" "${SYN_ARGS[@]}"
