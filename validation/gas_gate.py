"""
gas_gate.py — rule gate for datasheet-based gas detector data.

Checks a generated CSV against its datasheet spec (configs/gas/<device>/spec.json) and the marked
assumptions (configs/gas/assumptions.json). It does not import the generator: every rule is
recomputed here from the CSV, so a generator bug cannot hide behind shared code.

Checks (per device):
  columns           every expected column is present (gas columns carry their unit in the name)
  timestamps        ISO 8601 UTC, strictly increasing, constant logging interval
  resolution        every gas, STEL and TWA value is a multiple of the channel resolution
  range             every gas value within [range_min, range_max]
  alarm_setpoints   alarm_low / alarm_high == value vs setpoint (O2 low: value <= setpoint)
  over_range        over_range == value >= range_max
  stel_formula      STEL == mean of the last 15 min (zero-filled before the shift), within half a resolution step
  twa_formula       TWA == accumulated dose / 8 h, within half a resolution step
  stel_twa_alarms   alarm_stel / alarm_twa == STEL / TWA vs limit
  bump_simultaneous every gas of the bump mix starts to change at the same sample, the first bump-test sample
  alarm_cause       every alarm has a cause: an event on that gas now (instant alarms), in the last
                    15 min (STEL) or earlier in the shift (TWA)
  state_values      state, alarm and gateway columns hold only allowed values
  scenario_content  bump test in the first 15 min, 1-3 exposures, SOS count (devices with sos_state)

Usage: python3 validation/gas_gate.py --device blackline_g7c [--csv path]
       python3 validation/gas_gate.py --all [--json data/gas/gate_report.json] [--readme data/gas/README.md]
"""
import argparse
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


def expected_columns(spec):
    cols = ["timestamp", "device_id"]
    if "gateway" in spec:
        cols += spec["gateway"]["columns"]
    for g, ch in spec["channels"].items():
        p = prefix(ch)
        cols += [ch["column"], f"{p}_alarm_low", f"{p}_alarm_high", f"{p}_over_range"]
        if g in TOXIC:
            cols += [f"{p}_stel_{unit_suffix(ch)}", f"{p}_twa_{unit_suffix(ch)}", f"{p}_alarm_stel", f"{p}_alarm_twa"]
    cols += ["device_mode"] + list(spec.get("state_columns", {})) + ["event"]
    return cols


