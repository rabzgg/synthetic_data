"""ablation_table.py — markdown tables comparing ablation variants (out/ablation/<name>/ablation.json).
Usage: python3 ablation_table.py S1_gaussian S1_A_no_jitter S1_empirical"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
names = sys.argv[1:]
R = {n: json.load(open(os.path.join(ROOT, "out", "ablation", n, "ablation.json"))) for n in names}
K = list(R[names[0]]["sensors"])
G = list(R[names[0]]["sensors"][K[0]]["summary"]["c2st_groups_mean"])
L = ["### omega p99 vs real (5 seeds; tolerance from gate_thresholds.json)", "",
     "| sensor | tol | " + " | ".join(names) + " |", "|---|---|" + "---|" * len(names)]
for k in K:
    s0 = R[names[0]]["sensors"][k]["summary"]
    cells = []
    for n in names:
        s = R[n]["sensors"][k]["summary"]
        seeds = R[n]["sensors"][k]["seeds"].values()
        rng = f"{100 * min(e['omega_rel'] for e in seeds):+.1f}..{100 * max(e['omega_rel'] for e in seeds):+.1f}"
        cells.append(f"{100 * s['omega_rel_mean']:+.1f}% ({rng}), pass {s['omega_pass_n']}/5")
    L.append(f"| {k} | ±{100 * s0['omega_tol']:.1f}% | " + " | ".join(cells) + " |")
L += ["", "### C2ST (mean ± sd over 5 seeds; 0.5 = indistinguishable)", "",
      "| sensor | feature set | gate threshold | " + " | ".join(names) + " |", "|---|---|---|" + "---|" * len(names)]
for k in K:
    thr = R[names[0]]["sensors"][k]["summary"]["c2st_threshold"]
    L.append(f"| {k} | **all** | {thr:.3f} | " + " | ".join(
        f"**{R[n]['sensors'][k]['summary']['c2st_mean']:.3f} ± {R[n]['sensors'][k]['summary']['c2st_sd']:.3f}**" for n in names) + " |")
    for g in G:
        L.append(f"| {k} | {g} | | " + " | ".join(
            f"{R[n]['sensors'][k]['summary']['c2st_groups_mean'][g]:.3f} ± {R[n]['sensors'][k]['summary']['c2st_groups_sd'][g]:.3f}" for n in names) + " |")
L += ["", "### logged dt (ms), mean over seeds; real = full recording", "",
      "| sensor | source | p1 | p25 | p50 | p75 | p99 | sd | excess kurtosis | lag-1 ac | lag-2 ac | % > 150 | % < 40 |",
      "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
F = ["p1", "p25", "p50", "p75", "p99", "sd", "kurt", "ac1", "ac2", "pct_gt150", "pct_lt40"]
fmt = lambda v, f: f"{v:+.2f}" if f.startswith("ac") else (f"{v:.0f}" if f == "kurt" else f"{v:.1f}" if not f.startswith("pct") else f"{v:.2f}")
for k in K:
    r = R[names[0]]["sensors"][k]["real_dt"]
    L.append(f"| {k} | real | " + " | ".join(fmt(r[f], f) for f in F) + " |")
    for n in names:
        d = R[n]["sensors"][k]["summary"]["dt_mean"]
        L.append(f"| {k} | {n} | " + " | ".join(fmt(d[f], f) for f in F) + " |")
if all("copy_pct_mean" in R[n]["sensors"][K[0]]["summary"] for n in names):
    L += ["", "### copy metric (% of synthetic 37 s windows with corr > 0.99 to some real window)", "",
          "| sensor | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for k in K:
        if "copy_pct_mean" in R[names[0]]["sensors"][k]["summary"]:
            L.append(f"| {k} | " + " | ".join(f"{R[n]['sensors'][k]['summary']['copy_pct_mean']:.1f}" for n in names) + " |")
print("\n".join(L))
