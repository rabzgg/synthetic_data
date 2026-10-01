#!/usr/bin/env bash
# Generate all three arm sensors with the joint-template engine (shared cycle schedule)
# and run the full physics gate (per-sensor + cross-sensor). Exit code != 0 on gate failure.
#
# Usage: ./run_robot_arm_joint.sh [seed=42] [duration_s=3600] [outdir=out/robot_arm_joint] [--identity]
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SEED="${1:-42}"
DURATION="${2:-3600}"
OUTDIR="${3:-$SCRIPT_DIR/out/robot_arm_joint}"
EXTRA="${4:-}"
BANK="$SCRIPT_DIR/configs/robot_arm/joint_bank_arm.npz"
mkdir -p "$OUTDIR"

for k in 1 2 3; do
  echo "=== sensor_$k (seed $SEED, ${DURATION}s) ==="
  # same --seed and --duration for every sensor -> identical shared cycle schedule
  python3 "$SCRIPT_DIR/main.py" --config "$SCRIPT_DIR/configs/robot_arm/sensor_${k}_joint.json" \
      --output "$OUTDIR/sensor_${k}_seed${SEED}.csv" --duration "$DURATION" --seed "$SEED" --no-physics-gate
done

echo ""
echo "=== physics gate (all sensors) ==="
python3 "$SCRIPT_DIR/physics_gate.py" --bank "$BANK" \
    --syn sensor_1="$OUTDIR/sensor_1_seed${SEED}.csv" \
    --syn sensor_2="$OUTDIR/sensor_2_seed${SEED}.csv" \
    --syn sensor_3="$OUTDIR/sensor_3_seed${SEED}.csv" $EXTRA
