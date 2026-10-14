"""
gas_gate.py — rule gate for datasheet-based gas detector data.

Checks a generated CSV against its datasheet spec (configs/gas/<device>/spec.json) and the marked
assumptions (configs/gas/assumptions.json). It does not import the generator: every rule is
recomputed here from the CSV, so a generator bug cannot hide behind shared code.

Checks (per file):
  columns           every expected column is present (gas columns carry their unit in the name)
  timestamps        ISO 8601 UTC, starting at the shift start; every step is the logging interval,
                    or the interval + gap_before_s on a row that announces a connection gap. A
                    missing row without that announcement fails.
  connection_gaps   announced gaps: count and duration within the assumed ranges, none in the bump test
  resolution        every gas, STEL and TWA value is a multiple of the channel resolution
  range             every gas value within [range_min, range_max]
  alarm_setpoints   alarm_low / alarm_high == value vs setpoint (O2 low: value <= setpoint)
  over_range        over_range == value >= range_max
  stel_formula      STEL == mean of the last 15 min (zero-filled before the shift) within half a
                    resolution step; where the window holds a gap, STEL lies within the bounds the
                    missing samples allow (range_min .. range_max)
  twa_formula       TWA == accumulated dose / 8 h: exact up to the first gap, then per gap-free
                    segment relative to its first row; across a gap within the bounds of the missing samples
  stel_twa_alarms   alarm_stel / alarm_twa == STEL / TWA vs limit
  bump_simultaneous every gas of the bump mix starts to change at the same sample, the first bump-test sample
  alarm_cause       every alarm has a cause: an event on that gas now (instant alarms), in the last
                    15 min (STEL) or earlier in the shift (TWA), by timestamp
  battery           battery_pct == floor(100 - 100 * elapsed / datasheet runtime)
  signal            signal_strength_dbm integer, within the assumed range
  pump              pump_alarm == (pump_state == fault)        (devices with a pump)
  bridge_link       satellite periods within the assumed count  (G7x Bridge)
  state_values      state, alarm and gateway columns hold only allowed values; ids constant
  scenario_content  bump test in the first 15 min, 1-3 exposures, SOS count, and the coverage-plan
                    items of this seed visible in the data

Usage: python3 validation/gas_gate.py --device blackline_g7c [--seed 42] [--csv path]
       python3 validation/gas_gate.py --all [--json data/gas/gate_report.json] [--readme data/gas/README.md]
"""
import argparse
import glob
import json
import os
import re
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from validation.physics_gate import Check, GateReport

CONFIGS = os.path.join(ROOT, "configs", "gas")
DATA = os.path.join(ROOT, "data", "gas")
TOXIC = ("co", "h2s")
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def val(e):
    return e["value"] if isinstance(e, dict) and "value" in e else e


def load(device):
    with open(os.path.join(CONFIGS, device, "spec.json")) as fh:
        spec = json.load(fh)
    with open(os.path.join(CONFIGS, "assumptions.json")) as fh:
        A = json.load(fh)
    return spec, A


def runs(mask):
    """(start, end) of contiguous True runs."""
    m = np.concatenate([[False], np.asarray(mask, bool), [False]])
    d = np.diff(m.astype(int))
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))


def prefix(ch):
    return ch["column"].split("_")[0]


def unit_suffix(ch):
    return ch["column"].split("_", 1)[1]


def plan_items(device, seed, A):
    """Coverage-plan items expected on this (device, seed), read from assumptions.json."""
    plan = val(A["coverage_plan"])
    items = plan["items"].get(device, plan["items"]["default"])
    off = 0 if len(items) >= len(plan["seeds"]) else 1
    return [it for k, it in enumerate(items) if k + off < len(plan["seeds"]) and plan["seeds"][k + off] == seed]


def expected_columns(spec):
    cols = ["timestamp", "device_id"] + (spec["gateway"]["columns"] if "gateway" in spec else []) + ["gap_before_s"]
    for g, ch in spec["channels"].items():
        p = prefix(ch)
        cols += [ch["column"], f"{p}_alarm_low", f"{p}_alarm_high", f"{p}_over_range"]
        if g in TOXIC:
            cols += [f"{p}_stel_{unit_suffix(ch)}", f"{p}_twa_{unit_suffix(ch)}", f"{p}_alarm_stel", f"{p}_alarm_twa"]
    st = spec.get("state_columns", {})
    cols += ["device_mode"] + (["pump_state", "pump_alarm"] if "pump_state" in st else []) + \
            (["sos_state"] if "sos_state" in st else []) + ["battery_pct", "signal_strength_dbm", "event"]
    return cols


