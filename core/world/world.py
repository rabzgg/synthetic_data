"""
world.py — block [D]: one timeline of physical truth that every sensor in a run reads.

A world is built from a preset (configs/worlds/<name>.yaml) in two steps:
    1. drivers   independent inputs: air temperature, water vapour pressure, sea-level pressure,
                 floor altitude, gas levels, light, and the motion plan of the body
    2. derive()  everything related to them: relative humidity, oxygen, air pressure, and the
                 body tracks (orientation, angular rate, specific force, magnetic field, height)
Events (phase 4) change drivers or the motion plan and call derive() again, so the relations hold
after every change.

Slow quantities live on the air grid (air_dt_s), the body on its own finer grid (body_dt_s). A track
that does not change is stored as one sample. World.at(name, t) reads any track at any times.
"""
import datetime as _dt
import os
import zlib
from dataclasses import dataclass

import numpy as np
import yaml

from core.quantities import CATALOG
from core.quantities import rotation as rot
from core.quantities.measurement import check_source

from . import drivers as D
from . import physics as P
from .motion import MotionPlan, kinematics

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORLDS_DIR = os.path.join(ROOT, "configs", "worlds")
GASES = ("air.co_ppm", "air.h2s_ppm", "air.lel_pct", "air.voc_ppm", "air.co2_ppm")
DRIVERS = ("air.temperature_c", "air.vapour_pressure_hpa", "air.sea_level_pressure_hpa", "floor_altitude_m",
           "light.lux") + GASES
REALISM = ("ASSUMPTION", "recorded")


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


def load_preset(name: str, worlds_dir: str = WORLDS_DIR) -> dict:
    path = os.path.join(worlds_dir, f"{name}.yaml")
    if not os.path.exists(path):
        raise FileNotFoundError(f"world preset {name!r} not found in {worlds_dir}")
    with open(path) as fh:
        d = yaml.safe_load(fh)
    check_preset(d, name)
    return d


def list_presets(worlds_dir: str = WORLDS_DIR) -> list:
    return sorted(f[:-5] for f in os.listdir(worlds_dir) if f.endswith(".yaml"))


def check_preset(d: dict, name: str = ""):
    """Every number in a preset carries {value, unit, source}; the realism label is set."""
    if d.get("realism") not in REALISM:
        raise ValueError(f"world {name}: realism must be one of {REALISM}")
    missing = set(DRIVERS) - set(d.get("drivers", {}))
    if missing:
        raise ValueError(f"world {name}: drivers missing: {sorted(missing)}")

    def walk(x, path):
        if isinstance(x, dict):
            if "value" in x and not isinstance(x["value"], dict):
                check_source(path, x)
            else:
                for k, y in x.items():
                    if k not in ("model", "description", "title", "realism", "name"):
                        walk(y, f"{path}.{k}")
        elif isinstance(x, (int, float, list)) and not isinstance(x, bool):
            raise ValueError(f"world {name}: {path} = {x!r} has no source; write {{value, unit, source}}")
    for k in ("grid", "time", "clean_air", "earth_field_ut", "drivers", "motion"):
        walk(d.get(k, {}), k)


