"""
units.py — unit spellings and linear conversions to the catalog's canonical units.

Datasheets write the same unit many ways (C, degC, °C) and often in another scale (Pa instead of
hPa, mg instead of g, per year instead of per hour). Every parameter value is converted here
before the measurement model sees it, so a part file can keep the datasheet's own unit.
Only linear factors are supported for parameters (no offsets: temperatures in kelvin are not accepted);
output_transform also knows units with an offset (°F, K) for writing columns.
The tables are data: configs/units.yaml.
"""
import os

def _load():
    import yaml
    with open(UNITS_FILE) as fh:
        d = yaml.safe_load(fh)
    return (d.get("aliases") or {}, {k: (v[0], float(v[1])) for k, v in (d.get("factors") or {}).items()},
            {k: float(v) for k, v in (d.get("hours") or {}).items()}, tuple(d.get("percent_units") or ()),
            {k: (v["to"], float(v["scale"]), float(v["offset"])) for k, v in (d.get("affine") or {}).items()})


UNITS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "configs",
                          "units.yaml")
ALIASES, FACTORS, HOURS, PERCENT_UNITS, AFFINE = _load()
ALIASES.setdefault("√Hz", "√Hz")


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


def output_transform(unit: str, target: str, absolute: bool = True):
    """(scale, offset) so that value_in_target = value_in_unit × scale + offset, for writing a column in
    another unit (output_format). `unit` is the column's own unit; a rate such as °C/min converts its
    numerator only, and never with an offset. absolute=False: a difference (no offset)."""
    u, t = canonical(unit), canonical(target)
    if u == t:
        return 1.0, 0.0
    if "/" in u and "/" in t and u not in FACTORS and u != "°/s":
        (un, ud), (tn, td) = u.rsplit("/", 1), t.rsplit("/", 1)
        if ud != td:
            raise UnitError(f"cannot write {unit!r} as {target!r}: the time units differ")
        return output_transform(un, tn, absolute=False)[0], 0.0
    if t in AFFINE and AFFINE[t][0] == u:
        _, sc, off = AFFINE[t]
        return float(f"{1.0 / sc:.12g}"), (-off if absolute else 0.0)
    return float(f"{1.0 / factor(t, u):.12g}"), 0.0


def convert(value, unit: str, target: str):
    """Convert a number or a (nested) list of numbers, e.g. a range, from `unit` to `target`."""
    f = factor_compound(unit, target)

    def scale(v):
        return [scale(x) for x in v] if isinstance(v, (list, tuple)) else v * f
    return scale(value)
