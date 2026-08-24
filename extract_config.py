"""
extract_config.py — fit a scenario config from a real CSV sample.

Usage
-----
python3 extract_config.py --csv path/to/sample.csv --output configs/robot_arm/idle.json

Optional flags
--------------
--domain    domain hint passed to AutoFitter (default: robot_arm)
--duration  override duration_s in output config (seconds)
            useful when sample is 10% but you want config to generate full-length data

Example
-------
python3 extract_config.py \
    --csv ../new_robot_arm_data/sliced/xdk_joint_03_..._10pct.csv \
    --output configs/robot_arm/joint_03_normal.json \
    --duration 4451
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from core.generator import fit_from_real_data

parser = argparse.ArgumentParser(description="Fit a scenario config from a CSV sample.")
parser.add_argument("--csv",      required=True,              help="Path to input CSV")
parser.add_argument("--output",   required=True,              help="Path to output JSON config")
parser.add_argument("--domain",   default="robot_arm",        help="Domain hint (default: robot_arm)")
parser.add_argument("--duration", type=float, default=None,   help="Override duration_s in output (seconds)")
parser.add_argument("--labels",   default=None,               help="Row-aligned labels CSV (supervised states, e.g. dog robot poses)")
args = parser.parse_args()

if not os.path.exists(args.csv):
    print(f"Error: CSV not found: {args.csv}")
    sys.exit(1)

print(f"Fitting from : {args.csv}")
scenario = fit_from_real_data(args.csv, domain_hints={"domain": args.domain}, labels_csv=args.labels)

if args.duration:
    scenario["duration_s"] = args.duration
    print(f"Duration     : overridden to {args.duration}s")

os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
with open(args.output, "w") as f:
    json.dump(scenario, f, indent=2)

print(f"Saved config : {args.output}")
print(f"  domain     : {scenario.get('domain', '?')}")
print(f"  duration   : {scenario['duration_s']:.0f}s  ({scenario['duration_s']/60:.1f} min)")
print(f"  frequency  : {scenario['frequency_hz']} Hz")
print(f"  columns    :")
for col, cfg in scenario["columns"].items():
    print(f"    {col:<22} {cfg['engine']}")
