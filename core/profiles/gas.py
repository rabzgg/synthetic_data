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
    "standard": ([], "Standard shift: bump test + 1-3 short exposures"),
    "stel_alarm": (["sustained_stel"], "Shift with a STEL alarm (sustained H2S exposure)"),
    "twa_alarm": (["prolonged_twa"], "Shift with a TWA alarm (long CO exposure)"),
    "over_range": (["over_range"], "Shift with an over-range reading (LEL above range)"),
    "voc_exposure": (["voc"], "Shift with a VOC exposure (PID)"),
    "pump_fault": (["pump_fault"], "Shift with a pump fault"),
}
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
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import pandas as pd
        from core.gas_detector import _v
        d = pd.read_csv(csv_paths[0])
        t = (pd.to_datetime(d["timestamp"]) - pd.to_datetime(d["timestamp"].iloc[0])).dt.total_seconds().to_numpy() / 3600
        sp = _v(self.A["alarm_setpoints"])
        chans = list(self.spec["channels"].items())
        fig, ax = plt.subplots(len(chans) + 1, 1, figsize=(14, 2.3 * (len(chans) + 1)), sharex=True)
        ev = d["event"].astype(str).to_numpy()

        def gapped(y):
            y = np.asarray(y, float).copy()
            br = np.where(d["gap_before_s"].to_numpy() > 0)[0]
            return np.insert(t, br, np.nan), np.insert(y, br, np.nan)
        for a, (g, ch) in zip(ax, chans):
            x, y = gapped(d[ch["column"]])
            a.plot(x, y, color="black", lw=0.8, label="reading")
            p = ch["column"].split("_")[0]
            if f"{p}_stel_{ch['column'].split('_', 1)[1]}" in d:
                xs, ys = gapped(d[f"{p}_stel_{ch['column'].split('_', 1)[1]}"])
                a.plot(xs, ys, color="tab:blue", lw=0.8, label="STEL")
                xt, yt = gapped(d[f"{p}_twa_{ch['column'].split('_', 1)[1]}"])
                a.plot(xt, yt, color="tab:green", lw=0.8, label="TWA")
            for lvl, c, nm in ((sp[g]["low"], "tab:orange", "low setpoint"), (sp[g]["high"], "tab:red", "high setpoint")):
                a.axhline(lvl, color=c, ls="--", lw=0.8, label=nm)
            alarm = (d[f"{p}_alarm_low"] == 1) | (d[f"{p}_alarm_high"] == 1)
            if alarm.any():
                a.fill_between(t, 0, 1, where=alarm.to_numpy(), color="tab:red", alpha=0.12,
                               transform=a.get_xaxis_transform(), label="alarm")
            a.set_ylabel(ch["column"])
            a.grid(alpha=0.3)
            a.legend(loc="upper right", fontsize=7, ncol=3)
        a = ax[-1]
        a.plot(t, d["battery_pct"], color="tab:purple", lw=1, label="battery %")
        a.set_ylabel("battery [%]")
        a2 = a.twinx()
        a2.plot(t, d["signal_strength_dbm"], color="tab:gray", lw=0.6, label="signal [dBm]")
        a2.set_ylabel("signal [dBm]")
        states = [("pump_state", "fault", "tab:brown", "pump fault"), ("sos_state", 1, "tab:pink", "SOS"),
                  ("bridge_link", "satellite", "tab:cyan", "satellite link")]
        for col, on, c, nm in states:
            if col in d and (d[col] == on).any():
                a.fill_between(t, 0, 1, where=(d[col] == on).to_numpy(), color=c, alpha=0.3,
                               transform=a.get_xaxis_transform(), label=nm)
        h1, l1 = a.get_legend_handles_labels()
        h2, l2 = a2.get_legend_handles_labels()
        a.legend(h1 + h2, l1 + l2, loc="lower left", fontsize=7, ncol=4)
        for gb in np.where(d["gap_before_s"].to_numpy() > 0)[0]:
            for ax_ in ax:
                ax_.axvspan(t[gb] - d["gap_before_s"].iloc[gb] / 3600, t[gb], color="gold", alpha=0.35)
        a.set_xlabel("time since shift start [h]  (yellow: connection gap, no rows; red shade: gas alarm)")
        a.grid(alpha=0.3)
        bump = np.where(d["device_mode"] == "bump_test")[0]
        title = (f"{self.label}: {self.scenario_label(scenario)}, seed {seed}\n"
                 f"synthetic, datasheet-based (no real data); bump test at {t[bump[0]] * 60:.0f} min" if len(bump) else "")
        fig.suptitle(title, fontsize=11)
        fig.tight_layout(rect=(0, 0, 1, 0.96))
        os.makedirs(out_dir, exist_ok=True)
        p = os.path.join(out_dir, f"{self.device}_{scenario}_seed{seed}.png")
        fig.savefig(p, dpi=100)
        plt.close(fig)
        return [p]
