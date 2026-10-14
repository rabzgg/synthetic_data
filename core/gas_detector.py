"""
gas_detector.py — rule-based generator for portable gas detectors, built from datasheet specs.

There is no real recording behind this engine. Its goal is data that obeys the datasheet (range,
resolution) and is consistent by rule (alarms, STEL/TWA, simultaneous bump test). It is not meant
to look like field data. Every number that is not in a datasheet comes from
configs/gas/assumptions.json, where it is marked ASSUMPTION.

Separate engine: SyntheticXDKGenerator is not touched. A device config selects it with
"engine": "gas_detector" (configs/gas/<device>/spec.json).

Pieces, applied in this order:
  1. event state machine: bump test at the start of the shift, 1-3 exposures, SOS (when the device
     has sos_state). It sets a target concentration per gas and sample.
  2. sensor response: first order towards the target, T90 while gas is applied, slower recovery.
  3. measurement noise.
  4. quantisation to the resolution, then clipping to the range: always LAST on every gas reading.
  5. derived columns from the final readings: STEL, TWA, alarm flags, over_range.
  6. discrete state columns: device_mode, pump_state, sos_state, gateway columns, event label.
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


class GasDetectorEngine:
    def __init__(self, spec: dict, assumptions: dict):
        if spec.get("engine") != "gas_detector":
            raise ValueError("spec is not a gas_detector config")
        self.spec, self.A = spec, assumptions
        self.channels = spec["channels"]
        self.dt = float(_v(assumptions["logging_interval_s"]))

    # 1. event state machine
    def schedule(self, n: int, rng) -> list:
        """Events as dicts with sample indices. Bump test first, exposures in equal slots after it,
        SOS anywhere (independent of the gas)."""
        A, dt = self.A, self.dt
        bump = A["bump_test"]
        b0 = int(round(_v(bump["start_after_s"]) / dt))
        events = [{"kind": "bump_test", "start": b0, "applied": int(round(_v(bump["gas_applied_s"]) / dt)),
                   "targets": {g: float(c) for g, c in _v(bump["gas_mix"]).items() if g in self.channels}}]
        ex = A["exposure"]
        lo_n, hi_n = _v(ex["count_per_shift"])
        k = int(rng.integers(lo_n, hi_n + 1))
        gases = [g for g in _v(ex["gases"]) if g in self.channels]
        first, last = b0 + int(900 / dt), n - int(2700 / dt)          # 15 min after the bump .. 45 min before the end
        slot = (last - first) // k
        p_lo, p_hi = _v(ex["plateau_s"])
        for i in range(k):
            g = gases[int(rng.integers(len(gases)))]
            pk_lo, pk_hi = _v(ex["peak"])[g]
            plateau = int(round(rng.uniform(p_lo, p_hi) / dt))
            start = first + i * slot + int(rng.integers(0, max(1, slot - plateau - int(1800 / dt))))
            events.append({"kind": f"exposure_{g}", "start": start, "applied": plateau,
                           "targets": {g: float(rng.uniform(pk_lo, pk_hi))}})
        if "sos_state" in self.spec.get("state_columns", {}):
            d_lo, d_hi = _v(A["sos"]["duration_s"])
            for _ in range(int(_v(A["sos"]["count_per_shift"]))):
                dur = int(round(rng.uniform(d_lo, d_hi) / dt))
                events.append({"kind": "sos", "start": int(rng.integers(0, n - dur)), "applied": dur, "targets": {}})
        return events

    # 2-4. readings
    def readings(self, n: int, events: list, rng):
        A, dt = self.A, self.dt
        base = _v(A["clean_air_baseline"])
        t90, rf = _v(A["t90_s"]), float(_v(A["recovery_factor"]))
        noise = _v(A["measurement_noise_sd"])
        label = np.array(["none"] * n, dtype=object)
        out = {}
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
        for g, ch in self.channels.items():
            x = true[g] + rng.normal(0.0, noise[g], n)
            out[g] = quantize_clip(x, _v(ch["resolution"]), _v(ch["range_min"]), _v(ch["range_max"]))
        return out, label

    # 5. derived columns
    def derived(self, vals: dict) -> dict:
        A, dt = self.A, self.dt
        sp, rule = _v(A["alarm_setpoints"]), _v(A["alarm_rule"])
        lim = _v(A["exposure_limits"])
        w = int(round(_v(A["stel_rule"])["window_s"] / dt))
        period = float(_v(A["twa_rule"])["period_s"])
        cols = {}
        for g, ch in self.channels.items():
            v, res, lo, hi = vals[g], _v(ch["resolution"]), _v(ch["range_min"]), _v(ch["range_max"])
            name = ch["column"].split("_")[0]
            if g in TOXIC:
                csum = np.concatenate([[0.0], np.cumsum(v)])
                idx = np.arange(1, len(v) + 1)
                stel = (csum[idx] - csum[np.maximum(idx - w, 0)]) / w          # zero-filled before the shift
                twa = csum[idx] * dt / period
                stel_q, twa_q = quantize_clip(stel, res, lo, hi), quantize_clip(twa, res, lo, hi)
                cols[f"{name}_stel_{ch['column'].split('_', 1)[1]}"] = stel_q
                cols[f"{name}_twa_{ch['column'].split('_', 1)[1]}"] = twa_q
            low = (v <= sp[g]["low"]) if g == "o2" else (v >= sp[g]["low"])
            cols[f"{name}_alarm_low"] = low.astype(int)
            cols[f"{name}_alarm_high"] = (v >= sp[g]["high"]).astype(int)
            if g in TOXIC:
                cols[f"{name}_alarm_stel"] = (stel_q >= lim[g]["stel"]).astype(int)
                cols[f"{name}_alarm_twa"] = (twa_q >= lim[g]["twa"]).astype(int)
            cols[f"{name}_over_range"] = (v >= hi).astype(int)
        return cols

    # all together
    def generate(self, duration_s: float, seed: int) -> pd.DataFrame:
        # one stream per (seed, device): devices with the same seed do not share an event timeline
        rng = np.random.default_rng([seed, zlib.crc32(self.spec["device"].encode())])
        n = int(round(duration_s / self.dt))
        events = self.schedule(n, rng)
        vals, label = self.readings(n, events, rng)
        der = self.derived(vals)
        A = self.A
        t0 = pd.Timestamp(_v(A["shift"]["start_utc"]))
        ts = (t0 + pd.to_timedelta(np.arange(n) * self.dt, unit="s")).strftime("%Y-%m-%dT%H:%M:%SZ")
        ids = _v(A["identifiers"])
        df = pd.DataFrame({"timestamp": ts, "device_id": ids["device_id"].replace("<DEVICE>", self.spec["device"].upper())})
        if "gateway" in self.spec:
            df["bridge_id"] = ids["bridge_id"]
            df["link"] = "cellular"
        for g, ch in self.channels.items():
            res = _v(ch["resolution"])
            df[ch["column"]] = vals[g].astype(int) if res >= 1 else vals[g]
        for c, v in der.items():
            if "_stel_" in c or "_twa_" in c:
                g = c.split("_")[0]
                df[c] = v.astype(int) if _v(self.channels[g]["resolution"]) >= 1 else v
        mode = np.array(["normal"] * n, dtype=object)
        for e in events:
            if e["kind"] == "bump_test":
                mode[e["start"]:e["end"]] = "bump_test"
        df["device_mode"] = mode
        if "pump_state" in self.spec.get("state_columns", {}):
            df["pump_state"] = "on"
        if "sos_state" in self.spec.get("state_columns", {}):
            sos = np.zeros(n, int)
            for e in events:
                if e["kind"] == "sos":
                    sos[e["start"]:e["start"] + e["applied"]] = 1
            df["sos_state"] = sos
        for c, v in der.items():
            if "_alarm_" in c or c.endswith("_over_range"):
                df[c] = v
        df["event"] = label
        self.events = events
        return df

    def write_csv(self, df: pd.DataFrame, path: str) -> None:
        fmt = {}
        for g, ch in self.channels.items():
            d = decimals(_v(ch["resolution"]))
            if d:
                for c in df.columns:
                    if c == ch["column"] or c.startswith(ch["column"].split("_")[0] + "_stel_") or \
                            c.startswith(ch["column"].split("_")[0] + "_twa_"):
                        fmt[c] = d
        out = df.copy()
        for c, d in fmt.items():
            out[c] = out[c].map(lambda x, d=d: f"{x:.{d}f}")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        out.to_csv(path, index=False)
