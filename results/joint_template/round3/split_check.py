import os, sys, numpy as np
sys.path.insert(0, os.getcwd())
import core.joint_template as J
for name, path in (("savgol", "configs/robot_arm/joint_bank_arm.npz"), ("lowpass", "out/round3/joint_bank_lowpass.npz")):
    b = J.JointBank(path)
    for s in b.sensors:
        row = {}
        for key, rk in (("A", "rA"), ("M", "rM")):
            corr, ratio = [], []
            for i in range(len(b.windows)):
                t = b.segment(s, i); d = b.segment(s, (i + 3) % len(b.windows))
                n = min(len(t[key]), len(d[key]))
                S = np.diff(t[key][:n], axis=0); R = np.diff(t[rk][:n], axis=0); Rd = np.diff(d[rk][:n], axis=0)
                corr.append(np.mean([np.corrcoef(S[:, c], R[:, c])[0, 1] for c in range(3) if S[:, c].std() > 0 and R[:, c].std() > 0]))
                ratio.append((S + Rd).var(0).mean() / (S + R).var(0).mean())
            row[key] = (np.nanmean(corr), np.nanpercentile(corr, 5), np.nanpercentile(corr, 95), np.mean(ratio))
        print(f"{name:7s} {s}: accel step corr {row['A'][0]:+.3f} (p5 {row['A'][1]:+.3f}, p95 {row['A'][2]:+.3f}), donor/raw step var {row['A'][3]:.3f} | "
              f"mag step corr {row['M'][0]:+.3f} (p5 {row['M'][1]:+.3f}, p95 {row['M'][2]:+.3f}), donor/raw step var {row['M'][3]:.3f}")
