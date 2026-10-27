"""
world.py — block [D]: one timeline of physical truth that every sensor in a run reads.

A world is a preset file (configs/worlds/<name>.yaml) made of
    realism    ASSUMPTION or recorded (required)
    signals    named helper signals (e.g. a compressor that is on or off), not quantities
    drivers    one spec per quantity id (configs/quantities/) or relation input (below)
    setting    indoor or outdoor (events such as a door opening only happen indoors; leave it out when
               it does not matter)
and optionally grid, time, earth_field_ut and motion (how the body moves, core/world/motion.py);
what is left out gets the defaults below (DEFAULTS, each an ASSUMPTION, listed in the manifest). A
world without people or movement only needs realism, signals and drivers.
Signals and drivers are specs built from the primitives in core/world/primitives.py; a spec can
refer to other nodes with {ref: name}. Evaluation runs in two steps:
    1. nodes     every signal and driver, in reference order; events' effects are applied to a node
                 right after it is computed, so everything that refers to it follows
    2. derive()  the relations between quantities (core/world/physics.py), when their inputs exist:
                   air.vapour_pressure_hpa + air.temperature_c -> air.humidity_rh
                   clean_air section + gas drivers           -> air.o2_pct
                   air.sea_level_pressure_hpa + altitude     -> air.pressure_hpa
                   motion                                    -> body.* and the device height
                 every other driver is a quantity as it is; all are kept within physical bounds
Slow quantities live on the air grid (air_dt_s), the body on its own finer grid (body_dt_s). A track
that does not change is stored as one sample. World.at(name, t) reads any track at any times.
"""
import os
import zlib
from dataclasses import dataclass

import numpy as np
import yaml

from core.quantities import CATALOG
from core.quantities import rotation as rot
from core.quantities.measurement import check_source

from . import physics as P
from . import primitives as PR
from .motion import MotionPlan, kinematics

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORLDS_DIR = os.path.join(ROOT, "configs", "worlds")
GASES = ("air.co_ppm", "air.h2s_ppm", "air.lel_pct", "air.voc_ppm", "air.co2_ppm")
RELATION_INPUTS = ("air.vapour_pressure_hpa", "air.sea_level_pressure_hpa", "floor_altitude_m")
REALISM = ("ASSUMPTION", "recorded")
SETTINGS = ("indoor", "outdoor")
TOP_KEYS = {"name", "title", "realism", "setting", "description", "grid", "time", "clean_air", "earth_field_ut",
            "signals", "drivers", "motion"}
_A = lambda v, u, why: {"value": v, "unit": u, "source": f"ASSUMPTION: {why}"}
DEFAULT_MOTION = {"model": "still", "device_height_m": _A(1.0, "m", "default: a device at rest 1 m above the floor"),
                  "lying_height_m": _A(0.15, "m", "default"), "heading_deg": _A(0, "°", "default: facing north"),
                  "impact_s": _A(0.08, "s", "default"), "step_hz": _A(1.8, "Hz", "default"),
                  "speed_m_s": _A(0, "m/s", "default"), "surge_m_s": _A(0, "m/s", "default"),
                  "bob_m": _A(0, "m", "default"), "sway_deg": _A(0, "°", "default"),
                  "turn_rate_sd_dps": _A(0, "°/s", "default"), "turn_tau_s": _A(3, "s", "default"),
                  "fidget_deg": _A(0, "°", "default: not on a person"), "fidget_tau_s": _A(2, "s", "default"),
                  "stir_deg": _A(0, "°", "default")}
DEFAULT_EARTH_FIELD = _A([19.5, 0.0, -44.5], "µT", "mid-latitude field in world axes (x north, z up), about 49 µT")
DEFAULT_GRID = {"air_dt_s": _A(1, "s", "default: air and slow quantities change over seconds"),
                "body_dt_s": _A(0.04, "s", "default: 25 Hz resolves steps (about 2 Hz) and a fall impact (about 0.1 s)")}
DEFAULT_TIME = {"start_utc": _A("2026-01-05T06:00:00Z", "ISO 8601", "default: a Monday 06:00, the shift start of the gas scenarios"),
                "utc_offset_h": _A(0, "h", "default: local time = UTC")}
DEFAULTS = {"grid": DEFAULT_GRID, "time": DEFAULT_TIME, "earth_field_ut": DEFAULT_EARTH_FIELD, "motion": DEFAULT_MOTION}


def v(p):
    return p["value"] if isinstance(p, dict) and "value" in p else p


