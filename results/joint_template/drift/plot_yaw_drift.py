"""Plot the rest-pose yaw (heading) drift per sensor vs time and temperature (from drift_diagnosis.json).
Run from clean_project/:  python3 results/joint_template/drift/plot_yaw_drift.py"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

D = os.path.join("results", "joint_template", "drift")
d = json.load(open(os.path.join(D, "drift_diagnosis.json")))
fig, ax = plt.subplots(3, 2, figsize=(14, 10))
for i, (s, x) in enumerate(d.items()):
    S = x["series"]
    t, y, tc = np.array(S["t_min"]), np.array(S["yaw_deg"]), np.array(S["temp_c"])
    a = ax[i, 0]
    a.plot(t, y, "o", ms=3, color="black", label="yaw at the same rest pose (per cycle)")
    a.plot(t, x["d_yaw_slope_deg_per_min"] * t + (y - x["d_yaw_slope_deg_per_min"] * t).mean(), color="tab:orange",
           label=f"linear fit {x['d_yaw_slope_deg_per_min'] * 60:+.1f}°/h (R² {x['d_r2_linear_time']:.2f})")
    a.plot(t, np.array(S["tilt_deg"]), "s", ms=2, color="tab:blue", alpha=0.6, label="tilt change (same pose)")
    a.set_ylabel(f"{s}\nangle vs first cycles [°]")
    a.grid(alpha=0.3)
    a.legend(fontsize=8)
    b = ax[i, 1]
    b.scatter(tc, y, c=t, s=8, cmap="viridis")
    b.set_ylabel("yaw [°]")
    b.set_title(f"{s}: yaw vs temperature (colour = time); corr {x['d_corr_yaw_temp']:+.2f}, "
                f"corr(time, temp) {x['d_corr_time_temp']:+.2f}", fontsize=9)
    b.grid(alpha=0.3)
ax[-1, 0].set_xlabel("elapsed time [min]")
ax[-1, 1].set_xlabel("sensor temperature [°C]")
fig.suptitle("Rest-pose orientation drift of the real XDKs: heading (yaw) vs tilt\n"
             "(sensor → arm-link mapping: [USER TO VERIFY])")
fig.tight_layout(rect=(0, 0, 1, 0.95))
fig.savefig(os.path.join(D, "yaw_drift.png"), dpi=110)
print("wrote", os.path.join(D, "yaw_drift.png"))