def inventory(d: pd.DataFrame) -> dict:
    """What happens in a file, read from the data only."""
    ev = d["event"].astype(str).to_numpy()
    exp = [d["event"].iloc[s] for s, _ in runs(np.char.startswith(ev.astype(str), "exposure_"))]

    def flagged(suffix):
        return int(sum(d[c].sum() for c in d.columns if c.endswith(suffix)))
    return {"bump_tests": len(runs(d["device_mode"].to_numpy() == "bump_test")),
            "exposures": ", ".join(e.replace("exposure_", "") for e in exp),
            "stel_alarm_samples": flagged("_alarm_stel"), "twa_alarm_samples": flagged("_alarm_twa"),
            "over_range_samples": flagged("_over_range"),
            "voc_exposures": sum(e == "exposure_voc" for e in exp),
            "pump_faults": len(runs(d["pump_state"].to_numpy() == "fault")) if "pump_state" in d else None,
            "sos": len(runs(d["sos_state"].to_numpy() == 1)) if "sos_state" in d else None,
            "gaps": int((d["gap_before_s"] > 0).sum()),
            "satellite_periods": len(runs(d["bridge_link"].to_numpy() == "satellite")) if "bridge_link" in d else None,
            "battery_end_pct": int(d["battery_pct"].iloc[-1])}


