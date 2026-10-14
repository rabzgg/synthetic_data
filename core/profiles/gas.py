"""
gas.py — one profile per portable gas detector (configs/gas/<device>/spec.json).

Wraps core/gas_detector.py (generation) and validation/gas_gate.py (rule gate) without changing
them. There is no real recording behind these devices: the data obeys the datasheet and is
consistent by rule; it is not meant to look like field data.

Scenarios: "standard" (bump test + 1-3 short random exposures) and variants that place one extra
event on purpose: a STEL alarm, a TWA alarm, an over-range reading; on the io6 also a VOC exposure
and a pump fault. They map onto the generator's `forced` items, the same items its coverage plan uses.
"""
import os

import numpy as np

from .base import GateReport, SensorProfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIGS = os.path.join(ROOT, "configs")
SCENARIOS = {
    "standard": ([], "Normal shift"),
    "stel_alarm": (["sustained_stel"], "Test: STEL alarm (H2S)"),
    "twa_alarm": (["prolonged_twa"], "Test: TWA alarm (CO)"),
    "over_range": (["over_range"], "Test: LEL over-range"),
    "voc_exposure": (["voc"], "Test: VOC exposure"),
    "pump_fault": (["pump_fault"], "Test: pump fault"),
}
GLOSSARY = {
    "LEL": "Lower Explosive Limit: the lowest concentration at which a gas can ignite; 100 %LEL means the air "
           "could explode.",
    "STEL": "Short-Term Exposure Limit: the average exposure over the last 15 minutes.",
    "TWA": "Time-Weighted Average: the exposure averaged over an 8-hour work shift.",
    "PID / VOC": "A PID (photo-ionisation detector) measures VOCs, volatile organic compounds such as solvent and "
                 "fuel vapours.",
    "Bump test": "A short check at the start of a shift: test gas is applied to confirm every sensor reacts and "
                 "alarms.",
    "Over-range": "The real level is above what the sensor can measure, so the reading stops at the top of its range.",
}
REALISM = {True: "Realism: normal shift, the kind of day a detector typically sees (event rates are assumptions, "
                 "not field measurements).",
           False: "Realism: test case. The event is forced to appear; how often it happens does not represent the field."}
MIN_S = {"twa_alarm": 7 * 3600.0}       # the long CO exposure (4-5 h) needs room in the shift
DEFAULT_MIN_S = 2 * 3600.0             # room for the bump test, one exposure and its recovery


def gas_devices() -> list:
    d = os.path.join(CONFIGS, "gas")
    return sorted(x for x in os.listdir(d) if os.path.isfile(os.path.join(d, x, "spec.json")))


