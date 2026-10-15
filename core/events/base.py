"""
base.py — block [E]: what an event is, how it says what it touches, and the labels it leaves.

An event changes the world (drivers or the motion plan; the world then derives everything again) or
changes one device (what its sensors are given, its states, its connection). It never writes a CSV
column. Each event declares
    affects    the world quantities it changes; a device sees it only if it measures one of them
    requires   device features it needs (device events), e.g. bump_test, connectivity, states.pump
    body       True if it only reaches devices worn on the moving body (falls, no motion)
Compatibility follows from those three, so an event that no device in a run can see is refused
with the reason, never dropped silently.

Every parameter is {value, unit, source}; defaults carry their own source. A scenario may give a
plain value (source "ASSUMPTION: scenario value") or a random draw: {random: [lo, hi]},
{random_int: [lo, hi]}, {choice: [...]}, {choice_measured: [...]} (a gas some device measures), and
{by_gas: {gas: value}} for a value that depends on the drawn gas.
"""
import re
from dataclasses import dataclass, field
from typing import ClassVar, Dict, List

import numpy as np

from core.quantities.measurement import check_source

GAS_Q = {"lel": "air.lel_pct", "co": "air.co_ppm", "h2s": "air.h2s_ppm", "voc": "air.voc_ppm", "co2": "air.co2_ppm",
         "o2": "air.o2_pct"}
GAS_UNIT = {"lel": "%LEL", "co": "ppm", "h2s": "ppm", "voc": "ppm", "co2": "ppm", "o2": "%vol"}
SCENARIO_VALUE = "ASSUMPTION: scenario value"


class ScenarioError(ValueError):
    pass


def parse_time(x) -> float:
    """Seconds from a number, "HH:MM[:SS]", or "90s" / "20min" / "8h"."""
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    m = re.fullmatch(r"(\d+):(\d{2})(?::(\d{2}(?:\.\d+)?))?", s)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3) or 0)
    m = re.fullmatch(r"([\d.]+)\s*(s|min|h)", s)
    if m:
        return float(m.group(1)) * {"s": 1, "min": 60, "h": 3600}[m.group(2)]
    raise ScenarioError(f"cannot read the time {x!r}; use seconds, HH:MM:SS, or 90s / 20min / 8h")


def hms(t: float) -> str:
    t = int(round(t))
    return f"{t // 3600:02d}:{t // 60 % 60:02d}:{t % 60:02d}"


@dataclass
class Label:
    start: float
    end: float
    event: str
    detail: str = ""
    scope: str = "world"          # world | device | expected (what the device should do)
    devices: tuple = ()           # slugs of the devices that see it

    def row(self) -> dict:
        return {"start_s": round(self.start, 3), "end_s": round(self.end, 3), "event": self.event,
                "detail": self.detail, "scope": self.scope}


@dataclass
class DeviceView:
    """One device in a run: where it sits, and what device events did to it."""
    device: object                                   # core.devices.Device
    mount: object                                    # core.world.Mount
    overrides: list = field(default_factory=list)    # (quantity, start, end, mode, value): what the sensor is given
    gaps: list = field(default_factory=list)         # (start, end): no rows written
    states: dict = field(default_factory=dict)       # state -> [(start, end)]
    battery: list = field(default_factory=list)      # (start, end, extra % per hour)
    labels: list = field(default_factory=list)

    @property
    def slug(self):
        return self.device.slug


def has_feature(device, feature: str) -> bool:
    f = device.features
    if feature == "bump_test":
        return bool(device.feature("bump_test"))
    if feature == "connectivity":
        return bool(f.get("connectivity"))
    if feature == "battery":
        return bool(f.get("battery_hours"))
    if feature.startswith("states."):
        st = (f.get("states") or {}).get(feature.split(".", 1)[1])
        return bool(st and st.get("value"))
    if feature.startswith("motion_alerts."):
        ma = (f.get("motion_alerts") or {}).get(feature.split(".", 1)[1])
        return bool(ma and ma.get("value"))
    raise KeyError(feature)


