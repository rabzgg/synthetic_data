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
An event that no device of the run can see is refused with the reason.
"""
import os
import zlib
from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np
import yaml

from core.devices import Device
from core.world import Mount, World

from .base import GAS_Q, DeviceView, Label, ScenarioError, draw, has_feature, hms, parse_time, resolve
from .device_events import DEVICE_EVENTS
from .world_events import WORLD_EVENTS

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCENARIOS_DIR = os.path.join(ROOT, "configs", "scenarios")
EVENTS = {e.kind: e for e in WORLD_EVENTS + DEVICE_EVENTS}
ENTRY_KEYS = ("at", "count", "spacing_s", "devices", "optional")


def load_scenario(name: str, scenarios_dir: str = SCENARIOS_DIR) -> dict:
    path = os.path.join(scenarios_dir, f"{name}.yaml")
    if not os.path.exists(path):
        raise FileNotFoundError(f"scenario {name!r} not found in {scenarios_dir}")
    with open(path) as fh:
        return yaml.safe_load(fh)


def list_scenarios(scenarios_dir: str = SCENARIOS_DIR) -> list:
    return sorted(f[:-5] for f in os.listdir(scenarios_dir) if f.endswith(".yaml"))


def _seconds_aliases(params: dict) -> dict:
    out = {}
    for k, v in params.items():
        for suf, f in (("_min", 60), ("_h", 3600)):
            if k.endswith(suf):
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

    for i, entry in enumerate(sc.get("events") or []):
        if len(entry) != 1:
            raise ScenarioError(f"event {i + 1}: write one event per list item, got {list(entry)}")
        kind, spec = next(iter(entry.items()))
        if kind not in EVENTS:
            raise ScenarioError(f"event {i + 1}: unknown event {kind!r}; known: {', '.join(EVENTS)}")
        cls, spec = EVENTS[kind], _seconds_aliases(dict(spec or {}))
        rng = np.random.default_rng([seed, zlib.crc32(f"{sc.get('name', '')}/event{i}".encode())])
        count = draw(spec.get("count", 1), rng, {})
        placed, same = [], by_kind.setdefault(kind, [])
        for _ in range(int(count)):
            ev = None
            for _try in range(200):
                ctx = {"measured": measured}
                params = {}
                if "gas" in spec:
                    params["gas"] = resolve(spec["gas"], rng, ctx, cls.PARAMS.get("gas", {}))
                    ctx["gas"] = params["gas"]["value"]
                for k, v in spec.items():
                    if k in ENTRY_KEYS or k == "gas":
                        continue
                    if k not in cls.PARAMS:
                        raise ScenarioError(f"{kind}: unknown parameter {k!r}; known: {list(cls.PARAMS)}")
                    params[k] = resolve(v, rng, ctx, cls.PARAMS[k])
                if "level" in params and "gas" in params:
                    params["level"]["unit"] = {"lel": "%LEL"}.get(params["gas"]["value"], "ppm")
                at = draw(spec.get("at", 0), rng, ctx)
                cand = cls(parse_time(at), params, i)
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
    world.derive()
    for v in views:
        labels[v.slug] += expected_alerts(world, v)
        labels[v.slug].sort(key=lambda lb: (lb.start, lb.event))
    return Prepared(sc, world, views, events, labels, notes)


def _place(ev, spec, run, views, world, labels, notes):
    seen = {d.slug: ev.visible_to(d, m) for d, m in run}
    if ev.scope == "world":
        ok = [s for s, (v, _) in seen.items() if v]
        if not ok:
            raise ScenarioError(f"{ev.kind} at {hms(ev.at)} cannot be placed: no device in this run can see it. "
                                + "; ".join(f"{s}: {why}" for s, (_, why) in seen.items()))
        for s, (v, why) in seen.items():
            if not v:
                notes.append(f"{ev.kind} at {hms(ev.at)} is not seen by {s}: {why}")
        for lb in ev.apply_world(world):
            for s in ok:
                labels[s].append(Label(lb.start, lb.end, lb.event, lb.detail, "world", tuple(ok)))
        return
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


def _spans(segments, kinds):
    """(start, end) of runs of consecutive motion segments whose kind is in kinds."""
    out = []
    for s in segments:
        if s["kind"] in kinds:
            if out and abs(out[-1][1] - s["start"]) < 1e-9:
                out[-1] = (out[-1][0], s["end"])
            else:
                out.append((s["start"], s["end"]))
    return out


def expected_alerts(world, view: DeviceView) -> List[Label]:
    """What a device with fall / no-motion detection should do, from the world's motion (ground truth).
    no motion: pre-alarm after detect_s without any movement, alert after pre_alarm_s more, until the
    body moves again. fall: pre-alarm from the impact for pre_alarm_s, then an alert if the wearer is
    still on the ground (getting up within the pre-alarm counts as cancelling it)."""
    dev, out = view.device, []
    if view.mount.kind != "body":
        return out
    ma = dev.features.get("motion_alerts") or {}
    segs = world.motion.segments
    v = lambda x: x["value"] if isinstance(x, dict) else x
    if has_feature(dev, "motion_alerts.no_motion"):
        det, pre = v(ma["no_motion"]["detect_s"]), v(ma["no_motion"]["pre_alarm_s"])
        for s, e in _spans(segs, ["motionless"]):
            if e - s >= det:
                out.append(Label(s + det, min(e, s + det + pre), "no_motion_pre_alarm", f"after {det:g} s without motion", "expected", (dev.slug,)))
                if e > s + det + pre:
                    out.append(Label(s + det + pre, e, "no_motion_alert", "", "expected", (dev.slug,)))
    if has_feature(dev, "motion_alerts.fall"):
        pre = v(ma["fall"]["pre_alarm_s"])
        for s, e in _spans(segs, ["fall"]):
            ups = [x["start"] for x in segs if x["start"] >= e and (x["kind"] in ("rise", "walk") or
                                                                    (x["kind"] == "still" and x.get("posture") != "lying"))]
            t_up = min(ups) if ups else world.duration_s
            out.append(Label(e, min(t_up, e + pre), "fall_pre_alarm", "wearer can cancel by getting up", "expected", (dev.slug,)))
            if t_up > e + pre:
                out.append(Label(e + pre, t_up, "fall_alert", "", "expected", (dev.slug,)))
    return out


def compatibility(devices=None, mount: str = "body") -> list:
    """Rows of (event, {device slug: (True, "") or (False, why)}) for every event kind; gas releases per
    gas. With default parameters, devices worn on the body unless mount says otherwise."""
    from core.devices import list_devices
    devs = [Device.load(s) for s in (devices or list_devices())]
    m = Mount(mount)
    rows = []
    for kind, cls in EVENTS.items():
        variants = [(f"{kind} ({g})", {"gas": {"value": g, "unit": "-", "source": "ASSUMPTION: table"}})
                    for g in GAS_Q if g != "o2"] if kind == "gas_release" else [(kind, {})]
        for name, params in variants:
            if kind == "sensor_fault":          # on any quantity the device measures
                cells = {d.slug: cls(0.0, {"quantity": {"value": next(iter(d.measured())), "unit": "-",
                                                        "source": "ASSUMPTION: table"}}).visible_to(d, m) for d in devs}
                rows.append(("sensor_fault (any measured quantity)", cells))
                continue
            ev = cls(0.0, params)
            rows.append((name, {d.slug: ev.visible_to(d, m) for d in devs}))
    return rows
