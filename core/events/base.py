"""
base.py — block [E]: the pieces events and scenarios share: labels, the per-device view of a run,
device features, times and random scenario values. Events themselves are data (library.py).

An event changes the world (its nodes or the motion plan; the world then derives everything again)
or one device (what its sensors are given, its states, its connection). It never writes a CSV column.

Every parameter is {value, unit, source}; defaults carry their own source. A scenario may give a
plain value (source "ASSUMPTION: scenario value") or a random draw: {random: [lo, hi]},
{random_int: [lo, hi]}, {choice: [...]}, {choice_measured: [...]} (a gas some device measures), and
{by_<param>: {choice: value}} for a value that depends on another drawn parameter (e.g. by_gas).
"""
import re
from dataclasses import dataclass, field

SCENARIO_VALUE = "ASSUMPTION: scenario value"


class ScenarioError(ValueError):
    pass


class Reason(str):
    """Why an event does not fit: the string itself is the technical reason (logs, errors, docs/EVENTS.md),
    .plain is one sentence for the UI."""
    def __new__(cls, text: str, plain: str = ""):
        r = super().__new__(cls, text)
        r.plain = plain or text
        return r


def columns_of(quantities) -> str:
    """CSV columns of quantity ids in plain words: 'temperature_c and accel_x,y,z_g'."""
    from core.quantities import CATALOG
    cols = [CATALOG[q].column.replace("{axis}", ",".join(CATALOG[q].axes)) if CATALOG[q].vector else CATALOG[q].column
            for q in quantities]
    return cols[0] if len(cols) == 1 else ", ".join(cols[:-1]) + " and " + cols[-1]


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
    """bump_test, connectivity, battery, states.<s>, motion_alerts.<fall | no_motion>: from the device's logic."""
    return feature in device.capabilities()


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
        from core.quantities import resolve as rq
        opts = [g for g in spec["choice_measured"] if rq(g) in ctx.get("measured", ())]
        if not opts:
            raise ScenarioError(f"none of {spec['choice_measured']} is measured by a device in this run")
        return opts[int(rng.integers(len(opts)))]
    by = next((k for k in spec if k.startswith("by_")), None)
    if by:
        g = ctx.get(by[3:])
        if g not in spec[by]:
            raise ScenarioError(f"no value for {by[3:]} {g!r} in {by} {list(spec[by])}")
        return draw(spec[by][g], rng, ctx)
    if "value" in spec:
        return spec["value"]
    return spec
