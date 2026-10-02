"""Step variance of raw accel/mag vs smooth(template) + residual(other cycle), 40 random cycles per sensor.
Run from clean_project/:  python3 results/joint_template/ablation/residual_step_covariance.py"""
import os
import sys

import numpy as np

sys.path.insert(0, os.getcwd())
import core.joint_template as J

b = J.JointBank("configs/robot_arm/joint_bank_arm.npz")
rng = np.random.default_rng(0)
for s in b.sensors:
    out = []
    for i in rng.choice(len(b.windows), 40, replace=False):
        t = b.segment(s, i)
        d = b.segment(s, (i + 3) % len(b.windows))
        n = min(len(t["A"]), len(d["A"]))
        for key, rk in (("A", "rA"), ("M", "rM")):
            S = np.diff(t[key][:n], axis=0)
            R = np.diff(t[rk][:n], axis=0)
            Rd = np.diff(d[rk][:n], axis=0)
            cov = np.mean((S - S.mean(0)) * (R - R.mean(0)), 0)
            out.append((key, (S.var(0) + R.var(0) + 2 * cov).mean(), (S.var(0) + Rd.var(0)).mean(), (2 * cov).mean()))
    for key in ("A", "M"):
        o = np.array([x[1:] for x in out if x[0] == key])
        print(f"{s} {'accel' if key == 'A' else 'mag'}: step variance raw {o[:, 0].mean():.3g}, "
              f"smooth + donor residual {o[:, 1].mean():.3g} (ratio {o[:, 1].mean() / o[:, 0].mean():.3f}); "
              f"2 cov(smooth step, residual step) {o[:, 2].mean():.3g}")
