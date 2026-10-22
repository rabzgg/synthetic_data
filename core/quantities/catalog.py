"""
catalog.py — the physical quantities a world can hold and a sensor can measure.

One entry per quantity: id, plain name, unit, CSV column stem and physical bounds. Nothing here is
about a particular sensor; a part (datasheet) says which quantities it measures and with which
parameters, and core/quantities/measurement.py turns the world value into a reading.

Physical bounds are hard limits of nature (RH cannot exceed 100 %, a concentration cannot be
negative). A sensor's own range is a datasheet parameter, not a property of the quantity.

The catalog is data: configs/quantities/*.yaml. A new quantity is a new entry there; no code.
"""
import glob
import os
from dataclasses import dataclass
from typing import Optional, Tuple

AXES = ("x", "y", "z")


@dataclass(frozen=True)
class Quantity:
    id: str                       # "<domain>.<name>_<unit>"
    name: str                     # plain English, shown in the UI
    unit: str                     # canonical unit; every parameter is converted to it
    column: str                   # CSV column; "{axis}" is replaced by x / y / z for vector quantities
    lower: Optional[float]        # physical bounds, None = unbounded
    upper: Optional[float]
    axes: Tuple[str, ...] = ()    # () = scalar
    note: str = ""
    alias: Optional[str] = None   # short name, e.g. h2s

    @property
    def vector(self) -> bool:
        return bool(self.axes)

    def columns(self) -> list:
        return [self.column.format(axis=a) for a in self.axes] if self.axes else [self.column]


QUANTITIES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                              "configs", "quantities")


def load_catalog(directory: str = QUANTITIES_DIR) -> dict:
    """Every configs/quantities/*.yaml, in file and list order. Ids and aliases must be unique."""
    import yaml
    out, aliases = {}, {}
    for f in sorted(glob.glob(os.path.join(directory, "*.yaml"))):
        with open(f) as fh:
            d = yaml.safe_load(fh) or {}
        for e in d.get("quantities") or []:
            unknown = set(e) - {"id", "name", "unit", "column", "lower", "upper", "axes", "alias", "note"}
            if unknown:
                raise ValueError(f"{os.path.basename(f)}: {e.get('id')}: unknown field(s) {sorted(unknown)}")
            if e["id"] in out:
                raise ValueError(f"{os.path.basename(f)}: quantity {e['id']} defined twice")
            num = lambda x: None if x is None else float(x)
            q = Quantity(e["id"], e["name"], e["unit"], e["column"], num(e.get("lower")), num(e.get("upper")),
                         tuple(e.get("axes") or ()), e.get("note", ""), e.get("alias"))
            if q.alias:
                if q.alias in aliases or q.alias in out:
                    raise ValueError(f"alias {q.alias!r} used twice")
                aliases[q.alias] = q.id
            out[q.id] = q
    return out


CATALOG = load_catalog()
ALIASES = {q.alias: q.id for q in CATALOG.values() if q.alias}


def resolve(name: str) -> str:
    """Quantity id from an id or a short alias (h2s -> air.h2s_ppm)."""
    if name in CATALOG:
        return name
    if name in ALIASES:
        return ALIASES[name]
    raise KeyError(f"unknown quantity {name!r}; known: {', '.join(list(CATALOG) + list(ALIASES))}")


def get(quantity_id: str) -> Quantity:
    try:
        return CATALOG[quantity_id]
    except KeyError:
        raise KeyError(f"unknown quantity {quantity_id!r}; known: {', '.join(CATALOG)}") from None