@dataclass
class Track:
    dt: float
    values: np.ndarray            # (n,) or (n, k); n == 1 means constant

    @property
    def constant(self) -> bool:
        return len(self.values) == 1

    def times(self):
        return np.arange(len(self.values)) * self.dt

    def at(self, t):
        t = np.atleast_1d(np.asarray(t, float))
        if self.constant:
            return np.repeat(self.values, len(t), axis=0)
        x = self.times()
        if self.values.ndim == 1:
            return np.interp(t, x, self.values)
        return np.column_stack([np.interp(t, x, self.values[:, k]) for k in range(self.values.shape[1])])


@dataclass
class Mount:
    """Where a device sits in the world. body: worn on the moving body (it reads the body tracks and
    the body's altitude). fixed: on a wall, shelf or post on the ground floor, at height_m, facing
    heading_deg; it shares the air but not the body's movement, floors or falls."""
    kind: str = "body"
    height_m: float = 1.0
    heading_deg: float = 0.0

    def __post_init__(self):
        if self.kind not in ("body", "fixed"):
            raise ValueError(f"mount must be 'body' or 'fixed', got {self.kind!r}")


class WorldView:
    """The world as one device sees it from its mount."""

    def __init__(self, world: "World", mount: Mount):
        self.world, self.mount = world, mount

    def at(self, name: str, t):
        w, m = self.world, self.mount
        if m.kind == "body":
            return w.at(name, t)
        n = len(np.atleast_1d(t))
        if name == "body.accel_g":
            return np.tile([0.0, 0.0, 1.0], (n, 1))
        if name == "body.gyro_dps":
            return np.zeros((n, 3))
        if name == "body.orientation":
            h = np.radians(m.heading_deg) / 2
            return np.tile([np.cos(h), 0.0, 0.0, np.sin(h)], (n, 1))
        if name in ("body.height_m", "altitude_m"):
            return np.full(n, m.height_m)
        if name == "air.pressure_hpa" and "air.sea_level_pressure_hpa" in w.tracks:
            return P.pressure_at(w.at("air.sea_level_pressure_hpa", t), m.height_m)
        return w.at(name, t)

    def state_at(self, t):
        return self.world.state_at(t) if self.mount.kind == "body" else np.full(len(np.atleast_1d(t)), "fixed", object)


def load_preset(name: str, worlds_dir: str = WORLDS_DIR) -> dict:
    path = os.path.join(worlds_dir, f"{name}.yaml")
    if not os.path.exists(path):
        raise FileNotFoundError(f"world preset {name!r} not found in {worlds_dir}")
    with open(path) as fh:
        d = yaml.safe_load(fh)
    d.setdefault("name", name)
    check_preset(d, name)
    return d


def list_presets(worlds_dir: str = WORLDS_DIR) -> list:
    return sorted(f[:-5] for f in os.listdir(worlds_dir) if f.endswith(".yaml"))


def check_preset(d: dict, name: str = ""):
    """Every number in a preset carries {value, unit, source}; the realism label is set; drivers are
    known quantities or relation inputs, without two ways to the same quantity."""
    unknown = set(d) - TOP_KEYS
    if unknown:
        raise ValueError(f"world {name}: unknown key(s) {sorted(unknown)}")
    if d.get("realism") not in REALISM:
        raise ValueError(f"world {name}: realism must be one of {REALISM}")
    if d.get("setting") not in SETTINGS + (None,):
        raise ValueError(f"world {name}: setting must be one of {SETTINGS} (or left out)")
    drv = d.get("drivers") or {}
    for k in drv:
        if k not in CATALOG and k not in RELATION_INPUTS:
            raise ValueError(f"world {name}: driver {k!r} is neither a quantity (configs/quantities) nor one of "
                             f"{RELATION_INPUTS}")
        if k in (d.get("signals") or {}):
            raise ValueError(f"world {name}: {k!r} is both a signal and a driver")
    for a, b in (("air.vapour_pressure_hpa", "air.humidity_rh"), ("air.sea_level_pressure_hpa", "air.pressure_hpa")):
        if a in drv and b in drv:
            raise ValueError(f"world {name}: give {a} or {b}, not both ({b} follows from {a})")
    if "clean_air" in d and "air.o2_pct" in drv:
        raise ValueError(f"world {name}: air.o2_pct follows from clean_air and the gases; do not give it as a driver")
    if "air.vapour_pressure_hpa" in drv and "air.temperature_c" not in drv:
        raise ValueError(f"world {name}: humidity from vapour needs air.temperature_c")

    def walk(x, path):
        if isinstance(x, dict):
            if "value" in x and not isinstance(x["value"], dict) and not any(k in x for k in PR.PRIMITIVES):
                check_source(path, x)
            else:
                for k, y in x.items():
                    if k not in ("model", "description", "title", "realism", "name", "ref"):
                        walk(y, f"{path}.{k}")
        elif isinstance(x, list):
            for i, y in enumerate(x):
                walk(y, f"{path}[{i}]")
        elif isinstance(x, (int, float)) and not isinstance(x, bool):
            raise ValueError(f"world {name}: {path} = {x!r} has no source; write {{value, unit, source}}")
    for k in ("grid", "time", "clean_air", "earth_field_ut", "signals", "drivers", "motion"):
        walk(d.get(k, {}), k)


