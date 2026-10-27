"""
library.py — events as data (configs/events/*.yaml) and the one generic engine that applies them.

An event file:

    kind: gas_release
    name: Gas release
    description: "One sentence for the UI."
    params:                                   # every parameter {value, unit, source}; choices optional
      gas: {value: h2s, unit: "-", source: "...", choices: [lel, co, h2s, voc, co2]}
      level: {value: 20, unit: "gas unit", source: "..."}
      duration_s: {value: 600, unit: s, source: "..."}
      ramp_s: {value: 30, unit: s, source: "..."}
    duration: "$duration_s + 2 * $ramp_s"     # optional; default $duration_s, or 0
    label: "{gas.upper} {level} {gas.unit}"   # detail of the label
    effects:
      - {target: "$gas", op: add, shape: {pulse: {duration_s: $duration_s, ramp_s: $ramp_s, level: $level}}}

Effects on the world (target = a world node: a quantity id, a short alias such as h2s, a relation
input, or a named signal of the world):
    op: add | multiply   shape: a spec (core/world/primitives.py) in time since the event start
    op: set             value: a spec, during the event
    op: approach        value: a spec, tau_s: moves towards the value during the event; afterwards back
                        with recovery_tau_s (instantly without it)
    after: revert       (default) the effect ends with the event: the node goes back (add 0, multiply 1,
                        set / approach released)
    after: hold         what the effect reached at the end stays for the rest of the run (wear, damage)
    optional: true      skip the effect in a world without that node
Effects on the body: {target: motion, segments: [{kind, duration, posture, needs, label}]}, one after
the other from the event start (kinds in core/world/motion.py; posture current keeps the posture).
Effects on a device (scope: device; requires: [device features]):
    {target: device.input, quantity, op: set | add | stuck | zero | offset, value}   what a sensor is given
    {target: device.input, quantities: $mix, op: set}                                 several, from a mapping
    {target: device.gap}                      no rows written
    {target: device.state, state: pump}       a device state is on
    {target: device.battery, extra_pct_per_h} faster drain
    after: hold on a device effect keeps it to the end of the run (a sensor that stays broken)
A composite event has steps instead of effects: [{event, at or after, params, label}]; at = offset from
the start, after = gap after the previous step's end; params are expressions of the composite's own.
building_block: true marks a small event meant for composites (left out of lists and tables).
missing: the sentence the UI shows when the environment or the device lacks what the event needs
    ("This environment has no air conditioner.", "This device has no sampling pump.").
probe_world: the world to try a world event in when no run is given (compatibility tables).
"""
import glob
import os
import re

import numpy as np
import yaml

from core.quantities import CATALOG, resolve as resolve_quantity
from core.quantities.measurement import check_source
from core.world.primitives import SpecError, value as pvalue

from .base import Label, Reason, ScenarioError, columns_of, has_feature

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EVENTS_DIR = os.path.join(ROOT, "configs", "events")
KEYS = {"kind", "name", "description", "scope", "params", "duration", "label", "effects", "steps", "requires",
        "probe_world", "building_block", "missing"}
DEVICE_TARGETS = ("device.input", "device.gap", "device.state", "device.battery")


class EventDef:
    def __init__(self, d: dict, path: str = ""):
        unknown = set(d) - KEYS
        if unknown:
            raise ScenarioError(f"event file {os.path.basename(path)}: unknown key(s) {sorted(unknown)}")
        self.kind, self.name, self.description = d["kind"], d.get("name", d["kind"]), d.get("description", "")
        self.PARAMS = {k: dict(v) for k, v in (d.get("params") or {}).items()}
        for k, p in self.PARAMS.items():
            check_source(f"{self.kind}.{k}", p)
        self.effects, self.steps = d.get("effects") or [], d.get("steps") or []
        if bool(self.effects) == bool(self.steps):
            raise ScenarioError(f"event {self.kind}: give effects or steps (a composite), one of the two")
        targets = [e.get("target", "") for e in self.effects]
        self.scope = d.get("scope") or ("device" if targets and all(t in DEVICE_TARGETS for t in targets) else "world")
        self.body = any(t == "motion" for t in targets)
        self.requires_ = list(d.get("requires") or [])
        self.duration_expr = d.get("duration", "$duration_s" if "duration_s" in self.PARAMS else 0)
        self.label_tpl = d.get("label", "")
        self.probe_world = d.get("probe_world")
        self.building_block = bool(d.get("building_block", False))     # used inside composites, not on its own
        self.missing = d.get("missing", "")                            # UI sentence when a world or device lacks it
        self.path = path

    def __call__(self, at_s=0.0, params=None, index=0):
        return Instance(self, at_s, params, index)

    def describe(self) -> dict:
        return {"kind": self.kind, "name": self.name, "description": self.description, "scope": self.scope,
                "body_only": self.body, "params": self.PARAMS, "requires": self.requires_,
                "composite": [s["event"] for s in self.steps]}


