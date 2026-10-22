"""
auto_gate.py — the gate for any device, derived from its spec: the part parameters and logic blocks
written in the run's manifest, the labels file and the CSV. It recomputes from the CSV and does not
use the generator's code paths (it reads the measurement model only for ranges and resolutions,
and the logic block definitions only for their parameters).

Checks (each with its threshold in the result):
    columns          exactly the device's columns, in order (after output_format: the vendor's names; the
                     values are turned back to the catalog's units before the other checks)
    device_id        one id, the device's
    timestamps       every logging time is a row, or inside an announced connection gap; no row in a gap
    range / grid     every reading inside its sensor's range and on its resolution grid
    threshold_alarm  recomputed from the CSV input column (state carried across a gap from the CSV)
    rolling_mean / cumulative_dose  exact where the window has no gap, bounded where it has
    rate_of_change   exact where both ends are rows
    event_mode       the value during each event, the default before it, back to the default once
                     the listed readings are back
    state_flag       on exactly during the device events that hold that state
    battery          recomputed from runtime, start and battery_drain events
    signal           whole dBm, inside the range, steps no larger than 6 sd per row
    constant / random_state   the value / one of the values
    motion blocks    the device's state agrees with the expected labels (truth) on at least 95 % of
                     rows, every expected alert is reported, no alert where none is expected (with a
                     tolerance of the block's window plus two rows)
    orientation      quaternion x, y, z inside the unit ball
    input_response   a sensor given a test value (bump test) moves at least half way towards it
    same_quantity    two parts on one quantity differ by no more than their combined error bounds
"""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

MOTION_AGREE = 0.95
SIGNAL_SD_STEPS = 6.0


def _v(p):
    return p["value"] if isinstance(p, dict) and "value" in p else p


class Report:
    def __init__(self, device):
        self.device, self.checks = device, []

    def add(self, name, column, passed, value="", threshold="", note=""):
        self.checks.append({"name": name, "column": column, "passed": bool(passed), "value": value,
                            "threshold": threshold, "note": note})

    def to_dict(self):
        return {"device": self.device, "passed": all(c["passed"] for c in self.checks), "checks": self.checks,
                "failed": [f"{c['name']}:{c['column']}" for c in self.checks if not c["passed"]]}


def _models(man):
    from core.quantities import CATALOG, MeasurementModel
    out = {}
    for p in man["parts"]:
        for q, d in p["quantities"].items():
            params = {k: dict(v, **({"kind": d["kinds"][k]} if k in d.get("kinds", {}) else {}))
                      for k, v in d["parameters"].items()}
            out.setdefault(q, []).append((p, MeasurementModel.from_params(q, params)))
    return out


def _reading_columns(man, models):
    """{column: (quantity, model, axis index or None)} for logged readings, following the manifest's parts."""
    from core.quantities import CATALOG
    cols = {}
    count = {}
    for p in man["parts"]:
        for q in p["quantities"]:
            logged = p["logged"] is True or (isinstance(p["logged"], list) and q in p["logged"])
            if logged:
                count[q] = count.get(q, 0) + 1
    for p in man["parts"]:
        for q in p["quantities"]:
            logged = p["logged"] is True or (isinstance(p["logged"], list) and q in p["logged"])
            if not logged:
                continue
            m = next(mm for pp, mm in models[q] if pp is p)
            names = CATALOG[q].columns()
            if count[q] > 1:
                names = [f"{c}_{p['alias'] or p['part']}" for c in names]
            for k, c in enumerate(names):
                cols[c] = (q, m, k if CATALOG[q].vector else None)
    return cols


