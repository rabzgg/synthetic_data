"""
run.py — block [F]: one scenario, one seed -> the files of every device in the run.

    world -> events -> every part measures the world at its mount -> device logic blocks ->
    logging (interval; rows lost in connection gaps) -> files

Per device, in the output folder:
    <slug>_<scenario>_seed<n>.csv            clean, as the device would export it (no event or gap columns)
    <slug>_<scenario>_seed<n>_labels.csv     ground truth: events seen, device events, what the device
                                             should do (scope expected)
    <slug>_<scenario>_seed<n>_manifest.json  device (name, slug, version), parts and every parameter
                                             with its source, logic, world (with the defaults it used),
                                             scenario, events placed, seed, generator version
    <slug>_<scenario>_seed<n>_gate.json      the gate (validation/auto_gate.py)
"""
import json
import os
import subprocess
import zlib

import numpy as np
import pandas as pd

from core.events import prepare
from core.events.scenario import hms
from core.logic import Context, Stream, build, outputs
from core.quantities import CATALOG

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def generator_version() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5)
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "core", "configs", "validation"], cwd=ROOT,
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return r.stdout.strip() + ("+local changes" if dirty else "") if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _decimals(res: float) -> int:
    s = f"{res:.10f}".rstrip("0")
    return len(s.split(".")[1]) if "." in s else 0


def measure_device(world, view, seed: int):
    """Readings of every part at the device's mount: {column: Stream on the logging grid}, {quantity:
    Stream}, {quantity: (t_fast, values)} and the unit draws."""
    dev, w = view.device, world
    t_log = np.arange(0, w.duration_s + 1e-9, dev.sample_interval_s)
    wv = w.view(view.mount)
    by_col, by_q, internal, draws = {}, {}, {}, {}
    cols = {(id(u), q): c for u, q, c in dev.reading_columns()}
    for u, q, m in dev.models():
        if q not in w.tracks:
            raise ValueError(f"world {w.name} has no {q}, which {dev.name} ({u.part.slug}) measures; "
                             f"the world provides {', '.join(w.quantities())}")
        vec = CATALOG[q].vector
        dt = w.body_dt if vec else w.air_dt
        t = np.arange(0, w.duration_s + 1e-9, dt)
        x = wv.at(q, t)
        for oq, s, e, mode, val in view.overrides:
            if oq == q and mode == "value":
                x = np.where(((t >= s) & (t < e))[:, None] if vec else (t >= s) & (t < e), val, x)
        others = {o: wv.at(o, t) for o in m.cross_sensitivity}
        rng = np.random.default_rng([seed, zlib.crc32(f"{dev.slug}/{u.part.slug}/{u.alias}/{q}".encode())])
        draw = m.draw(rng)
        r = m.measure(x, dt, rng, others=others, draw=draw,
                      body_quat=wv.at("body.orientation", t) if vec else None)
        y = r.values
        for oq, s, e, mode, val in view.overrides:          # sensor faults act on the reading
            if oq != q or mode == "value":
                continue
            win = (t >= s) & (t < e)
            if mode == "stuck" and win.any():
                y = np.where(win[:, None] if vec else win, y[np.argmax(win)], y)
            elif mode == "zero":
                y = np.where(win[:, None] if vec else win, 0.0, y)
            elif mode in ("offset", "add"):
                y = np.where(win[:, None] if vec else win, y + val, y)
            lo, hi = m.bounds
            y = np.clip(m.quantize(y), lo, hi) + 0.0
        idx = np.clip(np.searchsorted(t, t_log + 1e-9, side="right") - 1, 0, len(t) - 1)
        st = Stream(t_log, y[idx], m)
        by_q.setdefault(q, st)
        internal.setdefault(q, (t, y))
        draws[f"{u.part.slug}/{q}"] = {"u_bias": draw.u_bias.tolist(), "u_drift": draw.u_drift.tolist()}
        if (id(u), q) in cols:
            for k, c in enumerate(cols[(id(u), q)]):
                by_col[c] = Stream(t_log, y[idx][:, k] if vec else y[idx], m)
    return t_log, by_col, by_q, internal, draws


def run_logic(dev, t_log, by_q, internal, view, seed):
    streams = dict(by_q)
    out = {}
    for i, spec in enumerate(dev.logic):
        b = build(spec, dev.name)
        rng = np.random.default_rng([seed, zlib.crc32(f"{dev.slug}/logic{i}/{b.output}".encode())])
        res = b.run(Context(t_log, streams, internal, view, rng))
        if isinstance(res, dict):
            for c, x in res.items():
                out[c] = x
                streams[c] = Stream(t_log, x)
        else:
            model = streams[b.input].model if b.kind in ("rolling_mean", "cumulative_dose") and b.input in streams else None
            out[b.output] = res
            streams[b.output] = Stream(t_log, res, model)
    return out, streams


