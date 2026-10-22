"""
scenario.py — a scenario file (configs/scenarios/<name>.yaml): a world, devices with their mounts,
a list of events, a duration and a seed.

    name: collapse_demo
    title: "Collapse in a tank"
    realism: ASSUMPTION
    world: indoor_worker_walking
    duration: 8h
    seed: 42
    devices:                                  # a run can replace these
      - {device: blackline_g7c, mount: body}
      - {device: bme280_sensor_board, mount: fixed, height_m: 1.0}
    events:
      - bump_test: {at: "00:02:00"}
      - gas_release: {at: "01:04:00", gas: h2s, level: 20, duration_min: 20}
      - collapse: {at: "03:00:00", gas: h2s, level: 60}
      - connection_loss: {at: "01:23:00", duration_s: 70}

An event entry may also carry: count (how many, may be random), spacing_s (gap kept between this
entry's events and every other event of the same kind), devices (which devices a device event goes to), optional (skip, with a note, where no
device supports it: a scenario written for several device types). Parameters ending in _min or _h
are read as the _s parameter.

prepare() builds the world, applies the events and returns everything phase 5 needs: the world,
one DeviceView per device, the labels per device (what happened, and what each device should do in
response, e.g. the no-motion pre-alarm and alert) and notes on events some devices do not see.
An event that no device of the run can see is refused with the reason: a world event is seen by a
device when it changes something the device measures, at its mount, by at least that sensor's
resolution (tried numerically on the run's world); a device event when the device has the features
it requires and measures what it is given.
"""
import os
import zlib
from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np
import yaml

from core.devices import Device
from core.world import Mount, World

from core.quantities import CATALOG, resolve as resolve_quantity
from core.quantities import rotation as rot

from .base import DeviceView, Label, ScenarioError, draw, has_feature, hms, parse_time, resolve
from .library import EVENTS

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCENARIOS_DIR = os.path.join(ROOT, "configs", "scenarios")
PROBE_WORLD = "indoor_worker_walking"
VISIBILITY_MARGIN_S = 300.0        # after the event's end, effects such as a recovery still count
ENTRY_KEYS = ("at", "count", "spacing_s", "devices", "optional")


def load_scenario(name: str, scenarios_dir: str = SCENARIOS_DIR) -> dict:
    path = os.path.join(scenarios_dir, f"{name}.yaml")
    if not os.path.exists(path):
        raise FileNotFoundError(f"scenario {name!r} not found in {scenarios_dir}")
    with open(path) as fh:
        return yaml.safe_load(fh)


def list_scenarios(scenarios_dir: str = SCENARIOS_DIR) -> list:
    return sorted(f[:-5] for f in os.listdir(scenarios_dir) if f.endswith(".yaml"))


def _seconds_aliases(params: dict, known=()) -> dict:
    """x_min / x_h -> x_s (times 60 / 3600) where the event has an x_s parameter."""
    out = {}
    for k, v in params.items():
        for suf, f in (("_min", 60), ("_h", 3600)):
            if k.endswith(suf) and k[: -len(suf)] + "_s" in known:
                k = k[: -len(suf)] + "_s"
                v = {kk: ([x * f for x in vv] if kk in ("random", "random_int") else vv * f if kk == "value" else vv)
                     for kk, vv in v.items()} if isinstance(v, dict) else v * f
        if k in ("level_ppm", "level_pct_lel"):
            k = "level"
        out[k] = v
    return out


@dataclass
class Prepared:
    scenario: dict
    world: World
    views: List[DeviceView]
    events: list
    labels: Dict[str, List[Label]]                 # per device slug
    notes: List[str] = field(default_factory=list)

    def view(self, slug) -> DeviceView:
        return next(v for v in self.views if v.slug == slug)


def device_entries(scenario: dict, devices=None) -> list:
    """[(Device, Mount)] from the scenario's devices or the given list ({device, mount, height_m} or slugs)."""
    out = []
    for e in devices if devices is not None else scenario.get("devices", []):
        if isinstance(e, Device):
            e = {"device": e, "mount": "body"}
        elif isinstance(e, str):
            e = {"device": e}
        dev = e["device"] if isinstance(e["device"], Device) else Device.load(e["device"])
        out.append((dev, Mount(e.get("mount", "body"), float(e.get("height_m", 1.0)), float(e.get("heading_deg", 0.0)))))
    if not out:
        raise ScenarioError("a run needs at least one device")
    slugs = [d.slug for d, _ in out]
    if len(set(slugs)) != len(slugs):
        raise ScenarioError(f"a device appears twice in the run: {slugs}")
    return out


