"""
bank_cycle_attribution.py — why does build_bank drop cycles, and which sensor blocks them?

Replays the selection rules of core.joint_template.build_bank on the same windows and names, per
dropped window, the rule and the sensor(s) responsible:
  length      cycle length off the period by > 4 %
  samples     < 80 % of the expected samples in the window for that sensor
  rest_start  the sensor is not at rest at the window start
  rest_end    the sensor is not at rest at the window end
  pose_jump   the window starts > 2° (tilt) from the previous kept cycle's end pose
Run from clean_project/:  python3 results/joint_template/arm6/bank_cycle_attribution.py [k ...]
"""
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, ".")
from core.joint_template import (load_real, omega_smooth, motion_threshold, detect_period, detect_cycles,
                                 tilt_deg)

ks = [int(x) for x in sys.argv[1:]] or [1, 2, 3, 4, 5, 6]
S = [f"sensor_{k}" for k in ks]
R = {s: load_real(f"ppt/arm_robot/{s}_real.csv") for s in S}
for s in S:
    R[s]["om"] = omega_smooth(R[s]["t"], R[s]["q"])
    R[s]["rest"] = R[s]["om"] < motion_threshold(R[s]["om"])
t0 = max(R[s]["t"][0] for s in S); t1 = min(R[s]["t"][-1] for s in S)
g = np.arange(t0, t1, 0.1)
comb = np.zeros(len(g))
for s in S:
    comb = np.maximum(comb, np.interp(g, R[s]["t"], R[s]["om"]) / motion_threshold(R[s]["om"]))
period = detect_period(0.1, (comb > 1.0).astype(float))
windows = detect_cycles(g, comb, 1.0, period)

reasons, keep = Counter(), []
for a, b in windows:
    if abs((b - a) - period) > 0.04 * period:
        reasons["length (all sensors)"] += 1
        continue
    bad = []
    for s in S:
        m = (R[s]["t"] >= a) & (R[s]["t"] <= b)
        if m.sum() < 0.8 * period * 10:
            bad.append(f"samples {s}")
        else:
            if not R[s]["rest"][m][0]:
                bad.append(f"rest_start {s}")
            if not R[s]["rest"][m][-1]:
                bad.append(f"rest_end {s}")
    if bad:
        for x in bad:
            reasons[x] += 1
        reasons["windows dropped by rest/samples"] += 1
        continue
    keep.append((a, b))

def pose(s, tt):
    i = int(np.clip(np.searchsorted(R[s]["t"], tt), 0, len(R[s]["t"]) - 1))
    return R[s]["q"][i]
clean = [keep[0]]
for a, b in keep[1:]:
    pa, pb = clean[-1]
    if abs(a - pb) < 1e-6:
        bad = [s for s in S if tilt_deg(pose(s, pb), pose(s, a))[0] > 2.0]
        if bad:
            for s in bad:
                reasons[f"pose_jump {s}"] += 1
            reasons["windows dropped by pose_jump"] += 1
            continue
    clean.append((a, b))
print(f"sensors {', '.join(S)}: period {period:.2f} s, {len(windows)} windows detected, {len(clean)} kept")
for k, v in sorted(reasons.items()):
    print(f"  {k:32s} {v}")