def check_gas_file(csv_path, device, spec=None, assumptions=None) -> GateReport:
    """spec / assumptions: override the files in configs/gas (tests)."""
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

    # timestamps
    dt = float(val(A["logging_interval_s"]))
    fmt_ok = d["timestamp"].astype(str).map(lambda s: bool(ISO_UTC.match(s))).all()
    t = pd.to_datetime(d["timestamp"], utc=True)
    steps = t.diff().dt.total_seconds().to_numpy()[1:]
    bad = int(np.sum(steps != dt))
    rep.add(Check("timestamps", "all", bad, f"= 0 steps != {dt:g} s; ISO 8601 UTC", fmt_ok and bad == 0,
                  f"{n} rows, steps {np.unique(steps).tolist()}"))

    sp, lim = val(A["alarm_setpoints"]), val(A["exposure_limits"])
    stel_w = int(round(val(A["stel_rule"])["window_s"] / dt))
    twa_p = float(val(A["twa_rule"])["period_s"])
    ev = d["event"].astype(str).to_numpy()
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
        rep.add(Check("range", g, out, f"= 0 values outside [{lo:g}, {hi:g}]", out == 0,
                      f"min {v.min():g}, max {v.max():g}"))

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
            stel_exact = np.convolve(v, np.ones(stel_w))[:n] / stel_w
            twa_exact = np.cumsum(v) * dt / twa_p
            e_s, e_t = np.max(np.abs(stel - stel_exact)), np.max(np.abs(twa - twa_exact))
            rep.add(Check("stel_formula", g, float(e_s), f"max |STEL - 15-min mean| <= {res / 2:g}",
                          e_s <= res / 2 + 1e-9, f"peak STEL {stel.max():g}"))
            rep.add(Check("twa_formula", g, float(e_t), f"max |TWA - dose/8 h| <= {res / 2:g}",
                          e_t <= res / 2 + 1e-9, f"end-of-shift TWA {twa[-1]:g}"))
            m2 = int(np.sum(d[f"{p}_alarm_stel"].to_numpy() != (stel >= lim[g]["stel"])) +
                     np.sum(d[f"{p}_alarm_twa"].to_numpy() != (twa >= lim[g]["twa"])))
            rep.add(Check("stel_twa_alarms", g, m2, f"= 0 mismatches (STEL >= {lim[g]['stel']:g}, TWA >= {lim[g]['twa']:g})",
                          m2 == 0))

        # alarm cause: an event on this gas
        mix = val(A["bump_test"]["gas_mix"])
        on_gas = (ev == f"exposure_{g}") | ((ev == "bump_test") & (g in mix))
        inst = (d[f"{p}_alarm_low"].to_numpy() == 1) | (d[f"{p}_alarm_high"].to_numpy() == 1) | \
               (d[f"{p}_over_range"].to_numpy() == 1)
        no_cause = int(np.sum(inst & ~on_gas))
        if g in TOXIC:
            recent = np.convolve(on_gas.astype(float), np.ones(stel_w))[:n] > 0          # event in the last 15 min
            ever = np.cumsum(on_gas) > 0
            no_cause += int(np.sum((d[f"{p}_alarm_stel"].to_numpy() == 1) & ~recent))
            no_cause += int(np.sum((d[f"{p}_alarm_twa"].to_numpy() == 1) & ~ever))
        rep.add(Check("alarm_cause", g, no_cause, "= 0 alarm samples without an event on this gas", no_cause == 0,
                      f"alarm samples {int(inst.sum())}"))

    # bump test: every gas of the mix starts changing at the first bump-test sample
    base = val(A["clean_air_baseline"])
    mix = {g: c for g, c in val(A["bump_test"]["gas_mix"]).items() if g in ch_all}
    bumps = runs(d["device_mode"].to_numpy() == "bump_test")
    notes, ok = [], bool(bumps)
    for s, e in bumps:
        onset = {}
        for g, c in mix.items():
            v, res = d[ch_all[g]["column"]].to_numpy(float), float(val(ch_all[g]["resolution"]))
            band = max(2 * res, 0.05 * abs(c - base[g]))
            moved = np.where(np.sign(c - base[g]) * (v[max(0, s - 30):e] - base[g]) > band)[0]
            onset[g] = int(moved[0]) + max(0, s - 30) if len(moved) else None
        same = len(set(onset.values())) == 1 and onset[next(iter(onset))] == s
        ok &= same
        notes.append(f"bump at row {s}: first change " + ", ".join(f"{g}@{i}" for g, i in onset.items()))
    rep.add(Check("bump_simultaneous", "all", len(bumps), "every bump: all mix gases change first at its first sample",
                  ok, "; ".join(notes) or "no bump test found"))

    # state values
    allowed = {"device_mode": set(val(A["state_values"])["device_mode"])}
    for c, sc in spec.get("state_columns", {}).items():
        allowed[c] = set(map(str, val(sc["values"])))
    if "gateway" in spec:
        allowed["link"] = set(val(spec["gateway"]["link_values"]))
    for c in d.columns:
        if "_alarm_" in c or c.endswith("_over_range"):
            allowed[c] = {"0", "1"}
    bad = {c: sorted(set(d[c].astype(str)) - a) for c, a in allowed.items() if set(d[c].astype(str)) - a}
    const = {c: d[c].nunique() for c in ("device_id", "bridge_id") if c in d.columns}
    st_ok = not bad and all(k == 1 for k in const.values())
    rep.add(Check("state_values", "all", len(bad), "= 0 columns with values outside the allowed set; ids constant",
                  st_ok, str(bad) if bad else f"{len(allowed)} columns checked"))

    # scenario content
    first_bump_s = bumps[0][0] * dt if bumps else None
    ex_runs = [r for r in runs(np.char.startswith(ev.astype(str), "exposure_"))]
    ex_lo, ex_hi = val(A["exposure"]["count_per_shift"])
    cond = [first_bump_s is not None and first_bump_s <= 900, ex_lo <= len(ex_runs) <= ex_hi]
    note = f"first bump at {first_bump_s} s; exposures {len(ex_runs)}"
    if "sos_state" in d.columns:
        n_sos = len(runs(d["sos_state"].to_numpy() == 1))
        cond.append(n_sos == int(val(A["sos"]["count_per_shift"])))
        note += f"; SOS events {n_sos}"
    rep.add(Check("scenario_content", "all", len(ex_runs),
                  f"bump in first 15 min, {ex_lo}-{ex_hi} exposures" + (", SOS as configured" if "sos_state" in d.columns else ""),
                  all(cond), note))
    return rep