def check_gas_file(csv_path, device, seed=None, spec=None, assumptions=None, items=None) -> GateReport:
    """seed: also check the coverage-plan items of that seed; items: check these items instead (UI scenarios).
    spec / assumptions: override configs (tests)."""
    spec_f, A_f = load(device)
    spec, A = spec or spec_f, assumptions or A_f
    d = pd.read_csv(csv_path)
    rep = GateReport()
    ch_all = spec["channels"]
    n = len(d)

    missing = [c for c in expected_columns(spec) if c not in d.columns]
    rep.add(Check("columns", "all", len(missing), "= 0 missing columns", not missing,
                  ", ".join(missing) if missing else f"{len(d.columns)} columns"))
    if missing:
        return rep

    # timestamps and announced gaps
    dt = float(val(A["logging_interval_s"]))
    fmt_ok = bool(d["timestamp"].astype(str).map(lambda s: bool(ISO_UTC.match(s))).all())
    t = pd.to_datetime(d["timestamp"], utc=True)
    tsec = (t - pd.Timestamp(val(A["shift"]["start_utc"]))).dt.total_seconds().to_numpy()
    steps = np.diff(tsec)
    gb = d["gap_before_s"].to_numpy(float)
    wrong = steps != dt + gb[1:]
    bad = int(np.sum(wrong)) + int(gb[0] != 0)
    rep.add(Check("timestamps", "all", bad, f"= 0 steps != {dt:g} s + announced gap; ISO 8601 UTC from the shift start",
                  fmt_ok and bad == 0 and tsec[0] == 0,
                  f"{n} rows" + (f"; unexplained steps {sorted(set(steps[wrong].tolist()))} s" if bad else "")))
    G = val(A["connection_gaps"])
    gaps = gb[gb > 0]
    in_bump = int(np.sum((gb > 0) & (d["device_mode"].to_numpy() == "bump_test")))
    g_ok = (G["count_per_shift"][0] <= len(gaps) <= G["count_per_shift"][1] and in_bump == 0 and
            all(G["duration_s"][0] - dt <= x <= G["duration_s"][1] + dt for x in gaps))
    rep.add(Check("connection_gaps", "all", len(gaps), f"{G['count_per_shift'][0]}-{G['count_per_shift'][1]} gaps of "
                  f"{G['duration_s'][0]}-{G['duration_s'][1]} s, none in the bump test", g_ok,
                  "gaps " + ", ".join(f"{x:g} s" for x in gaps)))
    k_idx = np.round(tsec / dt).astype(int)            # sample index on the device clock (gaps included)
    seg_start = np.concatenate([[True], gb[1:] > 0])

    sp, lim = val(A["alarm_setpoints"]), val(A["exposure_limits"])
    w = int(round(val(A["stel_rule"])["window_s"] / dt))
    twa_p = float(val(A["twa_rule"])["period_s"])
    ev = d["event"].astype(str).to_numpy()
    mix = val(A["bump_test"]["gas_mix"])
    for g, ch in ch_all.items():
        p, res = prefix(ch), float(val(ch["resolution"]))
        lo, hi = float(val(ch["range_min"])), float(val(ch["range_max"]))
        v = d[ch["column"]].to_numpy(float)
        value_cols = [ch["column"]] + ([f"{p}_stel_{unit_suffix(ch)}", f"{p}_twa_{unit_suffix(ch)}"] if g in TOXIC else [])
        off = {c: int(np.sum(np.abs(d[c].to_numpy(float) / res - np.round(d[c].to_numpy(float) / res)) > 1e-6))
               for c in value_cols}
        rep.add(Check("resolution", g, sum(off.values()), f"= 0 values off the {res:g} grid", sum(off.values()) == 0,
                      ", ".join(f"{c}: {k}" for c, k in off.items())))
        out = int(np.sum((v < lo) | (v > hi)))
        rep.add(Check("range", g, out, f"= 0 values outside [{lo:g}, {hi:g}]", out == 0, f"min {v.min():g}, max {v.max():g}"))
        low_exp = (v <= sp[g]["low"]) if g == "o2" else (v >= sp[g]["low"])
        high_exp = v >= sp[g]["high"]
        mism = int(np.sum(d[f"{p}_alarm_low"].to_numpy() != low_exp) + np.sum(d[f"{p}_alarm_high"].to_numpy() != high_exp))
        rep.add(Check("alarm_setpoints", g, mism,
                      f"= 0 mismatches (low {'<=' if g == 'o2' else '>='} {sp[g]['low']:g}, high >= {sp[g]['high']:g})",
                      mism == 0, f"low alarms {int(low_exp.sum())}, high alarms {int(high_exp.sum())}"))
        orng = int(np.sum(d[f"{p}_over_range"].to_numpy() != (v >= hi)))
        rep.add(Check("over_range", g, orng, f"= 0 mismatches (value >= {hi:g})", orng == 0,
                      f"over-range samples {int((v >= hi).sum())}"))

        if g in TOXIC:
            stel = d[f"{p}_stel_{unit_suffix(ch)}"].to_numpy(float)
            twa = d[f"{p}_twa_{unit_suffix(ch)}"].to_numpy(float)
            # STEL on the device clock: the known samples of the window, plus bounds for the missing ones
            full = np.zeros(k_idx[-1] + 1)
            known = np.zeros(k_idx[-1] + 1)
            full[k_idx], known[k_idx] = v, 1.0
            ksum = np.convolve(full, np.ones(w))[:len(full)][k_idx]
            kmiss = np.minimum(k_idx + 1, w) - np.convolve(known, np.ones(w))[:len(full)][k_idx]
            s_lo, s_hi = (ksum + lo * kmiss) / w, (ksum + hi * kmiss) / w
            tol = res / 2 + 1e-9
            s_bad = int(np.sum((stel < s_lo - tol) | (stel > s_hi + tol)))
            exact = np.round(kmiss) == 0
            e_s = float(np.max(np.abs(stel[exact] - s_lo[exact]))) if exact.any() else 0.0
            rep.add(Check("stel_formula", g, s_bad, f"= 0 STEL values off the 15-min mean (±{res / 2:g}; bounded across gaps)",
                          s_bad == 0, f"max error where exact {e_s:.4g}; {int((~exact).sum())} rows bounded; peak {stel.max():g}"))
            # TWA: exact up to the first gap; then per segment relative to its first row; bounded across each gap
            seg_id = np.cumsum(seg_start) - 1
            t_bad = 0
            for sid in range(seg_id.max() + 1):
                rows = np.where(seg_id == sid)[0]
                inc = np.cumsum(v[rows]) * dt / twa_p
                if sid == 0:
                    t_bad += int(np.sum(np.abs(twa[rows] - inc) > res / 2 + 1e-9))
                    continue
                t_bad += int(np.sum(np.abs(twa[rows] - (twa[rows[0]] + inc - inc[0])) > res + 1e-9))
                gap_n = int(round(gb[rows[0]] / dt))
                jump = twa[rows[0]] - twa[rows[0] - 1]
                t_bad += int(not ((v[rows[0]] + lo * gap_n) * dt / twa_p - res - 1e-9 <= jump <=
                                  (v[rows[0]] + hi * gap_n) * dt / twa_p + res + 1e-9))
            rep.add(Check("twa_formula", g, t_bad, f"= 0 TWA values off dose / 8 h (±{res / 2:g} before the first gap, "
                          f"±{res:g} per segment after; bounded across gaps)", t_bad == 0, f"end-of-shift TWA {twa[-1]:g}"))
            m2 = int(np.sum(d[f"{p}_alarm_stel"].to_numpy() != (stel >= lim[g]["stel"])) +
                     np.sum(d[f"{p}_alarm_twa"].to_numpy() != (twa >= lim[g]["twa"])))
            rep.add(Check("stel_twa_alarms", g, m2, f"= 0 mismatches (STEL >= {lim[g]['stel']:g}, TWA >= {lim[g]['twa']:g})",
                          m2 == 0, f"STEL alarm samples {int((stel >= lim[g]['stel']).sum())}, "
                                   f"TWA alarm samples {int((twa >= lim[g]['twa']).sum())}"))

        # alarm cause, by timestamp
        on_gas = (ev == f"exposure_{g}") | ((ev == "bump_test") & (g in mix))
        inst = (d[f"{p}_alarm_low"].to_numpy() == 1) | (d[f"{p}_alarm_high"].to_numpy() == 1) | \
               (d[f"{p}_over_range"].to_numpy() == 1)
        no_cause = int(np.sum(inst & ~on_gas))
        if g in TOXIC:
            ev_t = np.sort(tsec[on_gas])
            # latest event row at or before each row (by time)
            j = np.searchsorted(ev_t, tsec, side="right") - 1
            last_ev = np.where(j >= 0, ev_t[np.maximum(j, 0)] if len(ev_t) else np.inf, -np.inf)
            recent = (tsec - last_ev) < w * dt
            ever = j >= 0
            no_cause += int(np.sum((d[f"{p}_alarm_stel"].to_numpy() == 1) & ~recent))
            no_cause += int(np.sum((d[f"{p}_alarm_twa"].to_numpy() == 1) & ~ever))
        rep.add(Check("alarm_cause", g, no_cause, "= 0 alarm samples without an event on this gas", no_cause == 0,
                      f"instant alarm samples {int(inst.sum())}"))

    # bump test
    base = val(A["clean_air_baseline"])
    bmix = {g: c for g, c in mix.items() if g in ch_all}
    bumps = runs(d["device_mode"].to_numpy() == "bump_test")
    notes, ok = [], bool(bumps)
    for s, e in bumps:
        onset = {}
        for g, c in bmix.items():
            v, res = d[ch_all[g]["column"]].to_numpy(float), float(val(ch_all[g]["resolution"]))
            band = max(2 * res, 0.05 * abs(c - base[g]))
            moved = np.where(np.sign(c - base[g]) * (v[max(0, s - 30):e] - base[g]) > band)[0]
            onset[g] = int(moved[0]) + max(0, s - 30) if len(moved) else None
        same = len(set(onset.values())) == 1 and onset[next(iter(onset))] == s
        ok &= same
        notes.append(f"bump at row {s}: first change " + ", ".join(f"{g}@{i}" for g, i in onset.items()))
    rep.add(Check("bump_simultaneous", "all", len(bumps), "every bump: all mix gases change first at its first sample",
                  ok, "; ".join(notes) or "no bump test found"))

    # device state
    runtime = float(val(spec["battery_runtime_h"])) * 3600
    B = val(A["battery"])
    exp_bat = np.floor(B["start_pct"] - 100 * tsec / runtime).astype(int)
    b_bad = int(np.sum(d["battery_pct"].to_numpy() != exp_bat))
    rep.add(Check("battery", "all", b_bad, f"= 0 rows != floor({B['start_pct']} - 100 * t / {runtime / 3600:g} h)",
                  b_bad == 0, f"{int(d['battery_pct'].iloc[0])} -> {int(d['battery_pct'].iloc[-1])} %"))
    S = val(A["signal_strength"])
    sig = d["signal_strength_dbm"].to_numpy(float)
    s_bad = int(np.sum((sig < S["range_dbm"][0]) | (sig > S["range_dbm"][1]) | (sig != np.round(sig))))
    rep.add(Check("signal", "all", s_bad, f"= 0 values outside {S['range_dbm']} dBm or not integer", s_bad == 0,
                  f"{sig.min():g} .. {sig.max():g} dBm"))
    if "pump_state" in d:
        p_bad = int(np.sum(d["pump_alarm"].to_numpy() != (d["pump_state"].to_numpy() == "fault")))
        rep.add(Check("pump", "all", p_bad, "= 0 rows where pump_alarm != (pump_state == fault)", p_bad == 0,
                      f"fault periods {len(runs(d['pump_state'].to_numpy() == 'fault'))}"))
    if "bridge_link" in d:
        L = val(A["bridge_link"])
        n_sat = len(runs(d["bridge_link"].to_numpy() == "satellite"))
        lo_s, hi_s = L["satellite_periods_per_shift"]
        rep.add(Check("bridge_link", "all", n_sat, f"{lo_s}-{hi_s} satellite periods", lo_s <= n_sat <= hi_s))

    allowed = {"device_mode": set(val(A["state_values"])["device_mode"])}
    for c in ("pump_state", "sos_state"):
        if c in d:
            allowed[c] = set(map(str, val(A["state_values"])[c]))
    if "bridge_link" in d:
        allowed["bridge_link"] = set(val(spec["gateway"]["link_values"]))
    for c in d.columns:
        if "_alarm" in c or c.endswith("_over_range"):
            allowed[c] = {"0", "1"}
    bad = {c: sorted(set(d[c].astype(str)) - a) for c, a in allowed.items() if set(d[c].astype(str)) - a}
    const = {c: d[c].nunique() for c in ("device_id", "bridge_id") if c in d.columns}
    rep.add(Check("state_values", "all", len(bad), "= 0 columns with values outside the allowed set; ids constant",
                  not bad and all(k == 1 for k in const.values()), str(bad) if bad else f"{len(allowed)} columns checked"))

    # scenario content and coverage-plan items
    inv = inventory(d)
    ex_lo, ex_hi = val(A["exposure"]["count_per_shift"])
    n_exp = len([x for x in inv["exposures"].split(", ") if x])
    first_bump_s = float(tsec[bumps[0][0]]) if bumps else None
    cond = {"bump in first 15 min": first_bump_s is not None and first_bump_s <= 900,
            f"{ex_lo}-{ex_hi} exposures": ex_lo <= n_exp <= ex_hi}
    if "sos_state" in d:
        cond["SOS count"] = inv["sos"] == int(val(A["sos"]["count_per_shift"]))
    seen = {"sustained_stel": inv["stel_alarm_samples"] > 0, "prolonged_twa": inv["twa_alarm_samples"] > 0,
            "over_range": inv["over_range_samples"] > 0, "voc": inv["voc_exposures"] > 0,
            "pump_fault": bool(inv["pump_faults"])}
    if items is None:
        items = plan_items(device, seed, A) if seed is not None else []
    for it in items:
        cond[f"coverage item {it}"] = seen[it]
    rep.add(Check("scenario_content", "all", n_exp, ", ".join(cond), all(cond.values()),
                  f"first bump at {first_bump_s:g} s; exposures {n_exp}" if first_bump_s is not None else "no bump test"))
    return rep


