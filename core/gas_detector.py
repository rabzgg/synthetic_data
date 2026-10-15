"""
gas_detector.py — rule-based generator for portable gas detectors, built from datasheet specs.

There is no real recording behind this engine. Its goal is data that obeys the datasheet (range,
resolution, battery runtime) and is consistent by rule (alarms, STEL/TWA, simultaneous bump test,
announced connection gaps). It is not meant to look like field data. Every number that is not in a
datasheet comes from configs/gas/assumptions.json, where it is marked ASSUMPTION.

Separate engine: SyntheticXDKGenerator is not touched. A device config selects it with
"engine": "gas_detector" (configs/gas/<device>/spec.json).

Pieces, applied in this order:
  1. event state machine: bump test at the start of the shift, 1-3 exposures, plus the items a
     coverage plan forces (STEL/TWA/over-range exposures, VOC exposure, pump fault), SOS (devices
     with sos_state), connection gaps, Bridge satellite periods.
  2. sensor response: first order towards the target, T90 while gas is applied, slower recovery.
  3. measurement noise.
  4. quantisation to the resolution, then clipping to the range: always LAST on every gas reading.
  5. derived columns from the final readings: STEL, TWA, alarm flags, over_range.
  6. device state: device_mode, pump_state/pump_alarm, sos_state, battery_pct, signal_strength_dbm,
     gateway columns, event label.
  7. connection gaps: their rows are removed last. The device keeps measuring through a gap, so
     STEL/TWA after it include the samples that were never sent. gap_before_s announces each gap.
"""
import json
import os
import zlib

import numpy as np
import pandas as pd

TOXIC = ("co", "h2s")          # channels with STEL / TWA


def _v(entry):
    """Value of a {value, unit, source|status} entry."""
    return entry["value"] if isinstance(entry, dict) and "value" in entry else entry


def decimals(res: float) -> int:
    return max(0, int(round(-np.log10(res)))) if res < 1 else 0


def quantize_clip(x, res, lo, hi):
    """Round to the resolution, then clip to the range (the last step on every reading)."""
    q = np.round(np.round(np.asarray(x, float) / res) * res, decimals(res))
    return np.clip(q, lo, hi) + 0.0          # + 0.0 turns -0.0 into 0.0


def load_device(device: str, configs_root: str):
    with open(os.path.join(configs_root, "gas", device, "spec.json")) as fh:
        spec = json.load(fh)
    with open(os.path.join(configs_root, "gas", "assumptions.json")) as fh:
        assumptions = json.load(fh)
    return spec, assumptions


def coverage_items(device: str, seed: int, assumptions: dict) -> list:
    """Items the coverage plan places on this (device, seed); [] for seeds outside the plan."""
    plan = _v(assumptions["coverage_plan"])
    items = plan["items"].get(device, plan["items"]["default"])
    seeds = plan["seeds"]
    offset = 0 if len(items) >= len(seeds) else 1
    return [it for k, it in enumerate(items) if k + offset < len(seeds) and seeds[k + offset] == seed]


