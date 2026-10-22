"""
parts.py — block [B]: one physical sensor, written from its datasheet (configs/parts/<slug>.yaml).

A part says which quantities it measures and, per quantity, the measurement parameters. They can be
given directly as model parameters (`params`) or in the datasheet's own wording (`from_datasheet`,
normalised by core/quantities/normalize.py). Every value is {value, unit, source}. A new sensor is a
new file; no code.

A generic part stands for a class of sensors when no product is named yet (pre-sales: "we measure
CO2"). It says which quantity it is the default for and its class; every value is an ASSUMPTION with
its anchor in the source. Each quantity in the catalog has exactly one:

    generic_for: air.co2_ppm
    class: "low-cost NDIR CO2 module, 0-5000 ppm, ±(50 ppm + 3 %)"

    name: Bosch BME280
    datasheet: "BST-BME280-DS001-23, revision 1.23"
    measures:
      - quantity: air.humidity_rh
        params:
          range: {value: [0, 100], unit: "%RH", source: "datasheet BST-BME280-DS001-23 p.9"}
        from_datasheet:
          - {rule: hysteresis_pm, value: 1, unit: "%RH", source: "datasheet BST-BME280-DS001-23 p.9"}
"""
import os
from dataclasses import dataclass, field
from typing import Dict, List

import yaml

from core.quantities import CATALOG, MeasurementModel, normalize
from core.quantities.measurement import PARAMETERS, ParamError

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PARTS_DIR = os.path.join(ROOT, "configs", "parts")
USER_TWEAK = "ASSUMPTION: user tweak"


@dataclass
class Part:
    slug: str
    name: str
    datasheet: str
    measures: Dict[str, dict]                 # {quantity_id: {param: {value, unit, source}}}
    notes: List[str] = field(default_factory=list)
    path: str = ""
    generic_for: str = ""                     # the quantity this generic part is the default for
    cls: str = ""                             # its sensor class, shown in the UI

    @classmethod
    def from_dict(cls, slug: str, d: dict, path: str = "") -> "Part":
        for k in ("name", "datasheet", "measures"):
            if k not in d:
                raise ParamError(f"part {slug}: '{k}' is missing")
        unknown = set(d) - {"name", "datasheet", "datasheet_url", "measures", "notes", "description", "generic_for",
                            "class"}
        if unknown:
            raise ParamError(f"part {slug}: unknown key(s) {sorted(unknown)}")
        measures = {}
        for m in d["measures"]:
            qid = m["quantity"]
            if qid not in CATALOG:
                raise ParamError(f"part {slug}: unknown quantity {qid!r}")
            if qid in measures:
                raise ParamError(f"part {slug}: {qid} listed twice")
            params = {k: dict(v) for k, v in (m.get("params") or {}).items()}
            for st in m.get("from_datasheet") or []:
                st = dict(st)
                rule, value, unit, source = st.pop("rule"), st.pop("value"), st.pop("unit"), st.pop("source")
                for k, v in normalize(rule, value, unit, source, **st).items():
                    if k in params:
                        raise ParamError(f"part {slug}: {qid}.{k} given twice")
                    params[k] = v
            measures[qid] = params
            MeasurementModel.from_params(qid, params)           # fail early on a bad file
        gen = d.get("generic_for", "")
        if gen or "class" in d:
            if gen not in measures or not d.get("class"):
                raise ParamError(f"part {slug}: a generic part needs generic_for (a quantity it measures) and class")
            bad = [f"{q}.{k}" for q, ps in measures.items() for k, p in ps.items()
                   if not str(p["source"]).startswith("ASSUMPTION")]
            if bad:
                raise ParamError(f"part {slug}: a generic part has no datasheet; every value is an ASSUMPTION "
                                 f"(not: {', '.join(bad)})")
        return cls(slug, d["name"], d["datasheet"], measures, list(d.get("notes") or []), path, gen,
                   d.get("class", ""))

    @classmethod
    def load(cls, slug: str, parts_dir: str = PARTS_DIR) -> "Part":
        path = os.path.join(parts_dir, f"{slug}.yaml")
        if not os.path.exists(path):
            raise FileNotFoundError(f"part {slug!r} not found in {parts_dir}")
        with open(path) as fh:
            return cls.from_dict(slug, yaml.safe_load(fh), path)

    def quantities(self) -> List[str]:
        return list(self.measures)

    def params(self, overrides: dict = None) -> Dict[str, dict]:
        """Parameters per quantity after a device's overrides (see apply_overrides)."""
        return apply_overrides(self, overrides or {})

    def models(self, overrides: dict = None) -> Dict[str, MeasurementModel]:
        return {q: MeasurementModel.from_params(q, p) for q, p in self.params(overrides).items()}


