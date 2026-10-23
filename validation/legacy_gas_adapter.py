"""
legacy_gas_adapter.py — run the old gas rule gate (validation/gas_gate.py) on files from the new
generator, for parity.

The new CSV is a clean export; the old gate wants two more columns, which the adapter rebuilds from
the run's labels and manifest:
    gap_before_s  seconds without rows before a row (the logging step beyond the interval), 0 elsewhere
    event         none | bump_test | exposure_<gas>, as the old engine wrote it: an exposure lasts from
                  the start of the release until the gas the sensor is exposed to is back within half a
                  resolution step (first-order decay with the part's falling t90, the old engine's rule);
                  a bump test lasts while device_mode is bump_test
The coverage items the old gate looks for follow from the scenario (STEL scenario -> sustained_stel, ...).

Usage: python3 validation/legacy_gas_adapter.py [--seeds 42 43 44 45 46] [--out out/parity]
"""
import argparse
import json
import os
import sys
import tempfile

import numpy as np
import pandas as pd

LABEL_TEXT = {"event": str, "detail": str, "scope": str}       # text columns of a labels file

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

GAS_SCENARIOS = {"gas_normal_shift": [], "gas_stel_alarm": ["sustained_stel"], "gas_twa_alarm": ["prolonged_twa"],
                 "gas_over_range": ["over_range"], "gas_voc_exposure": ["voc"], "gas_pump_fault": ["pump_fault"],
                 "worker_collapse": []}
DOC = os.path.join(ROOT, "docs", "GAS_PARITY.md")
WHY = {
    "bump_simultaneous": (
        "an old rule tied to the old engine's 10-s steps, not a fault in the new data. The old rule wants every gas "
        "of the bump mix to have moved by more than twice its resolution in the very first bump-test row. The new "
        "generator applies the test gas at 06:02:00 and logs that same second, so the sensor (t90 30 s) has seen the "
        "gas for one second: on the MSA detectors H2S (resolution 1 ppm) reads 2 ppm, not more than 2, and passes "
        "the band ten seconds later; the other gases move in the first row. The old engine filtered the response in "
        "10-s steps, so its first row always held 10 s of exposure. The bump is simultaneous; the new gate checks "
        "the response with input_response and passes."),
    "alarm_cause": (
        "a physical effect the old engine did not model. A combustible gas above 100 %LEL displaces air: 128 %LEL of "
        "methane is 6.4 %vol, so oxygen falls to about 19.5 %vol and the O2 low alarm (<= 19.5) goes off. The old "
        "rule only accepts an O2 alarm during an event on O2 itself, so it calls it an alarm without a cause. The new "
        "world derives O2 from the other gases (core/world/physics.py); the alarm is right."),
}


def _v(p):
    return p["value"] if isinstance(p, dict) and "value" in p else p


def to_legacy(csv_path, labels_path, manifest_path) -> pd.DataFrame:
    from core.quantities import resolve
    d = pd.read_csv(csv_path)
    lab = pd.read_csv(labels_path, dtype=LABEL_TEXT).fillna({c: "" for c in LABEL_TEXT})
    with open(manifest_path) as fh:
        man = json.load(fh)
    interval = float(_v(man["device"]["features"]["sample_interval_s"]))
    start = pd.Timestamp(man["world"]["start_utc"].replace("Z", ""))
    t = (pd.to_datetime(d["timestamp"].str.replace("Z", "")) - start).dt.total_seconds().to_numpy()
    gap = np.concatenate([[0.0], np.diff(t) - interval])
    d.insert(2 + sum(c in d.columns for c in ("bridge_id", "bridge_link")), "gap_before_s", np.round(gap).astype(int))
    event = np.array(["none"] * len(d), dtype=object)
    params = {}
    for p in man["parts"]:
        for q, spec in p["quantities"].items():
            params[q] = {k: _v(x) for k, x in spec["parameters"].items()}
    for e in man["events"]:
        if e["kind"] not in ("gas_release", "collapse"):
            continue
        g = _v(e["params"]["gas"])
        q = resolve(g)
        if q not in params:
            continue
        level = float(_v(e["params"]["level"]))
        ramp, dur = float(_v(e["params"]["ramp_s"])), float(_v(e["params"]["duration_s"]))
        res = float(params[q]["resolution"])
        t90d = float(params[q].get("t90_down_s", params[q].get("t90_s", 0)))
        tail = t90d / np.log(10) * np.log(max(level / (res / 2), 1.0)) if t90d > 0 else 0.0
        s, e_end = e["at_s"], e["at_s"] + 2 * ramp + dur + tail
        event[(t >= s) & (t < e_end)] = f"exposure_{g}"
    event[d["device_mode"].to_numpy() == "bump_test"] = "bump_test"
    d["event"] = event
    return d