def _resolve_params(defn, spec, rng, measured):
    """Scenario values -> {name: {value, unit, source}}; choices first, so by_<param> can use them."""
    ctx, params = {"measured": measured}, {}
    keys = [k for k in spec if k not in ENTRY_KEYS]
    for k in keys:
        if k not in defn.PARAMS:
            raise ScenarioError(f"{defn.kind}: unknown parameter {k!r}; known: {list(defn.PARAMS)}")
    first = [k for k in keys if isinstance(spec[k], dict) and ({"choice", "choice_measured"} & set(spec[k]))]
    for k in first + [k for k in keys if k not in first]:
        params[k] = resolve(spec[k], rng, ctx, defn.PARAMS[k])
        ctx[k] = params[k]["value"]
    return params


def prepare(scenario, devices=None, seed: int = None, duration_s: float = None) -> Prepared:
    sc = load_scenario(scenario) if isinstance(scenario, str) else scenario
    seed = int(sc.get("seed", 0) if seed is None else seed)
    duration = parse_time(sc.get("duration", "8h")) if duration_s is None else float(duration_s)
    run = device_entries(sc, devices)
    world = World(sc["world"], duration, seed)
    views = [DeviceView(d, m) for d, m in run]
    measured = set().union(*(set(d.measured()) for d, _ in run))
    notes, events, labels = [], [], {v.slug: [] for v in views}
    by_kind = {}                                   # spacing_s keeps repeats of a kind apart, across entries
    lib = EVENTS
    for i, entry in enumerate(sc.get("events") or []):
        if len(entry) != 1:
            raise ScenarioError(f"event {i + 1}: write one event per list item, got {list(entry)}")
        kind, spec = next(iter(entry.items()))
        if kind not in lib:
            raise ScenarioError(f"event {i + 1}: unknown event {kind!r}; known: {', '.join(lib)}")
        defn = lib[kind]
        spec = _seconds_aliases(dict(spec or {}), defn.PARAMS)
        rng = np.random.default_rng([seed, zlib.crc32(f"{sc.get('name', '')}/event{i}".encode())])
        count = draw(spec.get("count", 1), rng, {})
        placed, same = [], by_kind.setdefault(kind, [])
        for _ in range(int(count)):
            ev = None
            for _try in range(200):
                params = _resolve_params(defn, spec, rng, measured)
                cand = defn(parse_time(draw(spec.get("at", 0), rng, {})), params, i)
                gap = float(spec.get("spacing_s", 0))
                if all(cand.end + gap <= p.at or cand.at >= p.end + gap for p in placed + same):
                    ev = cand
                    break
            if ev is None:
                notes.append(f"{kind} (entry {i + 1}): only {len(placed)} of {count} fit without overlap")
                break
            if ev.end > duration:
                raise ScenarioError(f"{kind} at {hms(ev.at)} ends at {hms(ev.end)}, after the run ({hms(duration)})")
            placed.append(ev)
        for ev in placed:
            _place(ev, spec, run, views, world, labels, notes)
            events.append(ev)
        same += placed
    for v in views:
        labels[v.slug] += expected_alerts(world, v)
        labels[v.slug].sort(key=lambda lb: (lb.start, lb.event))
    return Prepared(sc, world, views, events, labels, notes)


def _resolution(device, q):
    return min(m.resolution for _, qq, m in device.models() if qq == q)


def _snapshot(world, run, start, end):
    """What every device measures at its mount over [start, end]."""
    t_air = np.arange(start, end + 1e-9, world.air_dt)
    t_body = np.arange(start, end + 1e-9, world.body_dt)
    out = {}
    for d, m in run:
        view = world.view(m)
        q_body = None
        for q in d.measured():
            if q not in world.tracks:
                continue
            if CATALOG[q].vector:                  # what the sensor feels: the vector in the body frame
                q_body = view.at("body.orientation", t_body) if q_body is None else q_body
                out[(d.slug, q)] = rot.rotate(rot.conj(q_body), view.at(q, t_body))
            else:
                out[(d.slug, q)] = view.at(q, t_air)
    return out


def world_visibility(world, run, ev) -> dict:
    """Apply a world event and tell, per device, whether it changes something the device measures by at
    least that sensor's resolution: {slug: (True, "") or (False, why)}."""
    start, end = ev.at, min(ev.end + VISIBILITY_MARGIN_S, world.duration_s)
    before = _snapshot(world, run, start, end)
    n_eff, n_mot = len(world.effects), len(world.motion_effects)
    labels = ev.apply_world(world)
    try:
        world.evaluate()
    except ValueError as err:
        del world.effects[n_eff:], world.motion_effects[n_mot:]
        world.evaluate()
        raise ScenarioError(f"{ev.kind} at {hms(ev.at)}: {err}") from None
    after = _snapshot(world, run, start, end)
    seen = {}
    for d, m in run:
        best = None
        for q in d.measured():
            if (d.slug, q) not in before:
                continue
            change = float(np.max(np.abs(after[(d.slug, q)] - before[(d.slug, q)]))) if len(before[(d.slug, q)]) else 0.0
            res = _resolution(d, q)
            if change >= res:
                seen[d.slug] = (True, "")
                break
            if best is None or change / res > best[1] / best[2]:
                best = (q, change, res)
        else:
            why = "it changes nothing this device measures" if best is None or best[1] == 0 else \
                f"the largest change it causes ({best[0]}: {best[1]:.3g}) is below the sensor resolution ({best[2]:g})"
            if ev.body and m.kind == "fixed":
                why += "; the device is fixed, the event moves the body"
            seen[d.slug] = (False, why)
    return seen, labels, (n_eff, n_mot)