def check_device(csv_path, labels_path, manifest_path) -> dict:
    from core.events import EVENTS
    from core.logic import build
    with open(manifest_path) as fh:
        man = json.load(fh)
    df = pd.read_csv(csv_path)
    lab = pd.read_csv(labels_path).fillna("")
    dev = man["device"]
    R = Report(dev["slug"])
    interval = float(_v(dev["features"].get("sample_interval_s", {"value": 1})))
    duration = float(man["duration_s"])
    start = pd.Timestamp(man["world"]["start_utc"].replace("Z", ""))

    # columns, id; output_format: written with the vendor's names and units, checked in the catalog's
    R.add("columns", "*", list(df.columns) == dev["columns"], len(df.columns), f"{len(dev['columns'])} columns in order")
    for c, (name, sc, off) in (dev.get("output_transforms") or {}).items():
        if name in df:
            if (sc, off) != (1.0, 0.0):
                df[name] = np.round((df[name].astype(float) - off) / sc, 9)   # back to the catalog unit, float noise off
            df = df.rename(columns={name: c})
    ids = df["device_id"].unique().tolist() if "device_id" in df else []
    R.add("device_id", "device_id", ids == [dev.get("device_id")], ids[:3], dev.get("device_id"))

    # timestamps and gaps
    t = ((pd.to_datetime(df["timestamp"].str.replace("Z", "")) - start).dt.total_seconds()).to_numpy()
    grid = np.arange(0, duration + 1e-9, interval)
    gaps = [(r.start_s, r.end_s) for r in lab.itertuples() if r.event == "connection_loss"]
    in_gap = lambda x: np.array([any(s <= xi < e for s, e in gaps) for xi in np.atleast_1d(x)])
    present = np.isin(np.round(grid, 3), np.round(t, 3))
    missing = grid[~present]
    R.add("timestamps", "timestamp", bool(np.all(np.diff(t) > 0)) and in_gap(missing).all() and not in_gap(t).any()
          and np.allclose(np.round(t / interval) * interval, t, atol=1e-3),
          f"{(~present).sum()} missing rows, {int(in_gap(t).sum())} rows inside gaps",
          f"every {interval:g} s, or inside an announced gap")
    row_idx = np.round(t / interval).astype(int)
    after_gap = np.concatenate([[False], np.diff(row_idx) > 1])

    # readings
    models = _models(man)
    rcols = _reading_columns(man, models)
    for c, (q, m, k) in rcols.items():
        if c not in df:
            continue
        x = df[c].to_numpy(float)
        lo, hi = m.bounds
        lo, hi = (np.atleast_1d(lo)[k if k is not None and np.ndim(lo) else 0], np.atleast_1d(hi)[k if k is not None and np.ndim(hi) else 0])
        R.add("range", c, np.isfinite(x).all() and (x >= lo - 1e-9).all() and (x <= hi + 1e-9).all(),
              f"{np.nanmin(x):g}..{np.nanmax(x):g}", f"{lo:g}..{hi:g}")
        on_grid = np.abs(x / m.resolution - np.round(x / m.resolution)) < 1e-6 + 1e-9 * np.abs(x) / m.resolution
        on_grid |= (x == lo) | (x == hi)
        R.add("resolution", c, bool(on_grid.all()), int((~on_grid).sum()), f"multiples of {m.resolution:g}")

    # logic
    cols = {c: df[c].to_numpy() for c in df.columns}
    q_of = {q: c for c, (q, m, k) in rcols.items() if k is None}
    model_of = {c: m for c, (q, m, k) in rcols.items()}

    def col_for(inp):
        return q_of.get(inp, inp)

    state_events = {}
    for kind, d in EVENTS.items():
        for e in d.effects:
            if e.get("target") == "device.state":
                state_events.setdefault(e["state"], []).append(kind)
    for spec in dev["logic"]:
        b = build(spec, dev["name"])
        out = b.output
        if b.kind == "orientation_quat":
            qc = [c for c in df.columns if c.startswith(spec.get("prefix", "orientation") + "_")]
            xyz = df[[c for c in qc if not c.endswith("_w")]].to_numpy(float)
            R.add("orientation", ",".join(qc), bool((np.sum(xyz ** 2, axis=1) <= 1 + 1e-3).all()), "", "|xyz| <= 1")
            continue
        if out not in df:
            continue
        y = cols[out]
        inp = col_for(b.input) if b.input else None
        if b.kind == "threshold_alarm":
            if inp not in cols:
                R.add("threshold_alarm", out, False, "", "", f"input {b.input} is not in the CSV")
                continue
            x = cols[inp].astype(float)
            level = b.level(model_of.get(inp))
            h, latch = float(b.p("hysteresis")), bool(_v(b.spec.get("latching", False)))
            on_v, off_v = b.spec.get("on_value", 1), b.spec.get("off_value", 0)
            if h == 0 and not latch:
                exp = b.apply(x, level)
            else:                                   # stateful: carry the state, take it from the CSV after a gap
                above = b.spec["when"] == "above"
                exp, state = [], False
                for i in range(len(x)):
                    trig = x[i] >= level if above else x[i] <= level
                    clear = x[i] < level - h if above else x[i] > level + h
                    if i == 0 or after_gap[i]:
                        state = trig or (str(y[i]) == str(on_v) and not clear)
                    else:
                        state = True if trig else (state if (latch or not clear) else False)
                    exp.append(on_v if state else off_v)
                exp = np.array(exp, dtype=object)
            bad = int(np.sum(np.asarray(exp).astype(str) != y.astype(str)))
            R.add("threshold_alarm", out, bad == 0, bad, f"0 rows differ from {inp} {b.spec['when']} {level:g}")
        elif b.kind in ("rolling_mean", "cumulative_dose"):
            x = cols[inp].astype(float)
            m = model_of.get(inp)
            res = m.resolution if m else 0.0
            if b.kind == "rolling_mean":
                w = int(round(b.p("window_s") / interval))
            full = np.zeros(len(grid))
            full[row_idx] = x
            have = np.zeros(len(grid), bool)
            have[row_idx] = True
            cs, ch = np.concatenate([[0.0], np.cumsum(full)]), np.concatenate([[0], np.cumsum(~have)])
            i1 = row_idx + 1
            i0 = np.maximum(i1 - w, 0) if b.kind == "rolling_mean" else np.zeros_like(i1)
            denom = w if b.kind == "rolling_mean" else b.p("period_s") / interval
            lo_v = (cs[i1] - cs[i0]) / denom
            n_miss = ch[i1] - ch[i0]
            top = float(np.max(m.bounds[1])) if m else float(np.nanmax(x))
            hi_v = lo_v + n_miss * top / denom
            exact = n_miss == 0
            y = y.astype(float)
            ok_exact = np.abs(y[exact] - (np.clip(m.quantize(lo_v[exact]), *m.bounds) if m else lo_v[exact])) <= 1e-9 + res * 1e-6
            ok_bound = (y[~exact] >= lo_v[~exact] - res) & (y[~exact] <= hi_v[~exact] + res)
            R.add(b.kind, out, bool(ok_exact.all() and ok_bound.all()),
                  f"{int((~ok_exact).sum())} exact, {int((~ok_bound).sum())} bounded rows off",
                  "exact where no gap in the window, bounded otherwise")
        elif b.kind == "rate_of_change":
            x = cols[inp].astype(float)
            w = int(round(b.p("window_s") / interval))
            pos = {r: i for i, r in enumerate(row_idx)}
            per = {"s": 1.0, "min": 60.0, "h": 3600.0}[spec.get("per", "min")]
            errs = [abs(y[i] - (x[i] - x[pos[r - w]]) / (w * interval) * per) for i, r in enumerate(row_idx) if r - w in pos]
            R.add("rate_of_change", out, (max(errs) if errs else 0) < 1e-6, max(errs) if errs else 0, "exact")
        elif b.kind == "event_mode":
            evs = lab[(lab.event == spec["event"]) & (lab.scope == "device")]
            ok, note = True, ""
            back = [col_for(q) for q in spec.get("until_back", []) if col_for(q) in cols]
            first = evs.start_s.min() if len(evs) else np.inf
            if (y[t < first] != spec["default"]).any():
                ok, note = False, "not default before the first event"
            for r in evs.itertuples():
                inside = (t >= r.start_s) & (t < r.end_s)
                if (y[inside] != spec["value"]).any():
                    ok, note = False, f"not {spec['value']} during the event at {r.start_s:g} s"
                pre = np.where(t < r.start_s)[0]
                if not len(pre):
                    continue
                base = {c: cols[c][pre[-1]] for c in back}
                after = np.where(t >= r.end_s)[0]
                done = next((i for i in after if all(abs(cols[c][i] - base[c]) <= model_of[c].resolution + 1e-9
                                                     for c in back)), None)
                if done is not None and (y[after[after >= done]] == spec["value"]).any():
                    nxt = evs.start_s[evs.start_s > r.start_s].min() if (evs.start_s > r.start_s).any() else np.inf
                    late = after[(after >= done) & (t[after] < nxt)]
                    if (y[late] == spec["value"]).any():
                        ok, note = False, "still in the mode after the readings were back"
            R.add("event_mode", out, ok, note, f"{spec['value']} during {spec['event']} until back")
        elif b.kind == "state_flag":
            kinds = state_events.get(spec["state"], [])
            win = [(r.start_s, r.end_s) for r in lab.itertuples() if r.event in kinds and r.scope == "device"]
            on = np.array([any(s <= ti < e for s, e in win) for ti in t])
            exp = np.where(on, spec.get("on_value", 1), spec.get("off_value", 0))
            bad = int(np.sum(exp.astype(str) != y.astype(str)))
            R.add("state_flag", out, bad == 0, bad, f"on exactly during {', '.join(kinds)}")
        elif b.kind == "battery":
            pct = b.p("start_pct") - 100.0 * t / (b.p("runtime_h") * 3600.0)
            for e in man["events"]:
                if e["kind"] == "battery_drain" and ((lab.event == "battery_drain") & (abs(lab.start_s - e["at_s"]) < 1e-6)).any():
                    pct = pct - _v(e["params"]["extra_pct_per_h"]) * np.clip(np.minimum(t, e["end_s"]) - e["at_s"], 0, None) / 3600
            exp = np.clip(np.floor(pct), 0, 100)
            bad = int(np.sum(exp != y.astype(float)))
            R.add("battery", out, bad == 0, bad, "floor(start - 100 t / runtime - extra drain)")
        elif b.kind == "signal":
            lo, hi = b.p("range_dbm")
            steps = np.abs(np.diff(y.astype(float)))
            allow = SIGNAL_SD_STEPS * b.p("step_sd_db") * np.sqrt(np.maximum(np.diff(row_idx), 1))
            ok = (y.astype(float) == np.round(y.astype(float))).all() and (y >= lo).all() and (y <= hi).all() and (steps <= allow).all()
            R.add("signal", out, bool(ok), f"{y.min()}..{y.max()}", f"{lo}..{hi} dBm, steps <= {SIGNAL_SD_STEPS:g} sd")
        elif b.kind == "constant":
            R.add("constant", out, bool((y.astype(str) == str(_v(spec["value"]))).all()), "", str(_v(spec["value"])))
        elif b.kind == "random_state":
            R.add("random_state", out, bool(np.isin(y.astype(str), [str(s) for s in spec["values"]]).all()), "",
                  f"one of {spec['values']}")
        elif b.kind in ("stillness_timer", "spike_then_still"):
            name = out[:-len("_state")] if out.endswith("_state") else out
            ex = lab[(lab.scope == "expected") & lab.event.str.startswith(name + "_")]
            tol = float(b.p("window_s") if "window_s" in b.spec else b.p("within_s")) + 2 * interval
            exp_at = lambda ti: next((r.event[len(name) + 1:] for r in ex.itertuples() if r.start_s <= ti < r.end_s), "ok")
            match = np.array([y[i] == exp_at(ti) or y[i] in (exp_at(ti - tol), exp_at(ti + tol)) for i, ti in enumerate(t)])
            alerts_ok = all(((y == "alert") & (t >= r.start_s - tol) & (t <= r.end_s + tol)).any()
                            for r in ex.itertuples() if r.event.endswith("_alert") and r.end_s - r.start_s > 2 * tol)
            R.add(b.kind, out, match.mean() >= MOTION_AGREE and alerts_ok,
                  f"{match.mean() * 100:.1f} % rows agree, alerts {'reported' if alerts_ok else 'missed'}",
                  f">= {MOTION_AGREE * 100:g} % agree (± {tol:g} s), every expected alert reported")

    # input response (bump test)
    for e in man["events"]:
        if e["kind"] != "bump_test" or not ((lab.event == "bump_test") & (lab.scope == "device") &
                                            (abs(lab.start_s - e["at_s"]) < 1e-6)).any():
            continue
        from core.quantities import resolve
        for g, val in _v(e["params"]["mix"]).items():
            c = q_of.get(resolve(g))
            if c is None:
                continue
            x = cols[c].astype(float)
            pre = x[t < e["at_s"]]
            win = x[(t >= e["at_s"]) & (t <= e["end_s"] + 60)]
            if not len(pre) or not len(win):
                continue
            moved = (win - pre[-1]) / (val - pre[-1]) if val != pre[-1] else np.ones(1)
            R.add("input_response", c, moved.max() >= 0.5, f"{moved.max() * 100:.0f} % of the way", ">= 50 % towards the test value")

    # two parts on one quantity
    for q, lst in models.items():
        cs = [c for c, (qq, m, k) in rcols.items() if qq == q and k is None]
        if len(cs) >= 2:
            (c1, (_, m1, _)), (c2, (_, m2, _)) = [(c, rcols[c]) for c in cs[:2]]
            x1, x2 = cols[c1].astype(float), cols[c2].astype(float)
            allow = m1.error_bound(x1) + m2.error_bound(x2) + m1.resolution + m2.resolution + \
                4 * np.hypot(m1.noise_sd, m2.noise_sd) + (m1.hard("drift_per_hour") + m2.hard("drift_per_hour")) * duration / 3600
            d = np.abs(x1 - x2)
            R.add("same_quantity", f"{c1},{c2}", bool((d <= allow).all()), f"max {d.max():.3g}", "combined error bounds")
    return R.to_dict()
