"""
cut_data.py — slice the first N% of a CSV and save to xdk_data/cutted_data/

Usage
-----
python3 cut_data.py --input xdk_data/some/path/raw/file.csv
python3 cut_data.py --input xdk_data/some/path/raw/file.csv --pct 10
python3 cut_data.py --input xdk_data/some/path/raw/file.csv --pct 5 --output-dir xdk_data/cutted_data

Defaults
--------
--pct        5   (percent of rows to keep, from the start)
--output-dir xdk_data/cutted_data (relative to this script's directory)

Output filename: <original_stem>_<pct>pct.csv
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUTDIR = os.path.join(SCRIPT_DIR, "data", "cutted")

parser = argparse.ArgumentParser(description="Slice first N% of a CSV.")
parser.add_argument("--input",      required=True,          help="Path to input CSV")
parser.add_argument("--pct",        type=float, default=5.0, help="Percentage to keep (default: 5)")
parser.add_argument("--output-dir", default=DEFAULT_OUTDIR,  help="Output directory (default: xdk_data/cutted_data)")
args = parser.parse_args()

if not os.path.exists(args.input):
    print(f"Error: file not found: {args.input}")
    sys.exit(1)

if not (0 < args.pct <= 100):
    print(f"Error: --pct must be between 0 and 100, got {args.pct}")
    sys.exit(1)

df = pd.read_csv(args.input)
total_rows  = len(df)
keep_rows   = max(1, int(total_rows * args.pct / 100))
df_cut      = df.iloc[:keep_rows]

stem        = os.path.splitext(os.path.basename(args.input))[0]
pct_tag     = str(args.pct).rstrip("0").rstrip(".")  # 5.0 → "5", 1.5 → "1.5"
out_name    = f"{stem}_{pct_tag}pct.csv"
out_path    = os.path.join(os.path.abspath(args.output_dir), out_name)

os.makedirs(os.path.dirname(out_path), exist_ok=True)
df_cut.to_csv(out_path, index=False)

duration_s  = (df_cut["timestamp"].iloc[-1] - df_cut["timestamp"].iloc[0]) / 1000.0
print(f"Input        : {args.input}")
print(f"Total rows   : {total_rows:,}")
print(f"Kept rows    : {keep_rows:,}  ({args.pct}%)")
print(f"Duration     : {duration_s:.1f}s  ({duration_s/60:.1f} min)")
print(f"Saved to     : {out_path}")