def load_events(directory: str = EVENTS_DIR) -> dict:
    out = {}
    for f in sorted(glob.glob(os.path.join(directory, "*.yaml"))):
        with open(f) as fh:
            d = EventDef(yaml.safe_load(fh), f)
        if d.kind in out:
            raise ScenarioError(f"event {d.kind} defined twice")
        out[d.kind] = d
    for d in out.values():
        for s in d.steps:
            if s["event"] not in out:
                raise ScenarioError(f"event {d.kind}: step {s['event']!r} is not a known event")
    for d in out.values():                         # a composite moves the body if one of its steps does
        if d.steps:
            d.body = any(out[s["event"]].body for s in d.steps)
    return out


def _fmt(x):
    if isinstance(x, float):
        return f"{x:.3g}"
    return str(x)


class Instance:
    """One placed event: its definition, start time and resolved parameters."""

    def __init__(self, defn: EventDef, at_s: float, params: dict = None, index: int = 0):
        self.defn, self.at, self.index = defn, float(at_s), index
        self.kind, self.scope, self.body = defn.kind, defn.scope, defn.body
        unknown = set(params or {}) - set(defn.PARAMS)
        if unknown:
            raise ScenarioError(f"{self.kind}: unknown parameter(s) {sorted(unknown)}; known: {list(defn.PARAMS)}")
        self.params = {k: dict(v) for k, v in defn.PARAMS.items()}
        for k, v in (params or {}).items():
            check_source(f"{self.kind}.{k}", v)
            self.params[k] = dict(v)
        for k, p in self.params.items():
            if "choices" in defn.PARAMS[k] and p["value"] not in defn.PARAMS[k]["choices"]:
                raise ScenarioError(f"{self.kind}: {k} must be one of {defn.PARAMS[k]['choices']}, got {p['value']!r}")
        for k, p in self.params.items():           # "<param> unit": the unit of the quantity that param names
            ref = str(p.get("unit", "")).removesuffix(" unit")
            if ref != p.get("unit") and ref in self.params and isinstance(self.params[ref]["value"], str):
                try:
                    p["unit"] = CATALOG[resolve_quantity(self.params[ref]["value"])].unit
                except KeyError:
                    pass
        self.names = {k: p["value"] for k, p in self.params.items()}
        self.children = []                      # (instance, label) of a composite, set by apply

    def p(self, name):
        return self.params[name]["value"]

    def ev(self, x):
        try:
            return pvalue(x, self.names)
        except SpecError as e:
            raise ScenarioError(f"{self.kind}: {e}") from None

    def duration_s(self) -> float:
        if self.defn.steps:
            steps = self._steps()
            return max(end for _, end, _ in steps) - self.at if steps else 0.0
        return float(self.ev(self.defn.duration_expr))

    @property
    def end(self) -> float:
        return self.at + self.duration_s()

    def detail(self) -> str:
        def field(m):
            name, _, attr = m.group(1).partition(".")
            v = self.names.get(name, m.group(0))
            if attr in ("unit", "name"):
                q = CATALOG.get(resolve_quantity(v)) if isinstance(v, str) else None
                return getattr(q, attr) if q else ""
            if attr == "upper":
                return str(v).upper()
            return _fmt(v)
        return re.sub(r"\{([\w.]+)\}", field, self.defn.label_tpl).strip()

    # composite
    def _steps(self):
        """[(child instance, end, label)] of a composite, placed one after the other."""
        out, prev_end = [], self.at
        for s in self.defn.steps:
            child_def = EVENTS[s["event"]]
            params = {}
            for k, x in (s.get("params") or {}).items():
                src = self.params[x[1:]]["source"] if isinstance(x, str) and re.fullmatch(r"\$\w+", x) and \
                    x[1:] in self.params else f"ASSUMPTION: set by the {self.kind} event"
                unit = child_def.PARAMS.get(k, {}).get("unit", "-")
                params[k] = {"value": self.ev(x), "unit": unit, "source": src}
            start = self.at + float(self.ev(s["at"])) if "at" in s else prev_end + float(self.ev(s.get("after", 0)))
            child = child_def(start, params, self.index)
            out.append((child, child.end, s.get("label", s["event"])))
            prev_end = child.end
        return out

    # what it touches
    def requires(self):
        if self.defn.steps:
            return []
        return list(self.defn.requires_)

    def inputs(self) -> list:
        """Quantities a device event gives to a sensor."""
        out = []
        for e in self.defn.effects:
            if e.get("target") != "device.input":
                continue
            if "quantities" in e:
                out += [resolve_quantity(k) for k in self.ev(e["quantities"])]
            else:
                out.append(resolve_quantity(self.ev(e["quantity"])))
        return out

    def affects(self) -> list:
        """World nodes it changes (quantity ids where the target is a quantity)."""
        if self.defn.steps:
            return sorted({a for c, _, _ in self._steps() for a in c.affects()})
        out = []
        for e in self.defn.effects:
            t = e.get("target", "")
            if t == "motion":
                out += ["body.accel_g", "body.gyro_dps"]
            elif t not in DEVICE_TARGETS:
                name = self.ev(t)
                try:
                    out.append(resolve_quantity(name))
                except KeyError:
                    out.append(name)
        return out + self.inputs()

    def device_visible(self, device) -> tuple:
        """For device events: the device has the features and measures what it is given."""
        missing = [r for r in self.requires() if not has_feature(device, r)]
        if missing:
            return False, Reason(f"it needs the device feature {', '.join(missing)}",
                                 self.defn.missing or "This device does not have what this event needs.")
        ins = self.inputs()
        if ins and not set(ins) & set(device.measured()):
            return False, Reason(f"the device measures none of {', '.join(ins)}",
                                 f"This device does not measure {columns_of(ins)}.")
        return True, ""

    # applying
    def apply_world(self, world) -> list:
        """Effects into the world (not evaluated yet). Returns labels (without devices)."""
        if self.defn.steps:
            labels = [Label(self.at, self.end, self.kind, self.detail(), "world")]
            for child, _, name in self._steps():
                if child.duration_s() <= 0:
                    continue
                if child.scope == "device":
                    raise ScenarioError(f"{self.kind}: step {child.kind} is a device event; composites take world events")
                sub = child.apply_world(world)
                labels.append(Label(child.at, child.end, f"{self.kind}:{name}", child.detail() or sub[0].detail, "world"))
            return labels
        labels = [Label(self.at, self.end, self.kind, self.detail(), "world")]
        for e in self.defn.effects:
            t = e.get("target", "")
            if t == "motion":
                segs, t0 = [], self.at
                for sg in e["segments"]:
                    d = float(self.ev(sg["duration"]))
                    segs.append({"kind": sg["kind"], "duration": d, "posture": sg.get("posture", "upright"),
                                 "needs": sg.get("needs")})
                    if sg.get("label") and d > 0:
                        labels.append(Label(t0, t0 + d, f"{self.kind}:{sg['label']}", "", "world"))
                    t0 += d
                world.add_motion(self.at, segs)
                continue
            node = self._node(world, t)
            if node is None:
                if e.get("optional"):
                    continue
                raise ScenarioError(f"{self.kind}: world {world.name} has no {self.ev(t)!r} "
                                    f"(nodes: {', '.join(world.nodes())})")
            eff = {"target": node, "op": e.get("op", "add"), "at": self.at, "end": self.end, "names": self.names,
                   "rng_stream": f"event{self.index}/{self.kind}/{self.at}"}
            for k in ("shape", "value", "tau_s", "recovery_tau_s", "after"):
                if k in e:
                    eff[k] = e[k]
            world.add_effect(eff)
        return labels

    def _node(self, world, target):
        name = self.ev(target)
        if name in world.nodes():
            return name
        try:
            q = resolve_quantity(name)
        except KeyError:
            return None
        return q if q in world.nodes() else None

    def apply_device(self, view) -> list:
        given = []
        for e in self.defn.effects:
            t = e["target"]
            if e.get("after", "revert") not in ("hold", "revert"):
                raise ScenarioError(f"{self.kind}: after must be hold or revert")
            end = np.inf if e.get("after") == "hold" else self.end
            if t == "device.input":
                op = self.ev(e.get("op", "set"))
                if op not in ("set", "add", "stuck", "zero", "offset"):
                    raise ScenarioError(f"{self.kind}: input op must be set, add, stuck, zero or offset")
                pairs = list(self.ev(e["quantities"]).items()) if "quantities" in e else \
                    [(self.ev(e["quantity"]), self.ev(e.get("value", 0)))]
                for qname, val in pairs:
                    q = resolve_quantity(qname)
                    if q in view.device.measured():
                        view.overrides.append((q, self.at, end, "value" if op == "set" else op, float(val)))
                        given.append(f"{CATALOG[q].alias or q} {_fmt(float(val))}")
            elif t == "device.gap":
                view.gaps.append((self.at, end))
            elif t == "device.state":
                view.states.setdefault(e["state"], []).append((self.at, end))
            elif t == "device.battery":
                view.battery.append((self.at, end, float(self.ev(e["extra_pct_per_h"]))))
        detail = self.detail() or (", ".join(given) if given else "")
        return [Label(self.at, self.end, self.kind, detail, "device")]


EVENTS = load_events()