def devices():
    return sorted(x for x in os.listdir(CONFIGS) if os.path.isfile(os.path.join(CONFIGS, x, "spec.json")))


def default_csv(device, seed=42):
    return os.path.join(ROOT, "data", "gas", f"{device}_shift_seed{seed}.csv")


def write_readme(results: dict, path: str):
    """data/gas/README.md: what the data is, per-device gate results, and every ASSUMPTION."""
    with open(os.path.join(CONFIGS, "assumptions.json")) as fh:
        A = json.load(fh)
    L = ["# Gas detector data (datasheet-based)", "",
         "**What this is:** synthetic data that **obeys the datasheets** (range, resolution) and is **consistent "
         "by rule** (alarms, STEL/TWA, simultaneous bump test, timestamps).",
         "",
         "**What this is not:** it is **not** made to look like field data. No real recording of these devices was "
         "available, so nothing here was compared with, or fitted to, real readings. Noise, event shapes and "
         "timings are assumptions (listed below), not measurements.", "",
         "- Generator: `core/gas_detector.py` (`python3 cli/generate_gas.py --all`), one 8-h shift per device, seed 42.",
         "- Rule gate: `validation/gas_gate.py` (`python3 validation/gas_gate.py --all --json data/gas/gate_report.json "
         "--readme data/gas/README.md`). The gate recomputes every rule from the CSV; it shares no code with the generator.",
         "- Specs: `configs/gas/<device>/spec.json`: only datasheet values, each with `{value, unit, source}`.",
         "- Assumptions: `configs/gas/assumptions.json`: everything else, each marked `ASSUMPTION` with a reason.", ""]
    n_pass = sum(r["report"]["passed"] for r in results.values())
    fired = {k: sum(r["alarm_counts"].get(k, 0) for r in results.values())
             for k in ("stel", "twa", "over_range")}
    L += ["## Summary", "",
          f"- Rule gate: **{n_pass} of {len(results)} devices pass every check.**",
          "- What these shifts do not exercise (the checks still run and confirm there is no false alarm): "
          f"STEL alarms {fired['stel']}, TWA alarms {fired['twa']}, over-range samples {fired['over_range']}; the "
          "Bridge link stays on cellular. Unit tests (`tests/test_gas.py`) force an over-range exposure and a STEL "
          "alarm and check that the gate still passes, and corrupt files one rule at a time to check that it fails.", "",
          "## Files", "", "| file | device | rows | gate |", "|---|---|---|---|"]
    for dev, r in results.items():
        L.append(f"| `{os.path.basename(r['csv'])}` | {r['model']} | {r['rows']} | "
                 f"{'PASS' if r['report']['passed'] else '**FAIL**'} |")
    L += ["", "Columns: `timestamp` (ISO 8601 UTC), `device_id`, gas readings with the unit in the name "
          "(`lel_pct_lel`, `o2_pct_vol`, `co_ppm`, `h2s_ppm`, `voc_ppm`), `co_/h2s_stel_ppm` and `_twa_ppm`, "
          "state columns (`device_mode`, `pump_state`, `sos_state`, `bridge_id`, `link`), alarm flags "
          "(`<gas>_alarm_low/high/stel/twa`, `<gas>_over_range`; 0/1), and `event`, a ground-truth label "
          "written by the generator, not a device field.", ""]
    for dev, r in results.items():
        L += [f"## {r['model']} (`{dev}`)", "", f"Source: {r['source']}. Events: {r['events']}.", "",
              "| check | channel | result | value | required | detail |", "|---|---|---|---|---|---|"]
        for c in r["report"]["checks"]:
            v = c["value"]
            vs = f"{v:.4g}" if isinstance(v, float) else str(v)
            L.append(f"| {c['name']} | {c['sensor']} | {'pass' if c['passed'] else '**FAIL**'} | {vs} | "
                     f"{c['threshold']} | {c['note']} |")
        if r.get("verify"):
            L += [""] + [f"- To verify: {x}" for x in r["verify"]]
        L.append("")
    L += ["## Assumptions (not in the datasheets)", "",
          "Every entry is marked `ASSUMPTION` in `configs/gas/assumptions.json`.", "",
          "| assumption | value | unit | reason |", "|---|---|---|---|"]

    def walk(prefix_, node):
        for k, e in node.items():
            if k.startswith("_"):
                continue
            if isinstance(e, dict) and e.get("status") == "ASSUMPTION":
                cell = lambda x: str(x).replace("|", "\\|")
                L.append(f"| `{prefix_}{k}` | `{cell(json.dumps(e['value']))}` | {cell(e['unit'])} | {cell(e['reason'])} |")
            elif isinstance(e, dict):
                walk(f"{prefix_}{k}.", e)
    walk("", A)
    L += ["", "Device-level assumptions in the specs:", "",
          "- `msa_altair_io6`: LEL/O2/CO/H2S ranges and resolutions and `pump_state` are taken from the io4 spec "
          "sheet: **ASSUMPTION: same sensors as io4** (io6 sensor table not found).", ""]
    with open(path, "w") as fh:
        fh.write("\n".join(L))