def check(csv_path, labels_path, manifest_path, items):
    from validation.gas_gate import check_gas_file
    with open(manifest_path) as fh:
        dev = json.load(fh)["device"]["slug"]
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "legacy.csv")
        to_legacy(csv_path, labels_path, manifest_path).to_csv(p, index=False)
        return check_gas_file(p, dev, items=items)


def main():
    from core.output import run
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="*", default=[42, 43, 44, 45, 46])
    ap.add_argument("--out", default=os.path.join(ROOT, "out", "parity"))
    ap.add_argument("--all-devices", action="store_true", help="also gas_normal_shift on every gas detector preset")
    args = ap.parse_args()
    runs = [(sc, None) for sc in GAS_SCENARIOS]
    if args.all_devices:
        runs += [("gas_normal_shift", [d]) for d in ("blackline_g7x_bridge", "blackline_g8", "msa_altair_io4",
                                                     "msa_altair_io6")]
    rows = []
    for sc, devs in runs:
        for seed in args.seeds:
            res = run(sc, seed=seed, out_dir=os.path.join(args.out, sc), devices=devs, gate=False)
            for r in res:
                if r["device"] == "bme280_sensor_board":
                    continue
                rep = check(r["csv"], r["labels"], r["manifest"], GAS_SCENARIOS[sc])
                failed = [f"{c.name}:{c.sensor}" for c in rep.checks if not c.passed]
                rows.append((sc, seed, r["device"], rep.passed, failed, rep))
                print(f"{sc:20s} seed {seed} {r['device']:22s} {'PASS' if rep.passed else 'FAIL'} {failed}")
    n_pass = sum(r[3] for r in rows)
    L = ["# Gas parity: new generator, old rule gate", "",
         "_Generated by `python3 validation/legacy_gas_adapter.py --all-devices`; do not edit by hand._", "",
         f"**{n_pass} of {len(rows)} files pass the old gas rule gate** (`validation/gas_gate.py`, unchanged). The "
         "adapter (`validation/legacy_gas_adapter.py`) adds the two columns the old gate reads, `gap_before_s` and "
         "`event`, from the run's labels and manifest, with the old engine's meaning of an exposure.", "",
         "| scenario | seed | device | old gate | failed checks |", "|---|---|---|---|---|"]
    L += [f"| `{sc}` | {seed} | `{dev}` | {'PASS' if ok else '**FAIL**'} | {', '.join(f) or '—'} |"
          for sc, seed, dev, ok, f, _ in rows]
    kinds = sorted({f.split(":")[0] for r in rows for f in r[4]})
    if kinds:
        L += ["", "## Why the failures", ""]
    for k in kinds:
        L += [f"- **`{k}`**: " + WHY.get(k, "not analysed yet: look at the check's note in the old gate output."), ""]
    with open(DOC, "w") as fh:
        fh.write("\n".join(L) + "\n")
    print(f"{n_pass}/{len(rows)} pass; wrote {os.path.relpath(DOC, ROOT)}")


if __name__ == "__main__":
    main()