class GasDetectorEngine:
    def __init__(self, spec: dict, assumptions: dict):
        if spec.get("engine") != "gas_detector":
            raise ValueError("spec is not a gas_detector config")
        self.spec, self.A = spec, assumptions
        self.channels = spec["channels"]
        self.dt = float(_v(assumptions["logging_interval_s"]))
        self.states = spec.get("state_columns", {})

    def _n(self, seconds):
        return int(round(seconds / self.dt))

    # 1. event state machine
    def _exposure(self, kind, rng):
        A, ex = self.A, self.A["exposure"]
        types = _v(ex["types"])
        if kind in ("short", "voc"):
            gases = ["voc"] if kind == "voc" else [g for g in _v(ex["gases"]) if g in self.channels]
            g = gases[int(rng.integers(len(gases)))]
            pk, pl = _v(ex["peak"])[g], _v(ex["plateau_s"])
        else:
            g, pk, pl = types[kind]["gas"], types[kind]["peak"], types[kind]["plateau_s"]
        return {"kind": f"exposure_{g}", "type": kind, "applied": self._n(rng.uniform(*pl)),
                "targets": {g: float(rng.uniform(*pk))}}

    def schedule(self, n: int, rng, forced=()) -> list:
        A = self.A
        bump = A["bump_test"]
        b0 = self._n(_v(bump["start_after_s"]))
        events = [{"kind": "bump_test", "type": "bump_test", "start": b0, "applied": self._n(_v(bump["gas_applied_s"])),
                   "targets": {g: float(c) for g, c in _v(bump["gas_mix"]).items() if g in self.channels}}]
        lo_n, hi_n = _v(A["exposure"]["count_per_shift"])
        k = int(rng.integers(lo_n, hi_n + 1))
        forced_ex = [f for f in forced if f != "pump_fault"]
        exps = [self._exposure(f, rng) for f in forced_ex] + [self._exposure("short", rng) for _ in range(k - len(forced_ex))]
        # sequential placement: each exposure takes its plateau + 30 min for recovery and spacing
        first, last = b0 + self._n(900), n - self._n(2700)
        margin = self._n(1800)
        while sum(e["applied"] + margin for e in exps) > last - first and len(exps) > max(1, len(forced_ex)):
            exps.pop()                                       # drop random exposures that do not fit
        order = rng.permutation(len(exps))
        free = (last - first) - sum(e["applied"] + margin for e in exps)
        cuts = np.sort(rng.integers(0, max(1, free), len(exps)))
        pos = first
        for c, j in zip(cuts, order):
            e = exps[j]
            e["start"] = int(first + c + (pos - first))
            pos += e["applied"] + margin
            events.append(e)
        if "pump_fault" in forced:
            dur = self._n(rng.uniform(*_v(A["pump_fault"])["duration_s"]))
            events.append({"kind": "pump_fault", "type": "pump_fault", "start": int(rng.integers(b0 + self._n(900), n - dur)),
                           "applied": dur, "targets": {}})
        if "sos_state" in self.states:
            for _ in range(int(_v(A["sos"]["count_per_shift"]))):
                dur = self._n(rng.uniform(*_v(A["sos"]["duration_s"])))
                events.append({"kind": "sos", "type": "sos", "start": int(rng.integers(0, n - dur)), "applied": dur,
                               "targets": {}})
        return events

    def gaps(self, n: int, rng) -> list:
        """(start, length) in samples, non-overlapping, after not_before_s."""
        G = _v(self.A["connection_gaps"])
        k = int(rng.integers(G["count_per_shift"][0], G["count_per_shift"][1] + 1))
        lo = self._n(G["not_before_s"])
        out = []
        while len(out) < k:
            ln = self._n(rng.uniform(*G["duration_s"]))
            s = int(rng.integers(lo, n - ln - 1))
            if all(s + ln + 1 < a or s > a + b + 1 for a, b in out):
                out.append((s, ln))
        return sorted(out)

    # 2-4. readings
    def readings(self, n: int, events: list, rng):
        A, dt = self.A, self.dt
        base = _v(A["clean_air_baseline"])
        t90, rf = _v(A["t90_s"]), float(_v(A["recovery_factor"]))
        noise = _v(A["measurement_noise_sd"])
        label = np.array(["none"] * n, dtype=object)
        gas_events = [e for e in events if e["targets"]]
        true = {}
        for g in self.channels:
            tgt = np.full(n, float(base[g]))
            applied = np.zeros(n, bool)
            for e in gas_events:
                if g in e["targets"]:
                    s, a = e["start"], e["applied"]
                    tgt[s:s + a] = e["targets"][g]
                    applied[s:s + a] = True
            tau_rise = t90[g] / np.log(10.0)
            k_rise, k_fall = 1 - np.exp(-dt / tau_rise), 1 - np.exp(-dt / (rf * tau_rise))
            c = np.empty(n)
            prev = float(base[g])
            for i in range(n):
                prev += (tgt[i] - prev) * (k_rise if applied[i] else k_fall)
                c[i] = prev
            true[g] = c
        # event label: from the start until every affected gas is back within half a resolution step
        for e in gas_events:
            s = e["start"]
            end = s + e["applied"]
            while end < n and any(abs(true[g][end] - base[g]) >= 0.5 * _v(self.channels[g]["resolution"])
                                  for g in e["targets"]):
                end += 1
            label[s:end] = e["kind"]
            e["end"] = end
        out = {}
        for g, ch in self.channels.items():
            x = true[g] + rng.normal(0.0, noise[g], n)
            out[g] = quantize_clip(x, _v(ch["resolution"]), _v(ch["range_min"]), _v(ch["range_max"]))
        return out, label

    # 5. derived columns
    def derived(self, vals: dict) -> dict:
        A, dt = self.A, self.dt
        sp, lim = _v(A["alarm_setpoints"]), _v(A["exposure_limits"])
        w = self._n(_v(A["stel_rule"])["window_s"])
        period = float(_v(A["twa_rule"])["period_s"])
        cols = {}
        for g, ch in self.channels.items():
            v, res, lo, hi = vals[g], _v(ch["resolution"]), _v(ch["range_min"]), _v(ch["range_max"])
            name, unit = ch["column"].split("_")[0], ch["column"].split("_", 1)[1]
            if g in TOXIC:
                csum = np.concatenate([[0.0], np.cumsum(v)])
                idx = np.arange(1, len(v) + 1)
                stel = (csum[idx] - csum[np.maximum(idx - w, 0)]) / w          # zero-filled before the shift
                twa = csum[idx] * dt / period
                stel_q, twa_q = quantize_clip(stel, res, lo, hi), quantize_clip(twa, res, lo, hi)
                cols[f"{name}_stel_{unit}"], cols[f"{name}_twa_{unit}"] = stel_q, twa_q
            low = (v <= sp[g]["low"]) if g == "o2" else (v >= sp[g]["low"])
            cols[f"{name}_alarm_low"] = low.astype(int)
            cols[f"{name}_alarm_high"] = (v >= sp[g]["high"]).astype(int)
            if g in TOXIC:
                cols[f"{name}_alarm_stel"] = (stel_q >= lim[g]["stel"]).astype(int)
                cols[f"{name}_alarm_twa"] = (twa_q >= lim[g]["twa"]).astype(int)
            cols[f"{name}_over_range"] = (v >= hi).astype(int)
        return cols

    # 6. device state
    def device_state(self, n: int, events: list, rng) -> dict:
        A, dt = self.A, self.dt
        st = {}
        B = _v(A["battery"])
        runtime_s = float(_v(self.spec["battery_runtime_h"])) * 3600
        st["battery_pct"] = np.floor(B["start_pct"] - 100 * np.arange(n) * dt / runtime_s).astype(int)
        S = _v(A["signal_strength"])
        lo, hi = S["range_dbm"]
        x = np.empty(n)
        x[0] = rng.uniform(*S["start_dbm"])
        steps = rng.normal(0, S["step_sd_db"], n)
        for i in range(1, n):
            x[i] = min(hi, max(lo, x[i - 1] + steps[i]))
        st["signal_strength_dbm"] = np.round(x).astype(int)
        if "gateway" in self.spec:
            L = _v(A["bridge_link"])
            link = np.array(["cellular"] * n, dtype=object)
            for _ in range(int(rng.integers(L["satellite_periods_per_shift"][0], L["satellite_periods_per_shift"][1] + 1))):
                ln = self._n(rng.uniform(*L["satellite_duration_s"]))
                s = int(rng.integers(0, n - ln))
                link[s:s + ln] = "satellite"
            st["bridge_link"] = link
        if "pump_state" in self.states:
            pump = np.array(["on"] * n, dtype=object)
            for e in events:
                if e["kind"] == "pump_fault":
                    pump[e["start"]:e["start"] + e["applied"]] = "fault"
            st["pump_state"], st["pump_alarm"] = pump, (pump == "fault").astype(int)
        if "sos_state" in self.states:
            sos = np.zeros(n, int)
            for e in events:
                if e["kind"] == "sos":
                    sos[e["start"]:e["start"] + e["applied"]] = 1
            st["sos_state"] = sos
        return st

    # all together
    def generate(self, duration_s: float, seed: int, forced=None) -> pd.DataFrame:
        """forced: coverage items for this shift; default = the coverage plan for (device, seed)."""
        if forced is None:
            forced = coverage_items(self.spec["device"], seed, self.A)
        # one stream per (seed, device): devices with the same seed do not share an event timeline
        rng = np.random.default_rng([seed, zlib.crc32(self.spec["device"].encode())])
        n = self._n(duration_s)
        events = self.schedule(n, rng, forced)
        vals, label = self.readings(n, events, rng)
        der = self.derived(vals)
        st = self.device_state(n, events, rng)
        gaps = self.gaps(n, rng)
        A = self.A
        t0 = pd.Timestamp(_v(A["shift"]["start_utc"]))
        ts = (t0 + pd.to_timedelta(np.arange(n) * self.dt, unit="s")).strftime("%Y-%m-%dT%H:%M:%SZ")
        ids = _v(A["identifiers"])
        df = pd.DataFrame({"timestamp": ts, "device_id": ids["device_id"].replace("<DEVICE>", self.spec["device"].upper())})
        if "gateway" in self.spec:
            df["bridge_id"] = ids["bridge_id"]
            df["bridge_link"] = st["bridge_link"]
        gap_before = np.zeros(n, int)
        keep = np.ones(n, bool)
        for s, ln in gaps:
            keep[s:s + ln] = False
            gap_before[s + ln] = int(round(ln * self.dt))
        df["gap_before_s"] = gap_before
        for g, ch in self.channels.items():
            res = _v(ch["resolution"])
            df[ch["column"]] = vals[g].astype(int) if res >= 1 else vals[g]
        for c, v in der.items():
            if "_stel_" in c or "_twa_" in c:
                df[c] = v.astype(int) if _v(self.channels[c.split("_")[0]]["resolution"]) >= 1 else v
        mode = np.array(["normal"] * n, dtype=object)
        for e in events:
            if e["kind"] == "bump_test":
                mode[e["start"]:e["end"]] = "bump_test"
        df["device_mode"] = mode
        for c in ("pump_state", "pump_alarm", "sos_state", "battery_pct", "signal_strength_dbm"):
            if c in st:
                df[c] = st[c]
        for c, v in der.items():
            if "_alarm_" in c or c.endswith("_over_range"):
                df[c] = v
        df["event"] = label
        self.events, self.gap_list = events, gaps
        return df[keep].reset_index(drop=True)

    def write_csv(self, df: pd.DataFrame, path: str) -> None:
        out = df.copy()
        for g, ch in self.channels.items():
            d = decimals(_v(ch["resolution"]))
            if not d:
                continue
            p = ch["column"].split("_")[0]
            for c in out.columns:
                if c == ch["column"] or c.startswith(p + "_stel_") or c.startswith(p + "_twa_"):
                    out[c] = out[c].map(lambda x, d=d: f"{x:.{d}f}")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        out.to_csv(path, index=False)