def devices():
    return sorted(x for x in os.listdir(CONFIGS) if os.path.isfile(os.path.join(CONFIGS, x, "spec.json")))


def files():
    """(device, seed, path) for every data/gas/<device>_shift_seed<seed>.csv."""
    out = []
    for p in sorted(glob.glob(os.path.join(DATA, "*_shift_seed*.csv"))):
        m = re.match(r"(.+)_shift_seed(\d+)\.csv$", os.path.basename(p))
        if m and m.group(1) in devices():
            out.append((m.group(1), int(m.group(2)), p))
    return out


EVENT_COLS = [("bump_tests", "bump"), ("exposures", "exposures (gas)"), ("stel_alarm_samples", "STEL alarm"),
              ("twa_alarm_samples", "TWA alarm"), ("over_range_samples", "over-range"), ("voc_exposures", "VOC exp."),
              ("pump_faults", "pump fault"), ("sos", "SOS"), ("gaps", "gaps"), ("satellite_periods", "satellite"),
              ("battery_end_pct", "battery end %")]
COVER = [("STEL alarm", "stel_alarm_samples", None), ("TWA alarm", "twa_alarm_samples", None),
         ("over-range", "over_range_samples", None), ("VOC exposure", "voc_exposures", "msa_altair_io6"),
         ("pump fault", "pump_faults", "msa_altair_io6"), ("SOS", "sos", "blackline_g8")]


