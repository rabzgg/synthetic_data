"""
units.py — unit spellings and linear conversions to the catalog's canonical units.

Datasheets write the same unit many ways (C, degC, °C) and often in another scale (Pa instead of
hPa, mg instead of g, per year instead of per hour). Every parameter value is converted here
before the measurement model sees it, so a part file can keep the datasheet's own unit.
Only linear factors are supported (no offsets): temperatures in kelvin are not accepted.
"""
import math

ALIASES = {
    "C": "°C", "degC": "°C", "deg C": "°C", "℃": "°C",
    "%rh": "%RH", "% RH": "%RH", "RH%": "%RH", "% vol": "%vol", "%v/v": "%vol", "% LEL": "%LEL", "%lel": "%LEL",
    "lux": "lx", "dps": "°/s", "deg/s": "°/s", "º/s": "°/s", "uT": "µT", "μT": "µT",
    "sec": "s", "Hertz": "Hz", "√Hz": "√Hz", "sqrt(Hz)": "√Hz", "rtHz": "√Hz",
}
# unit -> (canonical unit, factor): value_in_canonical = value * factor
FACTORS = {
    "Pa": ("hPa", 0.01), "kPa": ("hPa", 10.0), "mbar": ("hPa", 1.0),
    "mg": ("g", 1e-3), "µg": ("g", 1e-6), "ug": ("g", 1e-6), "m/s²": ("g", 1 / 9.80665), "m/s^2": ("g", 1 / 9.80665),
    "mdps": ("°/s", 1e-3), "rad/s": ("°/s", 180 / math.pi),
    "G": ("µT", 100.0), "mG": ("µT", 0.1), "nT": ("µT", 1e-3),
    "ppb": ("ppm", 1e-3),
    "ms": ("s", 1e-3), "min": ("s", 60.0), "h": ("s", 3600.0),
}
HOURS = {"s": 1 / 3600, "min": 1 / 60, "h": 1.0, "hour": 1.0, "day": 24.0, "d": 24.0, "week": 168.0,
         "month": 730.0, "year": 8760.0, "yr": 8760.0}
PERCENT_UNITS = ("%RH", "%vol", "%LEL")


class UnitError(ValueError):
    pass


def canonical(unit: str) -> str:
    u = str(unit).strip()
    return ALIASES.get(u, u)


def factor(unit: str, target: str) -> float:
    """Multiplier that takes a value in `unit` to `target` (both simple units)."""
    u, t = canonical(unit), canonical(target)
    if u == t or (u == "%" and t in PERCENT_UNITS):
        return 1.0
    if u in FACTORS and FACTORS[u][0] == t:
        return FACTORS[u][1]
    raise UnitError(f"cannot convert {unit!r} to {target!r}")


def factor_compound(unit: str, target: str) -> float:
    """Like factor(), also for '<q>/<time>' (drift) and '<q>/√Hz' (noise density)."""
    u, t = canonical(unit), canonical(target)
    if "/" not in t or t in FACTORS or t == "°/s":
        return factor(u, t)
    tn, td = t.rsplit("/", 1)
    if "/" not in u:
        raise UnitError(f"cannot convert {unit!r} to {target!r}")
    un, ud = u.rsplit("/", 1)
    if canonical(td) == "√Hz":
        if canonical(ud) != "√Hz":
            raise UnitError(f"cannot convert {unit!r} to {target!r}")
        return factor(un, tn)
    if ud not in HOURS or td not in HOURS:
        raise UnitError(f"cannot convert {unit!r} to {target!r}: unknown time unit")
    return factor(un, tn) * HOURS[td] / HOURS[ud]


def convert(value, unit: str, target: str):
    """Convert a number or a list of numbers (e.g. a range) from `unit` to `target`."""
    f = factor_compound(unit, target)
    if isinstance(value, (list, tuple)):
        return [v * f for v in value]
    return value * f