class World:
    def __init__(self, preset, duration_s: float, seed: int, start: str = None, worlds_dir: str = WORLDS_DIR):
        import copy
        self.preset = copy.deepcopy(load_preset(preset, worlds_dir) if isinstance(preset, str) else preset)
        if not isinstance(preset, str):
            check_preset(self.preset, self.preset.get("name", ""))
        self.defaults_used = {}                    # what the preset left out and the code filled in (manifest)
        for key, default in DEFAULTS.items():
            if key not in self.preset:
                self.preset[key] = copy.deepcopy(default)
                self.defaults_used[key] = default
            elif isinstance(default, dict) and "value" not in default:
                for k, v_ in default.items():
                    if k not in self.preset[key]:
                        self.preset[key][k] = copy.deepcopy(v_)
                        self.defaults_used[f"{key}.{k}"] = v_
        self.name = self.preset["name"]
        self.realism = self.preset["realism"]
        self.setting = self.preset.get("setting")             # indoor | outdoor | None (not stated)
        self.duration_s, self.seed = float(duration_s), int(seed)
        start = start or v(self.preset["time"]["start_utc"])
        self.start = np.datetime64(str(start).replace("Z", ""), "s")
        self.air_dt = float(v(self.preset["grid"]["air_dt_s"]))
        self.body_dt = float(v(self.preset["grid"]["body_dt_s"]))
        self.motion_params = self.preset.get("motion") or DEFAULT_MOTION
        self.effects, self.motion_effects = [], []
        self.drivers, self.signals, self.tracks = {}, {}, {}
        self._body_key = None
        m = self.motion_params
        if m["model"] == "walk_still":
            self.base_motion = MotionPlan.walk_still(self.duration_s, self.rng("motion"), v(m["walk_bout_s"]),
                                                     v(m["still_bout_s"]))
        elif m["model"] == "still":
            self.base_motion = MotionPlan(self.duration_s)
        else:
            raise ValueError(f"world {self.name}: unknown motion model {m['model']!r}")
        n = int(round(self.duration_s / self.air_dt)) + 1
        self.t = np.arange(n) * self.air_dt
        utc_h = (self.t / 3600.0 + (self.start - self.start.astype("datetime64[D]")) / np.timedelta64(1, "h"))
        self.hour = (utc_h + v(self.preset["time"]["utc_offset_h"])) % 24
        self.doy = (self.start.astype("datetime64[D]") - self.start.astype("datetime64[Y]")).astype(int) + 1 + utc_h // 24
        self.evaluate()

    def rng(self, stream: str):
        """Independent random stream per node, so adding one does not change the others."""
        return np.random.default_rng([self.seed, zlib.crc32(f"{self.name}/{stream}".encode())])

    def context(self, t=None, rng=None, names=None, node=None):
        return PR.Context(self.t if t is None else t, self.air_dt, self.hour, self.doy, rng, self.base_motion.walks(),
                          node, names)

    def nodes(self) -> list:
        return list(self.preset.get("signals") or {}) + list(self.preset.get("drivers") or {})

    # events
    def add_effect(self, effect: dict):
        """effect: {target, op (add | multiply | set | approach), shape or value, at, end, names, tau_s,
        recovery_tau_s, rng_stream}. Applied to the target node each time the world is evaluated."""
        if effect["target"] not in self.nodes():
            raise KeyError(effect["target"])
        self.effects.append(effect)

    def add_motion(self, at: float, segments: list):
        """segments: [{kind, duration, posture}] one after the other from `at`; posture current = as at `at`."""
        self.motion_effects.append((float(at), segments))

    def _apply(self, name, x):
        for e in self.effects:
            if e["target"] != name:
                continue
            at, end, names = e["at"], e["end"], e.get("names", {})
            c = self.context(self.t - at, self.rng(e.get("rng_stream", f"effect{at}")), names, self._node)
            op, hold = e["op"], e.get("after", "revert") == "hold"
            if e.get("after", "revert") not in ("hold", "revert"):
                raise ValueError(f"effect after must be hold or revert, got {e['after']!r}")
            before, during, after = self.t < at, (self.t >= at) & (self.t < end), self.t >= end
            last = max(0, min(np.searchsorted(self.t, end) - 1, len(self.t) - 1))     # last sample of the event
            if op in ("add", "multiply"):
                ident = 0.0 if op == "add" else 1.0
                s = PR.evaluate(e["shape"], c)
                s = np.where(before, ident, s)
                s[after] = s[last] if hold and during.any() else ident
                x = x + s if op == "add" else x * s
            elif op == "set":
                v = PR.evaluate(e["value"], c)
                x = np.where(during, v, x)
                if hold and during.any():
                    x = np.where(after, v[last], x)
            elif op == "approach":
                target = PR.evaluate(e["value"], c)
                tau = PR.value(e["tau_s"], names)
                d = np.zeros_like(x)
                d[during] = (target[during] - x[during]) * (1 - np.exp(-(self.t[during] - at) / tau))
                i = min(np.searchsorted(self.t, end), len(self.t) - 1)
                d_end = (target[i] - x[i]) * (1 - np.exp(-(end - at) / tau))
                if hold:
                    d[after] = target[after] - x[after]
                elif "recovery_tau_s" in e:
                    d[after] = d_end * np.exp(-(self.t[after] - end) / PR.value(e["recovery_tau_s"], names))
                x = x + d
            else:
                raise ValueError(f"unknown effect op {op!r}; known: add, multiply, set, approach")
        return x

    def _node(self, name):
        if name in self._cache:
            return self._cache[name]
        specs = {**(self.preset.get("signals") or {}), **(self.preset.get("drivers") or {})}
        if name not in specs:
            raise PR.SpecError(f"world {self.name}: no signal or driver {name!r}")
        if name in self._busy:
            raise PR.SpecError(f"world {self.name}: {name!r} refers to itself")
        self._busy.add(name)
        x = PR.evaluate(specs[name], self.context(rng=self.rng(name), node=self._node))
        self._busy.discard(name)
        self._cache[name] = self._apply(name, x)
        return self._cache[name]

    def evaluate(self):
        """Step 1 (nodes, with event effects) and step 2 (derive)."""
        self._cache, self._busy = {}, set()
        for name in self.nodes():
            self._node(name)
        self.signals = {k: self._cache[k] for k in (self.preset.get("signals") or {})}
        self.drivers = {k: self._cache[k].copy() for k in (self.preset.get("drivers") or {})}
        self.motion = MotionPlan(self.duration_s, [dict(s) for s in self.base_motion.segments])
        for at, segs in self.motion_effects:
            t = at
            for sg in segs:
                d = float(sg["duration"])
                if d <= 0:
                    continue
                posture = sg.get("posture", "upright")
                before = self.motion.at(max(t - 1e-6, 0.0)).get("posture", "upright")    # as it was just before
                if posture == "current":
                    posture = before
                if sg.get("needs") and before != sg["needs"]:
                    raise ValueError(f"at {t:.0f} s the body is not {sg['needs']} (motion {sg['kind']})")
                self.motion.insert(t, t + d, sg["kind"], posture=posture)
                t += d
        return self.derive()

    # step 2: relations
    def derive(self):
        d, dt = self.drivers, self.air_dt
        tr = {}
        for k, x in d.items():
            if k in CATALOG or k in RELATION_INPUTS:
                tr[k] = np.asarray(x, float)
        if "air.vapour_pressure_hpa" in d:
            T = tr["air.temperature_c"]
            e = np.minimum(tr["air.vapour_pressure_hpa"], P.saturation_vapour_pressure(T))   # no supersaturation
            tr["air.vapour_pressure_hpa"] = e
            tr["air.humidity_rh"] = P.relative_humidity(T, e)
        if "clean_air" in self.preset:
            ca = self.preset["clean_air"]
            clean = {"air.co2_ppm": v(ca["co2_ppm"])} if "co2_ppm" in ca else {}
            gases = {g: np.maximum(tr[g], 0.0) for g in GASES if g in tr}
            frac = P.foreign_fraction(gases, clean, self.lel_gas_vol_pct) if gases else np.zeros(len(self.t))
            tr["air.o2_pct"] = P.oxygen(v(ca["o2_pct"]), frac) * np.ones(len(self.t))
        for k in list(tr):                              # physical bounds
            q = CATALOG.get(k)
            if q is not None and not q.vector:
                tr[k] = np.clip(tr[k], -np.inf if q.lower is None else q.lower, np.inf if q.upper is None else q.upper)
        self.tracks = {k: Track(dt, x) for k, x in tr.items()}
        self._derive_body()
        if "air.sea_level_pressure_hpa" in tr:
            h = self.tracks["body.height_m"]
            if not h.constant:
                w = max(1, int(round(dt / self.body_dt)))
                padded = np.pad(h.values, (w // 2, w - 1 - w // 2), mode="edge")
                h = Track(self.body_dt, np.convolve(padded, np.ones(w) / w, mode="valid"))
            floor = tr.get("floor_altitude_m", np.zeros(len(self.t)))
            alt = floor + h.at(self.t)
            self.tracks["altitude_m"] = Track(dt, alt)
            self.tracks["air.pressure_hpa"] = Track(dt, P.pressure_at(tr["air.sea_level_pressure_hpa"], alt))
        return self

    def _derive_body(self):
        key = repr(self.motion.segments)
        if key != self._body_key:
            self._kin = kinematics(self.motion, self.body_dt, self.motion_params, self.rng("kinematics"))
            self._body_key = key
        k = self._kin
        b = np.asarray(v(self.preset.get("earth_field_ut", DEFAULT_EARTH_FIELD)), float)
        self.tracks["body.orientation"] = Track(self.body_dt, k["orientation"])
        self.tracks["body.gyro_dps"] = Track(self.body_dt, k["gyro"])
        self.tracks["body.accel_g"] = Track(self.body_dt, k["force"])
        self.tracks["body.mag_ut"] = Track(self.body_dt, b[None, :])          # world frame: the Earth's field
        self.tracks["body.height_m"] = Track(self.body_dt, k["height"])
        self.motion_state = Track(self.body_dt, k["state"])

    @property
    def combustible_gas(self) -> str:
        return v(self.preset.get("clean_air", {}).get("combustible_gas", {"value": "methane"}))

    @property
    def lel_gas_vol_pct(self) -> float:
        """%vol of the combustible gas at 100 %LEL: given in the preset, or from the table in physics.py."""
        ca = self.preset.get("clean_air", {})
        if "lel_vol_pct" in ca:
            return float(v(ca["lel_vol_pct"]))
        g = self.combustible_gas
        if g not in P.COMBUSTIBLE_LEL_VOL_PCT:
            raise ValueError(f"world {self.name}: combustible gas {g!r} has no LEL in the table "
                             f"({', '.join(P.COMBUSTIBLE_LEL_VOL_PCT)}); give clean_air.lel_vol_pct")
        return P.COMBUSTIBLE_LEL_VOL_PCT[g]

    # reading
    def at(self, name: str, t):
        """Values of a track at times t (s since the start)."""
        if name not in self.tracks:
            raise KeyError(f"world {self.name} has no track {name!r}; tracks: {sorted(self.tracks)}")
        x = self.tracks[name].at(t)
        return rot.normalize(x) if name == "body.orientation" else x

    def quantities(self) -> list:
        """Catalog quantities this world provides."""
        return [q for q in CATALOG if q in self.tracks]

    def view(self, mount: Mount = None) -> WorldView:
        return WorldView(self, mount or Mount())

    def state_at(self, t):
        tr = self.motion_state
        if tr.constant:
            return np.repeat(tr.values, len(np.atleast_1d(t)))
        idx = np.clip(np.round(np.atleast_1d(t) / tr.dt).astype(int), 0, len(tr.values) - 1)
        return tr.values[idx]

    def timestamps(self, t):
        return self.start + np.round(np.asarray(t, float) * 1000).astype("timedelta64[ms]")   # 0.28 s is 0.2799… ms-wise

    def describe(self) -> dict:
        d = {"name": self.name, "title": self.preset.get("title", self.name), "realism": self.realism,
             "setting": self.setting, "description": self.preset.get("description", ""), "start_utc": str(self.start) + "Z",
             "duration_s": self.duration_s, "seed": self.seed, "quantities": self.quantities(),
             "defaults_used": self.defaults_used}
        if "clean_air" in self.preset:
            d.update(combustible_gas=self.combustible_gas, lel_vol_pct=self.lel_gas_vol_pct)
        return d
