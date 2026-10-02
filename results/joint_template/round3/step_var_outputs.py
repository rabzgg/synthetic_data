import os, sys, numpy as np, pandas as pd
sys.path.insert(0, os.getcwd())
from core.joint_template import REAL_ALIASES, A_COLS, M_COLS, _abs_seconds
def stepvar(df, cols):
    t = _abs_seconds(df["timestamp"]); X = df[list(cols)].to_numpy(float)
    ok = np.diff(t) <= 0.15                                   # consecutive ticks only
    return np.diff(X, axis=0)[ok].var(0).mean()
for k in (1, 2, 3):
    r = pd.read_csv(f"ppt/arm_robot/sensor_{k}_real.csv").rename(columns=REAL_ALIASES)
    t = _abs_seconds(r["timestamp"]); r = r[(t - t[0]) < 3600]
    ra, rm = stepvar(r, A_COLS), stepvar(r, M_COLS)
    line = f"sensor_{k}: real step var accel {ra:.3g}, mag {rm:.3g}"
    for v in ("R3_base_savgol", "R3_lowpass"):
        sa = [stepvar(pd.read_csv(f"out/ablation/{v}/sensor_{k}_seed{s}.csv"), A_COLS) for s in (42, 43, 44, 45, 46)]
        sm = [stepvar(pd.read_csv(f"out/ablation/{v}/sensor_{k}_seed{s}.csv"), M_COLS) for s in (42, 43, 44, 45, 46)]
        line += f" | {v}: accel ×{np.mean(sa)/ra:.3f}, mag ×{np.mean(sm)/rm:.3f}"
    print(line)
