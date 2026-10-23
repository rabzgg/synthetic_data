"""
primitives.py — the building blocks worlds and events are made of, written in YAML.

A spec is one of:
    a number or {value, unit, source}          a constant
    {ref: <name>}                              another node of the world (a signal or a driver)
    {<primitive>: {params}}                    one of the primitives below
    {sum: [spec, ...]}, {product: [spec, ...]} combine
    {lowpass: {of: spec, tau_s, start}}        first-order lag (thermal mass, inertia); starts at `start`
                                               (default: the first input value)
    {smooth: {of: spec, window_s}}             centred moving average
    {clip: {of: spec, min, max}}               bound the values
Parameters are numbers, {value, unit, source}, or (inside events) "$name" expressions of the event's
parameters, e.g. "$duration_s + 2 * $ramp_s".

Primitives (time t in seconds from the start of the world, or of the event inside an event):
    constant        value
    step            at_s, value, before (default 0)
    ramp            start_s, duration_s, from, to
    pulse           start_s, duration_s, level, ramp_s (default 0): 0 -> level -> 0, a trapezoid
    exp_rise_decay  start_s, level, rise_tau_s, hold_s, decay_tau_s: rises during hold_s, then decays
    periodic        amplitude, period_s, phase_s (default 0), offset (default 0): a sine
    duty_cycle      period_s, duty, on_value, off_value, transition_s (default 0), phase_s (default 0), jitter (default 0):
                    on for duty × period of every period; jitter varies each period by up to ± jitter × period
    daily_cycle     mean, amplitude, peak_hour: a cosine over 24 h (local time)
    random_walk     mean, sd, tau_s, smooth_s (default 0): mean-reverting (Ornstein-Uhlenbeck), then smoothed
    schedule        segments [[from_hour, to_hour, value], ...], default: by local hour of the day
    solar           latitude_deg, clear_sky, cloud_mean, cloud_sd, cloud_tau_s: daylight with clouds
    vapour_from_rh  rh_pct, temperature_c: the water vapour pressure of air at that RH and temperature
    integrate       start, inflow [specs], outflow [specs], lower, upper, per (s | min | h, the time unit of the
                    flows; default s), relax_to and relax_tau_s (optional): a stock, e.g. a tank level,
                    energy or a battery: level = start + ∫(Σ inflow − Σ outflow) dt − (level − relax_to)/relax_tau,
                    held within [lower, upper] (it stops at a bound, it does not pass it). Name the flows as
                    signals ({ref: ...}) so that an event can change one of them (a leak = an extra outflow).
    levels_on_walk  levels: a new level from the list each time the body starts walking (room lights)
    floors_on_walk  floor_height_m, floors, change_probability, stairs_s: floor changes during walks
"""
import ast
import operator
import re

import numpy as np
from scipy.signal import lfilter

from .physics import vapour_pressure


class SpecError(ValueError):
    pass


# expressions in event parameters
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.USub: operator.neg, ast.UAdd: operator.pos}


def _eval_expr(text: str, names: dict):
    node = ast.parse(re.sub(r"\$(\w+)", r"\1", text), mode="eval").body

    def ev(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.Name):
            if n.id not in names:
                raise SpecError(f"unknown parameter ${n.id} in {text!r}")
            return names[n.id]
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("min", "max"):
            return {"min": min, "max": max}[n.func.id](*(ev(a) for a in n.args))
        raise SpecError(f"only numbers, $parameters, + - * / and min / max are allowed: {text!r}")
    return ev(node)


def value(x, names: dict = None):
    """A parameter: number, {value, ...}, "$expr", or a time string -> its value."""
    names = names or {}
    if isinstance(x, dict) and "value" in x and not any(k in x for k in PRIMITIVES):
        return value(x["value"], names)
    if isinstance(x, str):
        s = x.strip()
        if "$" in s:
            if re.fullmatch(r"\$\w+", s):
                k = s[1:]
                if k not in names:
                    raise SpecError(f"unknown parameter {s}")
                return names[k]
            return _eval_expr(s, names)
        if re.fullmatch(r"\d+:\d{2}(:\d{2})?", s):
            h, m, *sec = s.split(":")
            return int(h) * 3600 + int(m) * 60 + (int(sec[0]) if sec else 0)
    return x


def _ou(n, dt, mean, sd, tau_s, rng, x0=None):
    if sd == 0:
        return np.full(n, float(mean))
    a = np.exp(-dt / tau_s)
    x0 = rng.normal(mean, sd) if x0 is None else x0
    drive = (1 - a) * mean + sd * np.sqrt(1 - a * a) * rng.normal(size=n)
    drive[0] = x0
    return lfilter([1.0], [1.0, -a], drive)


