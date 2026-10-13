#!/usr/bin/env bash
# Generate every arm sensor of one joint-template bank (shared cycle schedule)
# and run the full physics gate (per-sensor + cross-sensor). Exit code != 0 on gate failure.
#
# Usage: cli/run_robot_arm_joint.sh [seed=42] [duration_s=3600] [outdir=out/robot_arm_joint] [config_dir=configs/robot_arm]
#   all six sensors: cli/run_robot_arm_joint.sh 42 3600 out/arm6 configs/robot_arm_6
set -e
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SEED="${1:-42}"
DURATION="${2:-3600}"
OUTDIR="${3:-$ROOT_DIR/out/robot_arm_joint}"
CFG_DIR="${4:-$ROOT_DIR/configs/robot_arm}"
case "$CFG_DIR" in /*) ;; *) CFG_DIR="$ROOT_DIR/$CFG_DIR" ;; esac
mkdir -p "$OUTDIR"

SYN_ARGS=()
for cfg in "$CFG_DIR"/sensor_*_joint.json; do
  s="$(basename "$cfg" _joint.json)"
  echo "=== $s (seed $SEED, ${DURATION}s) ==="
  # same --seed and --duration for every sensor -> identical shared cycle schedule
  python3 "$ROOT_DIR/cli/main.py" --config "$cfg" \
      --output "$OUTDIR/${s}_seed${SEED}.csv" --duration "$DURATION" --seed "$SEED" --no-physics-gate
  SYN_ARGS+=(--syn "$s=$OUTDIR/${s}_seed${SEED}.csv")
  BANK="$CFG_DIR/$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['motion']['bank'])" "$cfg")"
done

echo ""
echo "=== physics gate (all sensors) ==="
python3 "$ROOT_DIR/validation/physics_gate.py" --bank "$BANK" "${SYN_ARGS[@]}"