VERIFY = {
    "msa_altair_io6": ["The VOC (PID) range 0-4000 ppm, resolution 0.1 was given in the brief with the io4 spec sheet "
                       "(MSA 1708-056) as source; the io4 has no VOC channel, so confirm where this value comes from."],
    "blackline_g7x_bridge": ["Gas ranges and resolutions are the G7c values (brief: same sensors as G7c); confirm in "
                             "G7x datasheet R21."],
    "blackline_g8": ["Gas ranges and resolutions are the G7c values (brief: same sensors as G7c, LEL-MPS); confirm in "
                     "G8 spec sheet R1."],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", choices=devices())
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--csv", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--readme", default=None)
    args = ap.parse_args()
    if not args.all and not args.device:
        ap.error("give --device or --all")
    results, ok = {}, True
    for dev in (devices() if args.all else [args.device]):
        csv = args.csv if (args.csv and not args.all) else default_csv(dev)
        rep = check_gas_file(csv, dev)
        spec, _ = load(dev)
        d = pd.read_csv(csv, usecols=["event"] + (["sos_state"] if "sos_state" in pd.read_csv(csv, nrows=0).columns else []))
        evs = [d["event"].iloc[s] for s, _ in runs(d["event"].to_numpy() != "none")]
        if "sos_state" in d.columns:
            evs += ["sos"] * len(runs(d["sos_state"].to_numpy() == 1))
        print(f"== {dev}\n{rep.format().replace('PHYSICS GATE', 'GAS RULE GATE')}\n")
        full = pd.read_csv(csv)
        counts = {"stel": int(sum(full[c].sum() for c in full.columns if c.endswith("_alarm_stel"))),
                  "twa": int(sum(full[c].sum() for c in full.columns if c.endswith("_alarm_twa"))),
                  "over_range": int(sum(full[c].sum() for c in full.columns if c.endswith("_over_range")))}
        results[dev] = {"csv": os.path.relpath(csv, ROOT), "model": spec["model"], "source": spec["source_document"],
                        "alarm_counts": counts,
                        "rows": int(len(d)), "events": ", ".join(evs), "report": rep.to_dict(),
                        "verify": VERIFY.get(dev, [])}
        ok &= rep.passed
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(results, fh, indent=1, default=float)
    if args.readme:
        write_readme(results, args.readme)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