def device_table(world, view, seed):
    dev = view.device
    t_log, by_col, by_q, internal, draws = measure_device(world, view, seed)
    logic, streams = run_logic(dev, t_log, by_q, internal, view, seed)
    ms = dev.sample_interval_s % 1 != 0
    ts = pd.to_datetime(world.timestamps(t_log)).strftime("%Y-%m-%dT%H:%M:%S.%f" if ms else "%Y-%m-%dT%H:%M:%S")
    ts = [x[:-3] + "Z" if ms else x + "Z" for x in ts]
    data = {"timestamp": ts, "device_id": [dev.device_id()] * len(t_log)}
    fmt = {}
    for c in dev.columns()[2:]:
        if c in by_col:
            data[c] = by_col[c].x
            fmt[c] = _decimals(by_col[c].model.resolution)
        else:
            data[c] = logic[c]
            st = streams.get(c)
            if st is not None and st.model is not None:
                fmt[c] = _decimals(st.model.resolution)
    df = pd.DataFrame(data, columns=dev.columns())
    keep = np.ones(len(t_log), bool)
    for s, e in view.gaps:
        keep &= ~((t_log >= s) & (t_log < e))
    for c, d in fmt.items():
        df[c] = df[c].astype(float).round(d)
        if d == 0:
            df[c] = df[c].astype(int)
    return df[keep].reset_index(drop=True), {"t_log": t_log, "keep": keep, "draws": draws}


def _labels_frame(world, labels):
    rows = []
    for lb in labels:
        r = lb.row()
        r["start_utc"] = str(world.timestamps(lb.start)) + "Z"
        r["end_utc"] = str(world.timestamps(lb.end)) + "Z"
        rows.append(r)
    return pd.DataFrame(rows, columns=["start_s", "end_s", "start_utc", "end_utc", "event", "detail", "scope"])


def manifest(prepared, view, seed, scenario_name, extra) -> dict:
    dev, w = view.device, prepared.world
    parts = []
    for u in dev.parts:
        ms = u.part.models(u.overrides)
        parts.append({"part": u.part.slug, "name": u.part.name, "datasheet": u.part.datasheet, "logged": u.log,
                      "alias": u.alias, "note": u.note, "notes": u.part.notes,
                      "quantities": {q: {"parameters": u.part.params(u.overrides)[q], "kinds": m.kinds,
                                         "derived_sources": {k: s for k, s in m.sources.items()
                                                             if k not in u.part.params(u.overrides)[q]}}
                                     for q, m in ms.items()}})
    return {"device": {"name": dev.name, "slug": dev.slug, "version": dev.version, "path": os.path.relpath(dev.path, ROOT)
                       if dev.path else "", "description": dev.description, "features": dev.features,
                       "logic": dev.logic, "mount": vars(view.mount), "columns": dev.columns(),
                       "device_id": dev.device_id()},
            "parts": parts, "world": w.describe(),
            "scenario": {"name": scenario_name, "title": prepared.scenario.get("title", ""),
                         "realism": prepared.scenario.get("realism", "")},
            "seed": seed, "duration_s": w.duration_s,
            "events": [{"kind": e.kind, "at_s": e.at, "end_s": e.end, "at": hms(e.at),
                        "params": e.params} for e in prepared.events],
            "notes": prepared.notes, "unit_draws": extra["draws"], "generator_version": generator_version()}


def run(scenario, seed: int = None, out_dir: str = "out", devices=None, duration_s: float = None,
        gate: bool = True) -> list:
    """Generate every device of a scenario; returns [{device, csv, labels, manifest, gate, passed}]."""
    from validation.auto_gate import check_device
    p = prepare(scenario, devices=devices, seed=seed, duration_s=duration_s)
    name = p.scenario.get("name", scenario if isinstance(scenario, str) else "scenario")
    seed = int(p.scenario.get("seed", 0) if seed is None else seed)
    os.makedirs(out_dir, exist_ok=True)
    results = []
    for view in p.views:
        view.labels = p.labels[view.slug]                  # what the device's logic may react to
        df, extra = device_table(p.world, view, seed)
        base = os.path.join(out_dir, f"{view.slug}_{name}_seed{seed}")
        df.to_csv(base + ".csv", index=False)
        labels = _labels_frame(p.world, p.labels[view.slug])
        labels.to_csv(base + "_labels.csv", index=False)
        man = manifest(p, view, seed, name, extra)
        man["files"] = {k: os.path.basename(base + s) for k, s in
                        (("csv", ".csv"), ("labels", "_labels.csv"), ("manifest", "_manifest.json"), ("gate", "_gate.json"))}
        with open(base + "_manifest.json", "w") as fh:
            json.dump(man, fh, indent=1, default=_json)
        rec = {"device": view.slug, "csv": base + ".csv", "labels": base + "_labels.csv",
               "manifest": base + "_manifest.json"}
        if gate:
            g = check_device(base + ".csv", base + "_labels.csv", base + "_manifest.json")
            with open(base + "_gate.json", "w") as fh:
                json.dump(g, fh, indent=1, default=_json)
            rec.update(gate=base + "_gate.json", passed=g["passed"])
        results.append(rec)
    return results


def _json(x):
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        return float(x)
    if isinstance(x, np.ndarray):
        return x.tolist()
    return str(x)