def write_readme(results: list, path: str):
    """data/gas/README.md: what the data is, gate result per seed and device, event table, ASSUMPTIONs."""
    with open(os.path.join(CONFIGS, "assumptions.json")) as fh:
        A = json.load(fh)
    devs = sorted({r["device"] for r in results})
    seeds = sorted({r["seed"] for r in results})
    by = {(r["device"], r["seed"]): r for r in results}
    n_pass = sum(r["report"]["passed"] for r in results)
    L = ["# Gas detector data (datasheet-based)", "",
         "**What this is:** synthetic data that **obeys the datasheets** (range, resolution, battery runtime) and is "
         "**consistent by rule** (alarms, STEL/TWA, simultaneous bump test, announced connection gaps, timestamps).", "",
         "**What this is not:** it is **not** made to look like field data. No real recording of these devices was "
         "available, so nothing here was compared with, or fitted to, real readings. Noise, event shapes, timings, "
         "battery drain, signal strength and gaps are assumptions (listed below), not measurements.", "",
         "- Generator: `core/gas_detector.py` (`python3 cli/generate_gas.py --all`): one 8-h shift per device and seed, "
         f"seeds {', '.join(map(str, seeds))}.",
         "- Rule gate: `validation/gas_gate.py` (`python3 validation/gas_gate.py --all --json data/gas/gate_report.json "
         "--readme data/gas/README.md`). It recomputes every rule from the CSV and shares no code with the generator.",
         "- Specs: `configs/gas/<device>/spec.json`: datasheet values, each with `{value, unit, source}`.",
         "- Assumptions: `configs/gas/assumptions.json`: everything else, each marked `ASSUMPTION` with a reason.", "",
         "## Gate result per device and seed", "",
         f"**{n_pass} of {len(results)} files pass every check.** Full detail per check: `gate_report.json`.", "",
         "| device | " + " | ".join(f"seed {s}" for s in seeds) + " |", "|---|" + "---|" * len(seeds)]
    for dv in devs:
        cells = []
        for s in seeds:
            r = by.get((dv, s))
            if not r:
                cells.append("—")
            elif r["report"]["passed"]:
                cells.append("PASS")
            else:
                cells.append("**FAIL** (" + ", ".join(sorted({f"{c['sensor']}/{c['name']}" for c in r["report"]["checks"]
                                                              if not c["passed"]})) + ")")
        L.append(f"| {dv} | " + " | ".join(cells) + " |")
    L += ["", "Checks on every file: columns, timestamps (steps of 10 s, or an announced gap), connection_gaps, "
          "resolution, range, alarm_setpoints, over_range, stel_formula, twa_formula, stel_twa_alarms, "
          "bump_simultaneous, alarm_cause, battery, signal, state_values, scenario_content (incl. the coverage-plan "
          "items of that seed); pump (io6) and bridge_link (G7x).", "",
          "## Events per seed", "",
          "Read from the data by the gate (`inventory`). STEL / TWA / over-range: number of samples with that flag.", "",
          "| device | seed | " + " | ".join(h for _, h in EVENT_COLS) + " |", "|---|---|" + "---|" * len(EVENT_COLS)]
    for dv in devs:
        for s in seeds:
            r = by.get((dv, s))
            if r:
                L.append(f"| {dv} | {s} | " + " | ".join("—" if r["inventory"][k] is None else str(r["inventory"][k])
                                                         for k, _ in EVENT_COLS) + " |")
    L += ["", "## Coverage of the 5-seed set", "",
          "Each item has to appear at least once for every device it applies to. It is placed by the coverage plan "
          "(`coverage_plan` in `assumptions.json`), not left to chance; random exposures are always short.", "",
          "| item | applies to | seeds where it appears |", "|---|---|---|"]
    for name, key, only in COVER:
        parts = []
        for dv in ([only] if only else devs):
            ss = [str(s) for s in seeds if (dv, s) in by and (by[(dv, s)]["inventory"][key] or 0) > 0]
            parts.append(f"{dv}: {', '.join(ss) if ss else '**none**'}")
        L.append(f"| {name} | {only or 'all devices'} | " + "; ".join(parts) + " |")
    L += ["", "## Columns", "",
          "`timestamp` (ISO 8601 UTC), `device_id`, `bridge_id`/`bridge_link` (G7x), `gap_before_s` (seconds without "
          "rows before this row; 0 normally), gas readings with the unit in the name (`lel_pct_lel`, `o2_pct_vol`, "
          "`co_ppm`, `h2s_ppm`, `voc_ppm`), `co_/h2s_stel_ppm` and `_twa_ppm`, `device_mode`, `pump_state`/`pump_alarm` "
          "(io6), `sos_state` (G8), `battery_pct`, `signal_strength_dbm`, alarm flags (`<gas>_alarm_low/high/stel/twa`, "
          "`<gas>_over_range`; 0/1), and `event`, a ground-truth label written by the generator, not a device field.", "",
          "## Datasheet sources", "", "| device | source | battery runtime |", "|---|---|---|"]
    for dv in devs:
        spec, _ = load(dv)
        b = spec["battery_runtime_h"]
        L.append(f"| {spec['model']} (`{dv}`) | {spec['source_document']} | {b['value']} h ({b.get('assumption', b['source'])}) |")
    L += ["", "- `msa_altair_io6`: LEL/O2/CO/H2S and the pump are taken from the io4 spec sheet: **ASSUMPTION: same "
          "sensors as io4** (io6 sensor table not found). VOC (PID) 0-4000 ppm, resolution 0.1: **ASSUMPTION: borrowed "
          "from Blackline PID (G7c R28); io6 PID table not found**. Battery: **ASSUMPTION: same as io4**.",
          "- G7x and G8 gas ranges equal the G7c values; the reviewer checked this against the G7x and G8 datasheets.", "",
          "## Assumptions (not in the datasheets)", "",
          "Every entry is marked `ASSUMPTION` in `configs/gas/assumptions.json`.", "",
          "| assumption | value | unit | reason |", "|---|---|---|---|"]

    def cell(x):
        return str(x).replace("|", "\\|")

    def walk(pre, node):
        for k, e in node.items():
            if k.startswith("_"):
                continue
            if isinstance(e, dict) and e.get("status") == "ASSUMPTION":
                L.append(f"| `{pre}{k}` | `{cell(json.dumps(e['value']))}` | {cell(e['unit'])} | {cell(e['reason'])} |")
            elif isinstance(e, dict):
                walk(f"{pre}{k}.", e)
    walk("", A)
    with open(path, "w") as fh:
        fh.write("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", choices=devices())
    ap.add_argument("--all", action="store_true", help="every data/gas/<device>_shift_seed<seed>.csv")
    ap.add_argument("--csv", default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--readme", default=None)
    args = ap.parse_args()
    if args.all:
        todo = files()
    elif args.device:
        seed = args.seed if args.seed is not None else 42
        todo = [(args.device, seed, args.csv or os.path.join(DATA, f"{args.device}_shift_seed{seed}.csv"))]
    else:
        ap.error("give --device or --all")
    results, ok = [], True
    for dev, seed, csv in todo:
        rep = check_gas_file(csv, dev, seed)
        spec, _ = load(dev)
        print(f"== {dev} seed {seed}\n{rep.format().replace('PHYSICS GATE', 'GAS RULE GATE')}\n")
        results.append({"device": dev, "seed": seed, "csv": os.path.relpath(csv, ROOT), "model": spec["model"],
                        "inventory": inventory(pd.read_csv(csv)), "report": rep.to_dict()})
        ok &= rep.passed
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(results, fh, indent=1, default=float)
    if args.readme:
        write_readme(results, args.readme)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