def _smooth(x, w: int):
    if w <= 1:
        return x
    p = np.pad(x, (w // 2, w - 1 - w // 2), mode="edge")
    c = np.concatenate([[0.0], np.cumsum(p)])
    return (c[w:] - c[:-w]) / w


def _solar_elevation_deg(hour_local, day_of_year, latitude_deg):
    decl = np.radians(23.44) * np.sin(2 * np.pi * (day_of_year - 81) / 365.0)
    ha = np.radians(15.0 * (hour_local - 12.0))
    lat = np.radians(latitude_deg)
    return np.degrees(np.arcsin(np.sin(lat) * np.sin(decl) + np.cos(lat) * np.cos(decl) * np.cos(ha)))


class Context:
    """What a spec is evaluated against: the time grid and the world around it."""

    def __init__(self, t, dt, hour=None, doy=None, rng=None, walks=(), node=None, names=None):
        self.t, self.dt, self.hour, self.doy = t, dt, hour, doy
        self.rng = rng or np.random.default_rng(0)
        self.walks, self.node, self.names = walks, node, names or {}

    def p(self, params, key, default=None):
        if key not in params:
            if default is None:
                raise SpecError(f"missing parameter {key!r}")
            return default
        return value(params[key], self.names)


def _constant(c, p):
    return np.full(len(c.t), float(c.p(p, "value") if isinstance(p, dict) else value(p, c.names)))


def _step(c, p):
    return np.where(c.t >= c.p(p, "at_s"), float(c.p(p, "value")), float(c.p(p, "before", 0.0)))


def _ramp(c, p):
    s, d, a, b = c.p(p, "start_s"), c.p(p, "duration_s"), c.p(p, "from"), c.p(p, "to")
    f = np.clip((c.t - s) / d, 0, 1) if d > 0 else (c.t >= s).astype(float)
    return a + (b - a) * f


def _pulse(c, p):
    s, d, lv, r = c.p(p, "start_s", 0.0), c.p(p, "duration_s"), c.p(p, "level"), c.p(p, "ramp_s", 0.0)
    t = c.t
    if r <= 0:
        return np.where((t >= s) & (t < s + d), float(lv), 0.0)
    up = np.clip((t - s) / r, 0, 1)
    down = np.clip((s + 2 * r + d - t) / r, 0, 1)
    return lv * np.minimum(up, down) * (t >= s)


def _exp_rise_decay(c, p):
    s, lv = c.p(p, "start_s", 0.0), c.p(p, "level")
    rise, hold, decay = c.p(p, "rise_tau_s"), c.p(p, "hold_s"), c.p(p, "decay_tau_s")
    t = c.t
    up = lv * (1 - np.exp(-np.clip(t - s, 0, hold) / rise))
    peak = lv * (1 - np.exp(-hold / rise))
    return np.where(t < s, 0.0, np.where(t <= s + hold, up, peak * np.exp(-(t - s - hold) / decay)))


def _periodic(c, p):
    return c.p(p, "offset", 0.0) + c.p(p, "amplitude") * np.sin(
        2 * np.pi * (c.t - c.p(p, "phase_s", 0.0)) / c.p(p, "period_s"))


def _duty_cycle(c, p):
    per, duty, on, off = c.p(p, "period_s"), c.p(p, "duty"), c.p(p, "on_value"), c.p(p, "off_value")
    trans, phase, jit = c.p(p, "transition_s", 0.0), c.p(p, "phase_s", 0.0), c.p(p, "jitter", 0.0)
    t = c.t - phase
    span = t[-1] - min(t[0], 0) + 2 * per
    n_cyc = int(span / (per * (1 - min(jit, 0.9)))) + 2
    lengths = per * (1 + jit * c.rng.uniform(-1, 1, n_cyc)) if jit else np.full(n_cyc, per)
    starts = np.concatenate([[min(t[0], 0) - per], min(t[0], 0) - per + np.cumsum(lengths)])
    k = np.clip(np.searchsorted(starts, t, side="right") - 1, 0, n_cyc - 1)
    is_on = (t - starts[k]) < duty * lengths[k]
    x = np.where(is_on, float(on), float(off))
    return _smooth(x, int(round(trans / c.dt))) if trans > 0 else x


def _daily_cycle(c, p):
    return c.p(p, "mean") + c.p(p, "amplitude") * np.cos(2 * np.pi * (c.hour - c.p(p, "peak_hour")) / 24.0)


def _random_walk(c, p):
    x = _ou(len(c.t), c.dt, c.p(p, "mean"), c.p(p, "sd"), c.p(p, "tau_s"), c.rng)
    w = int(round(c.p(p, "smooth_s", 0.0) / c.dt))
    return _smooth(x, w)


def _schedule(c, p):
    x = np.full(len(c.t), float(c.p(p, "default")))
    for seg in value(p["segments"], c.names):
        a, b, v = (value(z, c.names) for z in seg)
        on = (c.hour >= a) & (c.hour < b) if a <= b else (c.hour >= a) | (c.hour < b)
        x[on] = float(v)
    return x


def _solar(c, p):
    el = _solar_elevation_deg(c.hour, c.doy, c.p(p, "latitude_deg"))
    cloud = np.clip(_ou(len(c.t), c.dt, c.p(p, "cloud_mean"), c.p(p, "cloud_sd"), c.p(p, "cloud_tau_s"), c.rng), 0.05, 1.0)
    return c.p(p, "clear_sky") * np.clip(np.sin(np.radians(el)), 0, None) * cloud


def _vapour_from_rh(c, p):
    return np.full(len(c.t), float(vapour_pressure(c.p(p, "temperature_c"), c.p(p, "rh_pct"))))


def _integrate(c, p):
    per = {"s": 1.0, "min": 60.0, "h": 3600.0}[str(c.p(p, "per", "s"))]
    flow = np.zeros(len(c.t))
    for s in value(p.get("inflow", []), c.names) or []:
        flow = flow + evaluate(s, c)
    for s in value(p.get("outflow", []), c.names) or []:
        flow = flow - evaluate(s, c)
    step = flow * c.dt / per
    lo, hi = float(c.p(p, "lower", -np.inf)), float(c.p(p, "upper", np.inf))
    relax = "relax_tau_s" in p
    to, k = (float(c.p(p, "relax_to")), c.dt / float(c.p(p, "relax_tau_s"))) if relax else (0.0, 0.0)
    out = np.empty(len(c.t))
    x = float(c.p(p, "start"))
    for i in range(len(c.t)):
        out[i] = x
        x = min(hi, max(lo, x + step[i] - k * (x - to)))
    return out


def _levels_on_walk(c, p):
    levels = np.asarray(value(p["levels"], c.names), float)
    x = np.full(len(c.t), c.rng.choice(levels))
    for s, _ in c.walks:
        x[c.t >= s] = c.rng.choice(levels)
    return x


def _floors_on_walk(c, p):
    h, top = c.p(p, "floor_height_m"), int(c.p(p, "floors"))
    prob, stairs = c.p(p, "change_probability"), c.p(p, "stairs_s")
    x, floor = np.zeros(len(c.t)), 0
    for s, e in c.walks:
        if c.rng.random() < prob and top > 0:
            new = int(np.clip(floor + c.rng.choice([-1, 1]), 0, top))
            ramp = np.clip((c.t - s) / min(stairs, e - s), 0, 1)
            x = np.where(c.t >= s, floor * h + (new - floor) * h * ramp, x)
            floor = new
    return x


PRIMITIVES = {"constant": _constant, "step": _step, "ramp": _ramp, "pulse": _pulse, "exp_rise_decay": _exp_rise_decay,
              "periodic": _periodic, "duty_cycle": _duty_cycle, "daily_cycle": _daily_cycle,
              "random_walk": _random_walk, "schedule": _schedule, "solar": _solar, "vapour_from_rh": _vapour_from_rh,
              "integrate": _integrate, "levels_on_walk": _levels_on_walk, "floors_on_walk": _floors_on_walk}
OPERATORS = ("ref", "sum", "product", "lowpass", "smooth", "clip")


def evaluate(spec, c: Context) -> np.ndarray:
    """Values of a spec on c.t."""
    n = len(c.t)
    if isinstance(spec, (int, float)) and not isinstance(spec, bool):
        return np.full(n, float(spec))
    if isinstance(spec, str):
        return np.full(n, float(value(spec, c.names)))
    if not isinstance(spec, dict):
        raise SpecError(f"cannot read {spec!r} as a signal")
    keys = [k for k in spec if k in PRIMITIVES or k in OPERATORS]
    if not keys:
        if "value" in spec:
            return np.full(n, float(value(spec, c.names)))
        raise SpecError(f"unknown signal {list(spec)}; primitives: {', '.join(PRIMITIVES)}; operators: "
                        f"{', '.join(OPERATORS)}")
    if len(keys) > 1:
        raise SpecError(f"one primitive or operator per spec, got {keys}")
    k, p = keys[0], spec[keys[0]]
    if k in PRIMITIVES:
        return np.asarray(PRIMITIVES[k](c, p if p is not None else {}), float)
    if k == "ref":
        if c.node is None:
            raise SpecError("ref is only possible inside a world")
        return c.node(p)
    if k == "sum":
        return np.sum([evaluate(s, c) for s in p], axis=0)
    if k == "product":
        return np.prod([evaluate(s, c) for s in p], axis=0)
    x = evaluate(p["of"], c)
    if k == "lowpass":
        a = np.exp(-c.dt / c.p(p, "tau_s"))
        y0 = float(c.p(p, "start", x[0]))          # causal: never from later values
        return lfilter([1 - a], [1, -a], x, zi=[a * y0])[0]
    if k == "smooth":
        return _smooth(x, int(round(c.p(p, "window_s") / c.dt)))
    lo, hi = c.p(p, "min", -np.inf), c.p(p, "max", np.inf)
    return np.clip(x, lo, hi)


def references(spec) -> set:
    """Names a spec refers to (for the evaluation order of a world)."""
    if isinstance(spec, dict):
        out = {spec["ref"]} if "ref" in spec else set()
        for v in spec.values():
            out |= references(v)
        return out
    if isinstance(spec, list):
        return set().union(*(references(v) for v in spec)) if spec else set()
    return set()