class GasDetectorProfile(SensorProfile):
    gate_name = "Rule gate"
    plot_title = "Gas readings, alarms and device state (synthetic; no real data behind it)"

    def __init__(self, device: str):
        from core.gas_detector import load_device
        self.device = device
        self.spec, self.A = load_device(device, CONFIGS)
        self.name = device
        self.label = self.spec["model"]

    # scenarios and durations
    def scenarios(self):
        sc = ["standard", "stel_alarm", "twa_alarm", "over_range"]
        if "voc" in self.spec["channels"]:
            sc.append("voc_exposure")
        if "pump_state" in self.spec.get("state_columns", {}):
            sc.append("pump_fault")
        return sc

    def scenario_label(self, scenario):
        return SCENARIOS[scenario][1]

    def scenario_help(self, scenario) -> list:
        """Three plain lines for the UI: what happens, the term, how realistic it is. Numbers come from
        assumptions.json, so the text follows the generator's settings."""
        from core.gas_detector import _v
        A = self.A
        ex, ty = A["exposure"], _v(A["exposure"]["types"])
        lim, sp = _v(A["exposure_limits"]), _v(A["alarm_setpoints"])
        rng = lambda r, f=1: f"{r[0] / f:g}–{r[1] / f:g}"
        pl = _v(ex["plateau_s"])
        gases = ", ".join(g.upper() for g in _v(ex["gases"]) if g in self.spec["channels"])
        if scenario == "standard":
            what = (f"A bump test at the start of the shift, then 1–3 short gas exposures ({gases}) of {rng(pl, 60)} "
                    "minutes each. Alarms go off only if a reading crosses its setpoint.")
            term = "Bump test = a quick check with test gas that every sensor reacts and alarms."
        elif scenario == "stel_alarm":
            t = ty["sustained_stel"]
            what = (f"The worker is in an area with H2S at {rng(t['peak'])} ppm for {rng(t['plateau_s'], 60)} minutes. "
                    f"The 15-minute average passes the {lim['h2s']['stel']:g} ppm limit, so the STEL alarm goes off.")
            term = "STEL = the average exposure over the last 15 minutes."
        elif scenario == "twa_alarm":
            t = ty["prolonged_twa"]
            what = (f"The worker spends {rng(t['plateau_s'], 3600)} hours in CO at {rng(t['peak'])} ppm. Averaged over "
                    f"the 8-hour shift this passes the {lim['co']['twa']:g} ppm limit, so the TWA alarm goes off.")
            term = "TWA = the exposure averaged over an 8-hour shift."
        elif scenario == "over_range":
            t = ty["over_range"]
            top = self.spec["channels"]["lel"]["range_max"]["value"]
            what = (f"Combustible gas rises to {rng(t['peak'])} %LEL for {rng(t['plateau_s'], 60)} minutes. The sensor "
                    f"can only show up to {top} %LEL, so the reading sticks at {top} and the over-range flag is set.")
            term = "LEL = the level at which a gas can ignite; 100 %LEL means explosive air."
        elif scenario == "voc_exposure":
            what = (f"The worker meets solvent or fuel vapour (VOC) at {rng(_v(ex['peak'])['voc'])} ppm for "
                    f"{rng(pl, 60)} minutes. The VOC alarms go off above {sp['voc']['low']:g} / {sp['voc']['high']:g} ppm.")
            term = "PID / VOC = a photo-ionisation sensor that measures volatile organic compounds."
        else:
            d = _v(A["pump_fault"])["duration_s"]
            what = (f"The sampling pump fails for {rng(d, 60)} minutes: the pump alarm is on. The gas readings are not "
                    "changed (an assumption: the effect of a stopped pump on the readings is not modelled).")
            term = "Pump = draws air into the detector; without it the sensors may not see the surrounding air."
        return [what, term, REALISM[scenario == "standard"]]

    def glossary(self) -> dict:
        return dict(GLOSSARY)

    def event_summary(self, csv_paths) -> list:
        """What actually happens in the data, read from the CSV (not from the config)."""
        import pandas as pd
        d = pd.read_csv(csv_paths[0])
        ts = pd.to_datetime(d["timestamp"], utc=True)
        hm = lambda i: ts.iloc[i].strftime("%H:%M")
        runs = _runs
        out = []
        for s, e in runs(d["device_mode"] == "bump_test"):
            out.append((s, f"Bump test {hm(s)}–{hm(e)}"))
        ev = d["event"].astype(str)
        for g, ch in self.spec["channels"].items():
            unit = ch["range_max"]["unit"]
            for s, e in runs(ev == f"exposure_{g}"):
                pk = d[ch["column"]].iloc[s:e + 1].max()
                out.append((s, f"{g.upper()} exposure {hm(s)}–{hm(e)} (peak {pk:g} {unit})"))
            p = ch["column"].split("_")[0]
            for col, name in ((f"{p}_alarm_stel", f"{g.upper()} STEL alarm"), (f"{p}_alarm_twa", f"{g.upper()} TWA alarm"),
                              (f"{p}_over_range", f"{g.upper()} over-range")):
                if col in d:
                    for s, e in runs(d[col] == 1):
                        out.append((s, f"{name} {hm(s)}–{hm(e)}"))
        for col, on, name in (("pump_state", "fault", "Pump fault"), ("sos_state", 1, "SOS"),
                              ("bridge_link", "satellite", "Satellite link")):
            if col in d:
                for s, e in runs(d[col] == on):
                    out.append((s, f"{name} {hm(s)}–{hm(e)}"))
        for i in np.where(d["gap_before_s"] > 0)[0]:
            out.append((i, f"No data {(ts.iloc[i] - pd.Timedelta(seconds=float(d['gap_before_s'].iloc[i]))).strftime('%H:%M')}"
                           f"–{hm(i)} (connection gap, {d['gap_before_s'].iloc[i]:g} s)"))
        return [text for _, text in sorted(out, key=lambda x: x[0])]

    def items(self, scenario):
        return list(SCENARIOS[scenario][0])

    def shift_s(self):
        from core.gas_detector import _v
        return float(_v(self.A["shift"]["duration_s"]))

    def max_duration_s(self, scenario):
        return self.shift_s()

    def min_duration_s(self, scenario):
        return MIN_S.get(scenario, DEFAULT_MIN_S)

    def default_duration_s(self, scenario):
        return self.shift_s()

    def hard_max_duration_s(self, scenario):
        return float(self.spec["battery_runtime_h"]["value"]) * 3600

    def beyond_max_message(self, scenario):
        return (f"Longer than one 8-h shift. TWA is still divided by 8 h and the scenario rules assume one shift; "
                f"the battery reaches 0 % at the datasheet runtime ({self.spec['battery_runtime_h']['value']} h).")

    def limitations(self, scenario, duration_s):
        L = ["Datasheet-based data: it obeys the datasheet (range, resolution, battery runtime) and is consistent by "
             "rule (alarms, STEL/TWA, bump test, announced connection gaps). It is NOT made to look like field data: "
             "no real recording of this device was available.",
             "Everything not in the datasheet (alarm setpoints, STEL/TWA limits, logging interval, bump-test gas, T90, "
             "exposure levels, noise, battery drain, signal, gaps) is an ASSUMPTION; see assumptions.json in this ZIP.",
             "The `event` column is a ground-truth label from the generator, not a device field."]
        if scenario != "standard":
            L.append("The event of this scenario is placed on purpose; it is not a measure of how often it happens.")
        for g, ch in self.spec["channels"].items():
            if "assumption" in ch:
                L.append(f"{ch['name']} ({ch['column']}): {ch['assumption']}.")
        if "assumption" in self.spec["battery_runtime_h"]:
            L.append(f"Battery runtime: {self.spec['battery_runtime_h']['assumption']}.")
        if duration_s > self.shift_s():
            L.append(self.beyond_max_message(scenario))
        return L

    # generation and validation
    def generate(self, scenario, duration_s, seed, out_dir, progress=None):
        from core.gas_detector import GasDetectorEngine
        os.makedirs(out_dir, exist_ok=True)
        eng = GasDetectorEngine(self.spec, self.A)
        if progress:
            progress(0.1, "generating the shift")
        df = eng.generate(duration_s, seed, self.items(scenario))
        path = os.path.join(out_dir, f"{self.device}_{scenario}_seed{seed}.csv")
        eng.write_csv(df, path)
        if progress:
            progress(1.0, "written")
        return [path]

    def validate(self, scenario, csv_paths):
        from validation.gas_gate import check_gas_file
        return GateReport.from_physics(check_gas_file(csv_paths[0], self.device, items=self.items(scenario)))

    def extra_files(self, run):
        return {"spec.json": os.path.join(CONFIGS, "gas", self.device, "spec.json"),
                "assumptions.json": os.path.join(CONFIGS, "gas", "assumptions.json")}

    # figure
    def plot(self, scenario, csv_paths, seed, duration_s, out_dir):
        os.makedirs(out_dir, exist_ok=True)
        p = os.path.join(out_dir, f"{self.device}_{scenario}_seed{seed}.png")
        self.plot_file(csv_paths[0], f"{self.label} · {self.scenario_label(scenario)} · seed {seed} · "
                                     "synthetic, datasheet-based", p)
        return [p]

    def plot_events(self, d) -> list:
        """Blocks to label above the figure, read from the CSV (event, device_mode, flag and gap_before_s
        columns): [(start, end, text, kind)] with start/end as timestamps."""
        ts = pd_times(d)
        bump = (d["device_mode"] == "bump_test").to_numpy()
        ev = d["event"].astype(str)
        out = [(ts[s], ts[e], "Bump test", "bump") for s, e in _runs(bump)]
        for g, ch in self.spec["channels"].items():
            unit, p = ch["range_max"]["unit"], ch["column"].split("_")[0]
            for s, e in _runs(ev == f"exposure_{g}"):
                pk = d[ch["column"]].iloc[s:e + 1].max()
                over = f"{p}_over_range" in d and (d[f"{p}_over_range"].iloc[s:e + 1] == 1).any()
                out.append((ts[s], ts[e], f"{gas_name(g)} exposure {pk:g} {unit}" + (" (over-range)" if over else ""),
                             "exposure"))
            low, high = (d[f"{p}_alarm_low"] == 1).to_numpy(), (d[f"{p}_alarm_high"] == 1).to_numpy()
            for s, e in _runs((low | high) & ~bump, join=ALARM_JOIN_ROWS):
                out.append((ts[s], ts[e], f"{gas_name(g)} alarm {'high' if high[s:e + 1].any() else 'low'}", "alarm"))
            for col, nm in ((f"{p}_alarm_stel", "STEL"), (f"{p}_alarm_twa", "TWA")):
                if col in d:
                    for s, e in _runs((d[col] == 1).to_numpy() & ~bump, join=ALARM_JOIN_ROWS):
                        out.append((ts[s], ts[e], f"{gas_name(g)} {nm} alarm", "alarm"))
        for col, on, nm, kind in DEVICE_BLOCKS:
            if col in d:
                out += [(ts[s], ts[e], nm[0].upper() + nm[1:], kind) for s, e in _runs(d[col] == on)]
        gap = d["gap_before_s"].to_numpy()
        for i in np.where(gap > 0)[0]:
            g = float(gap[i])
            out.append((ts[i] - np.timedelta64(int(g), "s"), ts[i],
                        f"Connection gap {g:g} s" if g < 90 else f"Connection gap {g / 60:.0f} min", "gap"))
        return sorted(out, key=lambda x: x[0])

    def plot_file(self, csv_path, subtitle, out_path):
        """One PNG: a panel per gas (reading, setpoints, STEL/TWA) and a device panel (battery, signal);
        shared blocks for gas alarm, bump test, connection gap and device states; one legend on top and
        a label above every block, all read from the CSV."""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D
        from matplotlib.patches import Patch
        import pandas as pd
        from core.gas_detector import _v
        d = pd.read_csv(csv_path)
        t = pd_times(d)
        dt = np.timedelta64(int(round(_v(self.A["logging_interval_s"]))), "s")
        sp = _v(self.A["alarm_setpoints"])
        chans = list(self.spec["channels"].items())
        bump = (d["device_mode"] == "bump_test").to_numpy()
        gap = d["gap_before_s"].to_numpy()
        n = len(chans) + 1
        head_in, panel_in, foot_in = 2.6, 1.9, 0.55     # unused header room is cropped on save
        H = head_in + n * panel_in + foot_in
        fig, ax = plt.subplots(n, 1, figsize=(14, H), sharex=True, dpi=100)
        fig.subplots_adjust(left=0.07, right=0.93, top=1 - head_in / H, bottom=foot_in / H, hspace=0.12)

        def gapped(y):
            br = np.where(gap > 0)[0]
            return np.insert(t, br, t[br] - dt), np.insert(np.asarray(y, float), br, np.nan)

        def blocks(a, mask, color, alpha, z=0):
            for s, e in _runs(mask):
                a.axvspan(t[s], t[e] + dt, color=color, alpha=alpha, lw=0, zorder=z)

        has_stel = False
        for a, (g, ch) in zip(ax, chans):
            col, p = ch["column"], ch["column"].split("_")[0]
            x, y = gapped(d[col])
            a.plot(x, y, color="black", lw=0.8, zorder=3)
            rest = col.split("_", 1)[1]
            if f"{p}_stel_{rest}" in d:
                has_stel = True
                for c, color in ((f"{p}_stel_{rest}", COLORS["stel"]), (f"{p}_twa_{rest}", COLORS["twa"])):
                    a.plot(*gapped(d[c]), color=color, lw=0.9, zorder=2)
            a.axhline(sp[g]["low"], color=COLORS["low"], ls="--", lw=0.9, zorder=1)
            a.axhline(sp[g]["high"], color=COLORS["high"], ls="--", lw=0.9, zorder=1)
            alarm = np.zeros(len(d), bool)
            for c in (f"{p}_alarm_low", f"{p}_alarm_high", f"{p}_alarm_stel", f"{p}_alarm_twa"):
                if c in d:
                    alarm |= (d[c] == 1).to_numpy()
            blocks(a, alarm & ~bump, COLORS["alarm"], 0.55)        # alarms during the bump test sit under its block
            a.set_ylabel(f"{gas_name(g)} ({ch['range_max']['unit']})")
            a.grid(alpha=0.3)
        a = ax[-1]
        a.plot(t, d["battery_pct"], color=COLORS["battery"], lw=1.1, zorder=3)
        a.set_ylabel("Battery (%)", color=COLORS["battery"])
        a.set_ylim(0, 105)
        a2 = a.twinx()
        a2.plot(*gapped(d["signal_strength_dbm"]), color=COLORS["signal"], lw=0.6)
        a2.set_ylabel("Signal (dBm)", color=COLORS["signal"])
        a.grid(alpha=0.3)
        present = {}
        for col, on, nm, kind in DEVICE_BLOCKS:
            if col in d and (d[col] == on).any():
                present[kind] = nm
                for a_ in (ax if kind == "sos" else [a]):
                    blocks(a_, (d[col] == on).to_numpy(), COLORS[kind], ALPHA[kind])
        for a_ in ax:
            blocks(a_, bump, COLORS["bump"], ALPHA["bump"])
            for i in np.where(gap > 0)[0]:          # drawn at least MIN_GAP_DRAW_S wide so short gaps stay visible
                a_.axvspan(t[i] - np.timedelta64(int(max(gap[i], MIN_GAP_DRAW_S)), "s"), t[i], color=COLORS["gap"],
                           alpha=ALPHA["gap"], lw=0, zorder=0)
        a.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        a.set_xlabel("Time (UTC)")
        a.set_xlim(t[0], t[-1] + dt)

        # a small label above every block, in up to LABEL_ROWS rows so they do not overlap
        a0 = ax[0]
        fig.canvas.draw()
        r = fig.canvas.get_renderer()
        box = a0.get_window_extent(r)
        row_px = 13
        right = [-np.inf] * LABEL_ROWS
        for s, e, text, kind in self.plot_events(d):
            xc = a0.transData.transform((mdates.date2num(s + (e - s) / 2), 0))[0]
            txt = fig.text(0, 0, text, fontsize=7.5, color=LABEL_COLORS[kind], ha="left", va="bottom")
            w = txt.get_window_extent(r).width
            x0 = min(max(xc - w / 2, box.x0), box.x1 - w)
            row = next((k for k in range(LABEL_ROWS) if x0 > right[k] + 6), None)
            if row is None:
                row = int(np.argmin(right))
            right[row] = x0 + w
            txt.set_position(fig.transFigure.inverted().transform((x0, box.y1 + 3 + row * row_px)))
        used = int(np.isfinite(right).sum())

        # header stacked upwards from the labels: one legend for every panel, subtitle, title
        to_fig = lambda y_px: fig.transFigure.inverted().transform((0, y_px))[1]
        line = lambda c, ls="-": Line2D([], [], color=c, ls=ls, lw=1.2)
        patch = lambda k: Patch(facecolor=COLORS[k], alpha=ALPHA[k])
        items = [(line("black"), "reading"), (line(COLORS["low"], "--"), "low setpoint"),
                 (line(COLORS["high"], "--"), "high setpoint")]
        if has_stel:
            items += [(line(COLORS["stel"]), "STEL (15-min average)"), (line(COLORS["twa"]), "TWA (8-h average)")]
        items += [(patch("alarm"), "gas alarm"), (patch("bump"), "bump test"), (patch("gap"), "connection gap (no rows)")]
        items += [(patch(k), present[k]) for k in ("sos", "pump", "satellite") if k in present]
        items += [(line(COLORS["battery"]), "battery"), (line(COLORS["signal"]), "signal")]
        leg = fig.legend([h for h, _ in items], [l for _, l in items], loc="lower center", ncol=min(len(items), 7),
                         bbox_to_anchor=(0.5, to_fig(box.y1 + 3 + used * row_px + 8)), fontsize=8.5, frameon=False,
                         handlelength=2.2)
        sub = fig.text(0.5, to_fig(leg.get_window_extent(r).y1 + 6), subtitle, ha="center", va="bottom", fontsize=10)
        fig.text(0.5, to_fig(sub.get_window_extent(r).y1 + 6), "Gas readings, alarms and device state",
                 ha="center", va="bottom", fontsize=13, weight="bold")
        fig.savefig(out_path, dpi=100, bbox_inches="tight", pad_inches=0.25)
        plt.close(fig)
        return out_path


