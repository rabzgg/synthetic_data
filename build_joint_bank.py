"""
build_joint_bank.py — fit the joint-template bank for a multi-XDK arm from its real recordings.

Usage
-----
python3 build_joint_bank.py \\
    --real sensor_1=ppt/arm_robot/sensor_1_real.csv \\
    --real sensor_2=ppt/arm_robot/sensor_2_real.csv \\
    --real sensor_3=ppt/arm_robot/sensor_3_real.csv \\
    --output configs/robot_arm/joint_bank_arm.npz

All recordings must share one clock (absolute timestamps): the bank cuts every
sensor over the SAME time windows. The pool is the whole recording.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.joint_template import build_bank

ap = argparse.ArgumentParser(description="Fit a joint-template bank from real arm recordings.")
ap.add_argument("--real", action="append", required=True, help="sensor_name=path.csv (repeat per sensor)")
ap.add_argument("--output", required=True, help="output .npz bank")
ap.add_argument("--am-split", choices=["savgol", "lowpass"], default="savgol",
                help="accel/mag shape vs residual split: savgol(7,2) or rest-matched zero-phase low-pass")
ap.add_argument("--smooth-quat", action="store_true",
                help="savgol-smooth the template quaternion (old behaviour; default stores it as recorded)")
args = ap.parse_args()

paths = {}
for item in args.real:
    name, _, path = item.partition("=")
    if not path or not os.path.exists(path):
        print(f"Error: bad --real '{item}'")
        sys.exit(1)
    paths[name] = path

meta = build_bank(paths, args.output, smooth_quat=args.smooth_quat, am_split=args.am_split)
print(f"Saved bank   : {args.output}  ({os.path.getsize(args.output)/1e6:.1f} MB)")
print(f"  sensors    : {meta['sensors']}")
print(f"  period     : {meta['period_s']:.2f}s   smooth_quat={meta['smooth_quat']}")
print(f"  recording  : {meta['recording_s']:.0f}s ({meta['recording_s']/60:.1f} min)")
print(f"  cycles     : {meta['n_windows_kept']} kept of {meta['n_windows_detected']} detected")
for s, n in meta["noise"].items():
    print(f"  noise {s}: sig_rotvec={n['sig_rotvec_rad']:.2e} rad  log_jitter={n['log_jitter_ms']:.1f} ms")