class Event:
    kind: ClassVar[str] = ""
    name: ClassVar[str] = ""
    description: ClassVar[str] = ""           # one sentence, for the UI
    scope: ClassVar[str] = "world"            # world | device
    body: ClassVar[bool] = False
    PARAMS: ClassVar[Dict[str, dict]] = {}

    def __init__(self, at_s: float, params: dict = None, index: int = 0):
        self.at = float(at_s)
        self.index = index
        unknown = set(params or {}) - set(self.PARAMS)
        if unknown:
            raise ScenarioError(f"{self.kind}: unknown parameter(s) {sorted(unknown)}; known: {list(self.PARAMS)}")
        self.params = {k: dict(v) for k, v in self.PARAMS.items()}
        for k, v in (params or {}).items():
            check_source(f"{self.kind}.{k}", v)
            self.params[k] = dict(v)

    def p(self, name):
        return self.params[name]["value"]

    # what it touches
    def affects(self) -> List[str]:
        return []

    def requires(self) -> List[str]:
        return []

    def duration_s(self) -> float:
        return float(self.p("duration_s")) if "duration_s" in self.params else 0.0

    @property
    def end(self) -> float:
        return self.at + self.duration_s()

    def visible_to(self, device, mount) -> tuple:
        """(True, "") or (False, why not) for one device at its mount."""
        if self.body and mount.kind != "body":
            return False, "it only reaches devices worn on the body; this one is fixed"
        missing = [r for r in self.requires() if not has_feature(device, r)]
        if missing:
            return False, f"it needs the device feature {', '.join(missing)}"
        aff = self.affects()
        if aff and not set(aff) & set(device.measured()):
            return False, f"the device measures none of {', '.join(aff)}"
        return True, ""

    # what it does
    def apply_world(self, world) -> List[Label]:
        return []

    def apply_device(self, view: DeviceView) -> List[Label]:
        return []

    def label(self, detail="", start=None, end=None, event=None, scope=None) -> Label:
        return Label(self.at if start is None else start, self.end if end is None else end, event or self.kind, detail,
                     scope or ("device" if self.scope == "device" else "world"))

    def describe(self) -> dict:
        return {"kind": self.kind, "name": self.name, "description": self.description, "scope": self.scope,
                "body_only": self.body, "params": self.PARAMS}


def trapezoid(t, start, ramp, hold, level):
    """0 -> level over ramp, level for hold, back to 0 over ramp (ramp 0 = a step)."""
    if ramp <= 0:
        return np.where((t >= start) & (t < start + hold), level, 0.0)
    up = np.clip((t - start) / ramp, 0, 1)
    down = np.clip((start + ramp + hold + ramp - t) / ramp, 0, 1)
    return level * np.minimum(up, down) * (t >= start)


def resolve(spec, rng, ctx: dict, default: dict):
    """Scenario value -> {value, unit, source}. ctx: measured gases, the drawn gas."""
    if isinstance(spec, dict) and "source" in spec and "value" in spec:
        return dict(spec, unit=spec.get("unit", default.get("unit", "-")))
    src = spec.get("source", SCENARIO_VALUE) if isinstance(spec, dict) else SCENARIO_VALUE
    unit = (spec.get("unit") if isinstance(spec, dict) else None) or default.get("unit", "-")
    val = draw(spec, rng, ctx)
    return {"value": val, "unit": unit, "source": src}


def draw(spec, rng, ctx):
    if not isinstance(spec, dict):
        return spec
    if "random" in spec:
        lo, hi = spec["random"]
        if isinstance(lo, str) or isinstance(hi, str):
            return float(rng.uniform(parse_time(lo), parse_time(hi)))
        return float(rng.uniform(lo, hi))
    if "random_int" in spec:
        lo, hi = spec["random_int"]
        return int(rng.integers(lo, hi + 1))
    if "choice" in spec:
        return spec["choice"][int(rng.integers(len(spec["choice"])))]
    if "choice_measured" in spec:
        opts = [g for g in spec["choice_measured"] if GAS_Q.get(g) in ctx.get("measured", ())]
        if not opts:
            raise ScenarioError(f"none of the gases {spec['choice_measured']} is measured by a device in this run")
        return opts[int(rng.integers(len(opts)))]
    if "by_gas" in spec:
        g = ctx.get("gas")
        if g not in spec["by_gas"]:
            raise ScenarioError(f"no value for gas {g!r} in by_gas {list(spec['by_gas'])}")
        return draw(spec["by_gas"][g], rng, ctx)
    if "value" in spec:
        return spec["value"]
    return spec