GAS_NAMES = {"lel": "LEL", "o2": "O₂", "co": "CO", "h2s": "H₂S", "voc": "VOC"}
COLORS = {"low": "tab:orange", "high": "tab:red", "stel": "tab:blue", "twa": "tab:green", "alarm": "#f4a3b4",
          "bump": "#bdbdbd", "gap": "gold", "sos": "tab:purple", "pump": "tab:olive", "satellite": "tab:cyan",
          "battery": "tab:brown", "signal": "tab:gray"}
ALPHA = {"alarm": 0.55, "bump": 0.55, "gap": 0.5, "sos": 0.3, "pump": 0.3, "satellite": 0.25}
LABEL_COLORS = {"bump": "dimgray", "exposure": "black", "alarm": "#c0143c", "gap": "#8a6d00", "sos": "tab:purple",
                "pump": "olive", "satellite": "teal"}
DEVICE_BLOCKS = [("sos_state", 1, "SOS", "sos"), ("pump_state", "fault", "pump fault", "pump"),
                 ("bridge_link", "satellite", "satellite link", "satellite")]
ALARM_JOIN_ROWS = 30         # alarm runs less than 5 min apart get one label
LABEL_ROWS = 4
MIN_GAP_DRAW_S = 120


def gas_name(g: str) -> str:
    return GAS_NAMES.get(g, g.upper())


def pd_times(d):
    import pandas as pd
    return pd.to_datetime(d["timestamp"], utc=True).dt.tz_convert(None).to_numpy()


def _runs(mask, join: int = 0) -> list:
    """(first, last) row of each run of True; runs fewer than `join` rows apart are merged."""
    m = np.concatenate([[False], np.asarray(mask, bool), [False]])
    k = np.diff(m.astype(int))
    out = []
    for s, e in zip(np.where(k == 1)[0], np.where(k == -1)[0] - 1):
        if out and s - out[-1][1] <= join:
            out[-1] = (out[-1][0], e)
        else:
            out.append((s, e))
    return out
