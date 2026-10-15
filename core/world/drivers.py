"""
drivers.py — generic models for the independent "drivers" of a world (temperature, vapour pressure,
sea-level pressure, floor altitude, gas levels, light). A world preset picks a model per driver and
gives its parameters, each {value, unit, source}; the related quantities (RH, O2, pressure) are then
derived from the drivers by physics.py, never drawn on their own.

Models:
    constant     value
    ou           mean, sd, tau_s: mean-reverting random walk (Ornstein-Uhlenbeck)
    daily_cycle  mean, amplitude, peak_hour: cosine over 24 h (local time)
    schedule     on_hour, off_hour, on_value, off_value: one level by day, another by night
    solar        latitude_deg, clear_sky, cloud_mean, cloud_sd, cloud_tau_s: sun elevation × clouds
    from_rh      rh_pct, at_temperature_c: vapour pressure that gives this RH at that temperature
    room_levels  levels: a new level drawn from the list whenever the body starts walking
    floors       floor_height_m, floors, change_probability, stairs_s: floor changes during walks
Any model can add `noise: {sd, tau_s}` (an ou process with mean 0) on top, and `smooth_s`: a moving
average over that span, because an ou path is rough at short time scales while weather, room air
and CO2 change smoothly (the sd of an ou is its sd before smoothing).
"""
import numpy as np

from .physics import vapour_pressure


def v(p):
    return p["value"] if isinstance(p, dict) and "value" in p else p


def ou(n, dt, mean, sd, tau_s, rng, x0=None):
    """Ornstein-Uhlenbeck on a grid: stationary sd, correlation time tau_s."""
    from scipy.signal import lfilter
    if sd == 0:
        return np.full(n, float(mean))
    a = np.exp(-dt / tau_s)
    x0 = rng.normal(mean, sd) if x0 is None else x0
    drive = (1 - a) * mean + sd * np.sqrt(1 - a * a) * rng.normal(size=n)
    drive[0] = x0
    return lfilter([1.0], [1.0, -a], drive)


def smooth(x, w: int):
    """Centred moving average over w samples, edges padded with the end values."""
    if w <= 1:
        return x
    p = np.pad(x, (w // 2, w - 1 - w // 2), mode="edge")
    c = np.concatenate([[0.0], np.cumsum(p)])
    return (c[w:] - c[:-w]) / w


def solar_elevation_deg(hour_local, day_of_year, latitude_deg):
    """Approximate sun elevation (declination from the day of year, hour angle from local solar time)."""
    decl = np.radians(23.44) * np.sin(2 * np.pi * (day_of_year - 81) / 365.0)
    ha = np.radians(15.0 * (hour_local - 12.0))
    lat = np.radians(latitude_deg)
    return np.degrees(np.arcsin(np.sin(lat) * np.sin(decl) + np.cos(lat) * np.cos(decl) * np.cos(ha)))


def make(name: str, spec: dict, ctx: dict) -> np.ndarray:
    """Values of one driver on the air grid. ctx: t (s), dt, hour (local hour of day), doy, rng,
    walks [(start_s, end_s)] of the motion plan, temperature (for from_rh)."""
    t, dt, rng = ctx["t"], ctx["dt"], ctx["rng"]
    n, m = len(t), spec["model"]
    if m == "constant":
        x = np.full(n, float(v(spec["value"])))
    elif m == "ou":
        x = ou(n, dt, v(spec["mean"]), v(spec["sd"]), v(spec["tau_s"]), rng)
    elif m == "daily_cycle":
        x = v(spec["mean"]) + v(spec["amplitude"]) * np.cos(2 * np.pi * (ctx["hour"] - v(spec["peak_hour"])) / 24.0)
    elif m == "schedule":
        on = (ctx["hour"] >= v(spec["on_hour"])) & (ctx["hour"] < v(spec["off_hour"]))
        x = np.where(on, float(v(spec["on_value"])), float(v(spec["off_value"])))
    elif m == "solar":
        el = solar_elevation_deg(ctx["hour"], ctx["doy"], v(spec["latitude_deg"]))
        cloud = np.clip(ou(n, dt, v(spec["cloud_mean"]), v(spec["cloud_sd"]), v(spec["cloud_tau_s"]), rng), 0.05, 1.0)
        x = v(spec["clear_sky"]) * np.clip(np.sin(np.radians(el)), 0, None) * cloud
    elif m == "from_rh":
        x = np.full(n, float(vapour_pressure(v(spec["at_temperature_c"]), v(spec["rh_pct"]))))
    elif m == "room_levels":
        levels = np.asarray(v(spec["levels"]), float)
        x = np.full(n, rng.choice(levels))
        for s, _ in ctx["walks"]:
            x[t >= s] = rng.choice(levels)
    elif m == "floors":
        h, top, p, stairs = v(spec["floor_height_m"]), int(v(spec["floors"])), v(spec["change_probability"]), v(spec["stairs_s"])
        x = np.zeros(n)
        floor = 0
        for s, e in ctx["walks"]:
            if rng.random() < p and top > 0:
                new = int(np.clip(floor + rng.choice([-1, 1]), 0, top))
                ramp = np.clip((t - s) / min(stairs, e - s), 0, 1)
                x = np.where(t >= s, floor * h + (new - floor) * h * ramp, x)
                floor = new
    else:
        raise ValueError(f"driver {name}: unknown model {m!r}")
    noise = spec.get("noise")
    if noise:
        x = x + ou(n, dt, 0.0, v(noise["sd"]), v(noise["tau_s"]), rng, x0=0.0)
    if "smooth_s" in spec:
        x = smooth(x, int(round(v(spec["smooth_s"]) / dt)))
    return x