class World:
    def __init__(self, preset, duration_s: float, seed: int, start: str = None, worlds_dir: str = WORLDS_DIR):
        self.preset = load_preset(preset, worlds_dir) if isinstance(preset, str) else preset
        if not isinstance(preset, str):
            check_preset(self.preset, self.preset.get("name", ""))
        self.name = self.preset["name"]
        self.realism = self.preset["realism"]
        self.duration_s, self.seed = float(duration_s), int(seed)
        start = start or v(self.preset["time"]["start_utc"])
        self.start = np.datetime64(str(start).replace("Z", ""), "s")
        self.air_dt = float(v(self.preset["grid"]["air_dt_s"]))
        self.body_dt = float(v(self.preset["grid"]["body_dt_s"]))
        self.drivers, self.tracks = {}, {}
        self._build()

    def rng(self, stream: str):
        """Independent random stream per driver, so adding one does not change the others."""
        return np.random.default_rng([self.seed, zlib.crc32(f"{self.name}/{stream}".encode())])

    # step 1: drivers
    def _build(self):
        m = self.preset["motion"]
        if m["model"] == "walk_still":
            self.motion = MotionPlan.walk_still(self.duration_s, self.rng("motion"), v(m["walk_bout_s"]),
                                                v(m["still_bout_s"]))
        elif m["model"] == "still":
            self.motion = MotionPlan(self.duration_s)
        else:
            raise ValueError(f"world {self.name}: unknown motion model {m['model']!r}")
        n = int(round(self.duration_s / self.air_dt)) + 1
        t = np.arange(n) * self.air_dt
        utc_h = (t / 3600.0 + (self.start - self.start.astype("datetime64[D]")) / np.timedelta64(1, "h"))
        local = (utc_h + v(self.preset["time"]["utc_offset_h"])) % 24
        doy = (self.start.astype("datetime64[D]") - self.start.astype("datetime64[Y]")).astype(int) + 1 + utc_h // 24
        ctx = {"t": t, "dt": self.air_dt, "hour": local, "doy": doy, "walks": self.motion.walks()}
        for name in DRIVERS:
            self.drivers[name] = D.make(name, self.preset["drivers"][name], dict(ctx, rng=self.rng(name)))
        self.derive()

    # step 2: relations
    def derive(self):
        d, ca, dt = self.drivers, self.preset["clean_air"], self.air_dt
        T = d["air.temperature_c"]
        e = np.minimum(d["air.vapour_pressure_hpa"], P.saturation_vapour_pressure(T))   # no supersaturation
        tr = {"air.temperature_c": T, "air.vapour_pressure_hpa": e, "air.humidity_rh": P.relative_humidity(T, e),
              "air.sea_level_pressure_hpa": d["air.sea_level_pressure_hpa"], "floor_altitude_m": d["floor_altitude_m"],
              "light.lux": np.maximum(d["light.lux"], 0.0)}
        clean = {"air.co2_ppm": v(ca["co2_ppm"])}
        for g in GASES:
            tr[g] = np.maximum(d[g], 0.0)
        frac = P.foreign_fraction({g: tr[g] for g in GASES}, clean, v(ca["lel_gas_vol_pct"]))
        tr["air.o2_pct"] = P.oxygen(v(ca["o2_pct"]), frac)
        self.tracks = {k: Track(dt, np.asarray(x, float)) for k, x in tr.items()}
        # body
        k = kinematics(self.motion, self.body_dt, self.preset["motion"], self.rng("kinematics"))
        q = k["orientation"]
        b = np.asarray(v(self.preset["earth_field_ut"]), float)
        self.tracks["body.orientation"] = Track(self.body_dt, q)
        self.tracks["body.gyro_dps"] = Track(self.body_dt, k["gyro"])
        self.tracks["body.accel_g"] = Track(self.body_dt, k["force"])
        self.tracks["body.mag_ut"] = Track(self.body_dt, b[None, :])          # world frame: the Earth's field
        self.tracks["body.height_m"] = Track(self.body_dt, k["height"])
        self.motion_state = Track(self.body_dt, k["state"])
        # pressure at the device: floor altitude plus the device height above the floor, averaged over
        # one air step (the step bob is far faster than any pressure change the air grid holds)
        h = self.tracks["body.height_m"]
        if not h.constant:
            w = max(1, int(round(dt / self.body_dt)))
            padded = np.pad(h.values, (w // 2, w - 1 - w // 2), mode="edge")
            h = Track(self.body_dt, np.convolve(padded, np.ones(w) / w, mode="valid"))
        alt = self.tracks["floor_altitude_m"].values + h.at(self.tracks["floor_altitude_m"].times())
        self.tracks["altitude_m"] = Track(dt, alt)
        self.tracks["air.pressure_hpa"] = Track(dt, P.pressure_at(tr["air.sea_level_pressure_hpa"], alt))
        return self

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

    def state_at(self, t):
        tr = self.motion_state
        if tr.constant:
            return np.repeat(tr.values, len(np.atleast_1d(t)))
        idx = np.clip(np.round(np.atleast_1d(t) / tr.dt).astype(int), 0, len(tr.values) - 1)
        return tr.values[idx]

    def timestamps(self, t):
        return self.start + (np.asarray(t, float) * 1000).astype("timedelta64[ms]")

    def describe(self) -> dict:
        return {"name": self.name, "title": self.preset.get("title", self.name), "realism": self.realism,
                "description": self.preset.get("description", ""), "start_utc": str(self.start) + "Z",
                "duration_s": self.duration_s, "seed": self.seed}