def _place(ev, spec, run, views, world, labels, notes):
    if ev.scope == "world":
        seen, lbs, (n_eff, n_mot) = world_visibility(world, run, ev)
        ok = [s for s, (v, _) in seen.items() if v]
        if not ok:
            del world.effects[n_eff:], world.motion_effects[n_mot:]
            world.evaluate()
            raise ScenarioError(f"{ev.kind} at {hms(ev.at)} cannot be placed: no device in this run can see it. "
                                + "; ".join(f"{s}: {why}" for s, (_, why) in seen.items()))
        for s, (v, why) in seen.items():
            if not v:
                notes.append(f"{ev.kind} at {hms(ev.at)} is not seen by {s}: {why}")
        for lb in lbs:
            for s in ok:
                labels[s].append(Label(lb.start, lb.end, lb.event, lb.detail, "world", tuple(ok)))
        return
    seen = {d.slug: ev.device_visible(d) for d, m in run}
    targets = spec.get("devices") or [s for s in seen]
    unknown = set(targets) - set(seen)
    if unknown:
        raise ScenarioError(f"{ev.kind}: devices {sorted(unknown)} are not in this run")
    bad = {s: seen[s][1] for s in targets if not seen[s][0]}
    if spec.get("devices") and bad:
        raise ScenarioError(f"{ev.kind} at {hms(ev.at)} cannot be placed on " +
                            "; ".join(f"{s}: {why}" for s, why in bad.items()))
    ok = [s for s in targets if seen[s][0]]
    if not ok:
        msg = f"{ev.kind} at {hms(ev.at)}: no device in this run supports it (" + \
              "; ".join(f"{s}: {why}" for s, why in bad.items()) + ")"
        if spec.get("optional"):
            notes.append(msg + "; skipped (optional)")
            return
        raise ScenarioError(msg)
    for s, why in bad.items():
        notes.append(f"{ev.kind} at {hms(ev.at)} is not given to {s}: {why}")
    for v in views:
        if v.slug in ok:
            for lb in ev.apply_device(v):
                labels[v.slug].append(Label(lb.start, lb.end, lb.event, lb.detail, "device", (v.slug,)))


def expected_alerts(world, view: DeviceView) -> List[Label]:
    """What the device's motion blocks should report, from the world's truth (core/logic/expected.py)."""
    from core.logic.expected import expected_labels
    return expected_labels(world, view)


def compatibility(devices=None, mount: str = "body", at_s: float = 1800.0, duration_s: float = 7200.0) -> list:
    """Rows of (event, {device slug: (True, "") or (False, why)}) for every event with default parameters;
    one row per choice of a quantity parameter (e.g. the gas). World events are tried in a probe world
    (the event's probe_world, default indoor_worker_walking), each device at the given mount."""
    from core.devices import list_devices
    devs = [Device.load(s) for s in (devices or list_devices())]
    run = [(d, Mount(mount)) for d in devs]
    rows = []
    for kind, defn in EVENTS.items():
        if defn.building_block:
            continue
        choice = next((k for k, p in defn.PARAMS.items() if p.get("choices") and
                       all(_is_quantity(c) for c in p["choices"])), None)
        variants = [(f"{kind} ({c})", {choice: {"value": c, "unit": "-", "source": "ASSUMPTION: table"}})
                    for c in defn.PARAMS[choice]["choices"]] if choice else [(kind, {})]
        for name, params in variants:
            ev = defn(at_s, params)
            if ev.scope == "device":
                qp = next((e["quantity"][1:] for e in defn.effects if isinstance(e.get("quantity"), str)
                           and e["quantity"].startswith("$")), None)
                cells = {}
                for d in devs:
                    p2 = dict(params)
                    if qp:
                        p2[qp] = {"value": next(iter(d.measured())), "unit": "-", "source": "ASSUMPTION: table"}
                    cells[d.slug] = defn(at_s, p2).device_visible(d)
                rows.append((f"{kind} (any measured quantity)" if qp else name, cells))
                continue
            world = World(defn.probe_world or PROBE_WORLD, duration_s, 1)
            try:
                seen, _, _ = world_visibility(world, run, ev)
            except ScenarioError as err:
                seen = {d.slug: (False, str(err).split(": ", 1)[-1]) for d in devs}
            rows.append((name, seen))
    return rows


def _is_quantity(name) -> bool:
    try:
        resolve_quantity(name)
        return True
    except KeyError:
        return False
