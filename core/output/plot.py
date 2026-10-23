"""
plot.py — one figure of a device's run, read from its files (CSV, labels, manifest).

One panel per value column (readings, STEL/TWA, rates, battery, signal), one panel for all 0/1 alarm
columns and one for text states (device_mode, fall_state, ...). Every event the device saw is a
shaded band in every panel (one colour per event kind), connection gaps are yellow, what the device
should have done (expected labels) is hatched in the states panel. One legend for the whole figure.
"""
import json

import numpy as np
import pandas as pd

LABEL_TEXT = {"event": str, "detail": str, "scope": str}       # text columns of a labels file

GAP = "#f4d03f"
PALETTE = ["#8ecae6", "#c77dff", "#90be6d", "#f28482", "#5e60ce", "#84a59d", "#b5838d", "#4ea8de", "#e07a5f"]


def _panels(df):
    vals, alarms, states = [], [], []
    for c in df.columns[2:]:
        x = df[c]
        if not pd.api.types.is_numeric_dtype(x):
            states.append(c)
        elif set(pd.unique(x.dropna())) <= {0, 1} and ("alarm" in c or c.endswith(("_over_range", "_fast", "_hi", "_low",
                                                                                   "_high"))):
            alarms.append(c)
        else:
            vals.append(c)
    return vals, alarms, states


def plot_run(csv_path, labels_path, manifest_path, title: str = None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    df = pd.read_csv(csv_path)
    lab = pd.read_csv(labels_path, dtype=LABEL_TEXT).fillna({c: "" for c in LABEL_TEXT})
    with open(manifest_path) as fh:
        man = json.load(fh)
    start = pd.Timestamp(man["world"]["start_utc"].replace("Z", ""))
    t = pd.to_datetime(df["timestamp"].str.replace("Z", ""))
    vals, alarms, states = _panels(df)
    n = len(vals) + bool(alarms) + bool(states)
    heights = [1] * len(vals) + ([max(1, len(alarms) / 4)] if alarms else []) + ([max(1, len(states) / 2)] if states else [])
    fig, axes = plt.subplots(max(n, 1), 1, figsize=(13, 1.7 * sum(heights or [1]) + 1.6), sharex=True, squeeze=False,
                             gridspec_kw={"height_ratios": heights or [1]})
    axes = axes[:, 0]
    at = lambda s: start + pd.to_timedelta(s, unit="s")
    seen = lab[lab.scope.isin(["world", "device"]) & ~lab.event.str.contains(":")]
    kinds = [k for k in dict.fromkeys(seen.event) if k != "connection_loss"]
    colour = {k: PALETTE[i % len(PALETTE)] for i, k in enumerate(kinds)}

    def shade(a):
        for r in seen.itertuples():
            a.axvspan(at(r.start_s), at(max(r.end_s, r.start_s + 1)), color=GAP if r.event == "connection_loss"
                      else colour[r.event], alpha=0.35 if r.event == "connection_loss" else 0.25, lw=0, zorder=0)
    i = 0
    generic = set(man["device"].get("generic_columns", []))
    for c in vals:
        a = axes[i]
        a.plot(t, df[c], color="black", lw=0.8, zorder=2)
        a.set_ylabel(c + ("\n(generic)" if c in generic else ""), fontsize=8)
        shade(a)
        i += 1
    if alarms:
        a = axes[i]
        for k, c in enumerate(alarms):
            a.step(t, df[c] * 0.8 + k, where="post", lw=1, color="#c1121f")
        a.set_yticks(np.arange(len(alarms)) + 0.4)
        a.set_yticklabels(alarms, fontsize=7)
        a.set_ylim(-0.2, len(alarms))
        shade(a)
        i += 1
    if states:
        a = axes[i]
        for k, c in enumerate(states):
            cats = list(dict.fromkeys(df[c].astype(str)))
            code = df[c].astype(str).map({v: j for j, v in enumerate(cats)})
            a.step(t, k + 0.8 * code / max(len(cats) - 1, 1), where="post", lw=1, color="#1d3557")
            a.text(1.002, (k + 0.4) / len(states), f"{c}: {' / '.join(cats)}", transform=a.transAxes, fontsize=7,
                   va="center")
        for r in lab[lab.scope == "expected"].itertuples():
            a.axvspan(at(r.start_s), at(r.end_s), facecolor="none", edgecolor="#e63946", hatch="///", lw=0, zorder=1)
        a.set_yticks([])
        a.set_ylim(-0.2, len(states))
        a.set_ylabel("states", fontsize=8)
        shade(a)
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    axes[-1].set_xlabel("Time (UTC)")
    for a in axes:
        a.grid(alpha=0.3)
    handles = [Line2D([], [], color="black", lw=1, label="reading" + (" ((generic) = generic part, all values "
                                                                       "ASSUMPTION)" if generic else ""))]
    if alarms:
        handles.append(Line2D([], [], color="#c1121f", lw=1, label="alarm (0/1)"))
    handles += [Patch(facecolor=colour[k], alpha=0.5, label=k) for k in kinds]
    if (lab.event == "connection_loss").any():
        handles.append(Patch(facecolor=GAP, alpha=0.6, label="connection gap (no rows)"))
    if (lab.scope == "expected").any():
        handles.append(Patch(facecolor="none", edgecolor="#e63946", hatch="///", label="expected device response"))
    fig.legend(handles=handles, loc="upper center", ncol=min(len(handles), 6), fontsize=8, frameon=False,
               bbox_to_anchor=(0.5, 1 - 0.55 / fig.get_size_inches()[1]))
    d = man["device"]
    fig.suptitle(title or f"{d['name']} · {man['scenario']['name']} · seed {man['seed']} · {man['world']['title']} "
                 f"(realism: {man['world']['realism']})", fontsize=11, y=1 - 0.1 / fig.get_size_inches()[1])
    fig.tight_layout(rect=(0, 0, 0.9 if states else 1, 1 - 0.85 / fig.get_size_inches()[1]))
    return fig


def zip_run(results) -> bytes:
    """ZIP of every device's CSV, labels, manifest, gate and summary (results of core.output.run)."""
    import io
    import os
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for r in results:
            for k in ("csv", "labels", "manifest", "gate", "summary"):
                if r.get(k):
                    z.write(r[k], os.path.basename(r[k]))
    return buf.getvalue()