def apply_overrides(part: Part, overrides: dict) -> Dict[str, dict]:
    """Device overrides on top of the part's parameters.

    Keyed by quantity ({quantity: {param: ...}}) or, for a part that measures one quantity, by
    parameter directly. A missing unit means the part's unit for that parameter (or the quantity's);
    a missing source means "ASSUMPTION: user tweak"."""
    if not overrides:
        return {q: {k: dict(v) for k, v in p.items()} for q, p in part.measures.items()}
    if set(overrides) <= set(PARAMETERS):
        if len(part.measures) != 1:
            raise ParamError(f"part {part.slug} measures {len(part.measures)} quantities: key overrides by quantity")
        overrides = {part.quantities()[0]: overrides}
    out = {q: {k: dict(v) for k, v in p.items()} for q, p in part.measures.items()}
    twins = {"noise_sd": "noise_density", "noise_density": "noise_sd"}     # one replaces the other
    for q, ov in overrides.items():
        if q not in out:
            raise ParamError(f"part {part.slug} does not measure {q}")
        for k, v in ov.items():
            if k not in PARAMETERS:
                raise ParamError(f"override {part.slug}.{q}.{k}: unknown parameter")
            v = dict(v) if isinstance(v, dict) else {"value": v}
            v.setdefault("unit", out[q].get(k, {}).get("unit") or _default_unit(q, k))
            v.setdefault("source", USER_TWEAK)
            out[q][k] = v
            if k in twins and twins[k] not in ov:
                out[q].pop(twins[k], None)
    return out


def _default_unit(qid, param):
    kind = PARAMETERS[param].kind
    q = CATALOG[qid]
    return {"q": q.unit, "q/h": q.unit + "/h", "q/√Hz": q.unit + "/√Hz", "s": "s", "Hz": "Hz", "%": "%",
            "deg": "deg"}.get(kind, "-")


def list_parts(parts_dir: str = PARTS_DIR) -> List[str]:
    return sorted(f[:-5] for f in os.listdir(parts_dir) if f.endswith(".yaml"))


def generic_parts(parts_dir: str = PARTS_DIR) -> Dict[str, List[str]]:
    """{quantity: [slugs of the generic parts for it]} (exactly one each, tests/test_generic_parts.py)."""
    out = {}
    for s in list_parts(parts_dir):
        p = Part.load(s, parts_dir)
        if p.generic_for:
            out.setdefault(p.generic_for, []).append(s)
    return out


def generic_part(quantity: str, parts_dir: str = PARTS_DIR) -> str:
    found = generic_parts(parts_dir).get(quantity, [])
    if len(found) != 1:
        raise ParamError(f"{quantity}: expected one generic part, found {found or 'none'}")
    return found[0]


def parts_measuring(quantity: str, parts_dir: str = PARTS_DIR) -> List[str]:
    """Slugs of the non-generic parts that measure a quantity."""
    return [s for s in list_parts(parts_dir) if quantity in Part.load(s, parts_dir).measures
            and not Part.load(s, parts_dir).generic_for]
