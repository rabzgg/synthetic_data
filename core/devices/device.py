"""
device.py — block [C]: a device the user assembles from parts, names and saves
(configs/devices/<slug>.yaml; later versions <slug>.v<N>.yaml).

    name: "Tank Monitor v1"            # free name from the user; the slug is made from it
    device_id_prefix: TANKMON          # device_id column = <prefix>-0001 (default: slug in capitals)
    description: "..."
    parts:
      - part: bosch_bme280
      - part: blackline_h2s_cell
        overrides: {t90_s: {value: 25}}      # no source given -> "ASSUMPTION: user tweak"
        log: true                            # false, or a list of quantities, to measure without writing
        as: cell                             # column suffix when two parts measure the same quantity
    features:
      sample_interval_s: {value, unit, source}   # logging interval (default 1 s, ASSUMPTION)
      connectivity: {value, unit, source}        # how it reports; optional
    logic:                                       # generic blocks (core/logic/blocks.py), in column order
      - {block: threshold_alarm, input: air.h2s_ppm, level: {...}, when: above, output: h2s_alarm_low}
    output_format:                               # optional: the vendor's column names and units
      temperature_c: {value: temp_f, unit: "°F", source: "ASSUMPTION: the vendor exports Fahrenheit"}

The CSV columns follow from the parts and the logic: timestamp, device_id, the outputs of blocks
with position: first, the logged readings, then the other block outputs in order. Nothing is typed
twice. Saving under a name that exists gives version + 1 in a new file; an older file is never
overwritten.
"""
import datetime as _dt
import glob
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml

from core.logic import MOTION_BLOCKS, build as build_block, outputs as block_outputs
from core.quantities import CATALOG
from core.quantities.measurement import ParamError, check_source

from .parts import PARTS_DIR, Part

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEVICES_DIR = os.path.join(ROOT, "configs", "devices")

FEATURES = {"sample_interval_s": "logging interval", "connectivity": "how the device reports"}
DEFAULT_INTERVAL = {"value": 1, "unit": "s", "source": "ASSUMPTION: default logging interval of one second"}


def v_(p):
    return p["value"] if isinstance(p, dict) and "value" in p else p


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    if not s:
        raise ValueError(f"cannot make a file name from {name!r}")
    return s


@dataclass
class PartUse:
    part: Part
    overrides: dict = field(default_factory=dict)
    log: object = True                       # True, False or a list of quantity ids
    alias: Optional[str] = None
    note: str = ""

    def logged(self, qid) -> bool:
        return self.log is True or (isinstance(self.log, list) and qid in self.log)


@dataclass
class Device:
    name: str
    slug: str
    version: int
    parts: List[PartUse]
    features: dict = field(default_factory=dict)
    device_id_prefix: str = ""
    description: str = ""
    created: str = ""
    preset: bool = False
    datasheet: str = ""
    notes: List[str] = field(default_factory=list)
    logic: list = field(default_factory=list)          # block specs as written
    output_format: dict = field(default_factory=dict)  # {column: {value: new name, unit, source}}
    path: str = ""

    # loading
    @classmethod
    def from_dict(cls, d: dict, parts_dir: str = PARTS_DIR, path: str = "") -> "Device":
        unknown = set(d) - {"name", "slug", "device_id_prefix", "description", "created", "version", "preset",
                            "datasheet", "parts", "features", "notes", "logic", "output_format"}
        if unknown:
            raise ParamError(f"device: unknown key(s) {sorted(unknown)}")
        name = d["name"]
        slug = slugify(name)
        if d.get("slug") not in (None, slug):
            raise ParamError(f"device {name!r}: slug must be {slug!r} (made from the name), got {d['slug']!r}")
        uses = []
        for u in d["parts"]:
            bad = set(u) - {"part", "overrides", "log", "as", "note"}
            if bad:
                raise ParamError(f"device {name!r}: unknown key(s) {sorted(bad)} in part entry")
            p = Part.load(u["part"], parts_dir)
            use = PartUse(p, u.get("overrides") or {}, u.get("log", True), u.get("as"), u.get("note", ""))
            use.part.models(use.overrides)                    # overrides are checked here
            if isinstance(use.log, list) and not set(use.log) <= set(p.quantities()):
                raise ParamError(f"device {name!r}: log lists quantities {p.slug} does not measure")
            uses.append(use)
        dev = cls(name, slug, int(d.get("version", 1)), uses, d.get("features") or {},
                  d.get("device_id_prefix") or slug.upper(), d.get("description", ""), str(d.get("created", "")),
                  bool(d.get("preset", False)), d.get("datasheet", ""), list(d.get("notes") or []),
                  list(d.get("logic") or []), dict(d.get("output_format") or {}), path)
        dev.validate()
        return dev

    @classmethod
    def load(cls, slug: str, version: int = None, devices_dir: str = DEVICES_DIR, parts_dir: str = PARTS_DIR):
        files = _versions(devices_dir, slug)
        if not files:
            raise FileNotFoundError(f"device {slug!r} not found in {devices_dir}")
        v = version or max(files)
        if v not in files:
            raise FileNotFoundError(f"device {slug!r} has no version {v}; versions: {sorted(files)}")
        with open(files[v]) as fh:
            return cls.from_dict(yaml.safe_load(fh), parts_dir, files[v])

    # what it measures
    def measured(self) -> Dict[str, List[PartUse]]:
        """{quantity: [part uses measuring it]}, in part order."""
        out = {}
        for u in self.parts:
            for q in u.part.quantities():
                out.setdefault(q, []).append(u)
        return out

    def models(self):
        """[(part use, quantity, MeasurementModel)] in part order."""
        return [(u, q, m) for u in self.parts for q, m in u.part.models(u.overrides).items()]

    def reading_columns(self) -> List[tuple]:
        """[(part use, quantity, [columns])] for every logged reading."""
        meas = self.measured()
        out = []
        for u in self.parts:
            for q in u.part.quantities():
                if not u.logged(q):
                    continue
                cols = CATALOG[q].columns()
                if len([x for x in meas[q] if x.logged(q)]) > 1:
                    suffix = u.alias or u.part.slug
                    cols = [f"{c}_{suffix}" for c in cols]
                out.append((u, q, cols))
        return out

    # features and logic
    def feature(self, key, default=None):
        f = self.features.get(key, default)
        return f["value"] if isinstance(f, dict) and "value" in f else f

    @property
    def sample_interval_s(self) -> float:
        return float(v_(self.features.get("sample_interval_s", DEFAULT_INTERVAL)))

    def blocks(self) -> list:
        return [build_block(spec, self.name) for spec in self.logic]

    def capabilities(self) -> set:
        """What device events can use: bump_test, connectivity, battery, states.<s>, motion_alerts.*."""
        caps = set()
        for b in self.blocks():
            if b.kind == "event_mode":
                caps.add(b.spec["event"])
            elif b.kind == "state_flag":
                caps.add(f"states.{b.spec['state']}")
            elif b.kind == "battery":
                caps.add("battery")
            elif b.kind == "signal":
                caps.add("connectivity")
            elif b.kind == "stillness_timer":
                caps.add("motion_alerts.no_motion")
            elif b.kind == "spike_then_still":
                caps.add("motion_alerts.fall")
        if self.features.get("connectivity"):
            caps.add("connectivity")
        return caps

    def columns(self) -> List[str]:
        """CSV columns: timestamp, device_id, outputs of position-first blocks, logged readings, then
        the other block outputs in their order."""
        blocks = self.blocks()
        cols = ["timestamp", "device_id"]
        cols += [c for b in blocks if b.position == "first" for c in block_outputs(b)]
        for _, _, c in self.reading_columns():
            cols += c
        cols += [c for b in blocks if b.position != "first" for c in block_outputs(b)]
        return cols

    def column_units(self) -> Dict[str, tuple]:
        """{column: (unit, absolute)} for every column after the id: readings and the blocks' outputs.
        absolute = an offset applies when the unit is written as °F or K; rates are differences."""
        out = {}
        for _, q, cols in self.reading_columns():
            for c in cols:
                out[c] = (CATALOG[q].unit, True)
        unit_of = {q: CATALOG[q].unit for q in self.measured()}
        unit_of.update({c: u for c, (u, _) in out.items()})
        for b in self.blocks():
            u, absolute = "-", False
            if b.kind in ("rolling_mean", "cumulative_dose"):
                u, absolute = unit_of.get(b.input, "-"), True
            elif b.kind == "rate_of_change":
                u = unit_of.get(b.input, "-") + "/" + b.spec.get("per", "min")
            elif b.kind == "battery":
                u = "%"
            elif b.kind == "signal":
                u = "dBm"
            for c in block_outputs(b):
                out[c] = (u, absolute)
                unit_of[c] = u
        return out

    def output_columns(self) -> List[str]:
        """The CSV header as written: columns() with output_format's new names."""
        return [v_(self.output_format[c]) if c in self.output_format else c for c in self.columns()]

    def output_transforms(self) -> Dict[str, tuple]:
        """{column: (new name, scale, offset)}: written value = value × scale + offset."""
        from core.quantities.units import output_transform
        units, out = self.column_units(), {}
        for c, f in self.output_format.items():
            u, absolute = units[c]
            target = f.get("unit", u)
            sc, off = (1.0, 0.0) if target in ("-", u) else output_transform(u, target, absolute)
            out[c] = (v_(f), sc, off)
        return out

    def device_id(self, n: int = 1) -> str:
        return f"{self.device_id_prefix}-{n:04d}"

    # checks
    def validate(self):
        name, meas = self.name, self.measured()
        unknown = set(self.features) - set(FEATURES)
        if unknown:
            raise ParamError(f"device {name!r}: unknown feature(s) {sorted(unknown)}; known: {list(FEATURES)} "
                             "(alarms, exposure, states, battery and motion detection are logic blocks)")
        for k, f in self.features.items():
            check_source(f"{name}.{k}", f)
        known = set(meas)
        for b in self.blocks():
            inp = b.input
            if b.kind == "orientation_quat":
                from core.derived import OrientationQuat
                need = OrientationQuat(b.spec.get("params")).inputs()
                if not set(need) <= set(meas):
                    raise ParamError(f"device {name!r}: orientation_quat needs {need}, not all measured")
            elif inp is not None and inp not in known:
                raise ParamError(f"device {name!r}: {b.kind} {b.output} reads {inp!r}, which is neither a quantity the "
                                 "device measures nor an earlier block's output")
            elif inp is None and b.kind in ("rolling_mean", "cumulative_dose", "rate_of_change", "threshold_alarm",
                                            "stillness_timer", "spike_then_still"):
                raise ParamError(f"device {name!r}: {b.kind} {b.output} needs an input")
            if b.kind in MOTION_BLOCKS and (inp not in CATALOG or not CATALOG[inp].vector):
                raise ParamError(f"device {name!r}: {b.kind} needs an accelerometer quantity as input")
            for c in block_outputs(b):
                known.add(c)
        cols = self.columns()
        dup = {c for c in cols if cols.count(c) > 1}
        if dup:
            raise ParamError(f"device {name!r}: duplicate columns {sorted(dup)}; give the parts an 'as' alias")
        for c, f in self.output_format.items():
            if c not in cols[2:]:
                raise ParamError(f"device {name!r}: output_format names {c!r}, which is not one of its columns {cols[2:]}")
            check_source(f"{name}.output_format.{c}", f)
        try:
            self.output_transforms()
        except Exception as e:
            raise ParamError(f"device {name!r}: output_format: {e}") from None
        out = self.output_columns()
        dup = {c for c in out if out.count(c) > 1}
        if dup:
            raise ParamError(f"device {name!r}: output_format gives duplicate column names {sorted(dup)}")

    # saving
    def to_dict(self) -> dict:
        parts = []
        for u in self.parts:
            e = {"part": u.part.slug}
            if u.overrides:
                e["overrides"] = u.overrides
            if u.log is not True:
                e["log"] = u.log
            if u.alias:
                e["as"] = u.alias
            if u.note:
                e["note"] = u.note
            parts.append(e)
        d = {"name": self.name, "slug": self.slug, "device_id_prefix": self.device_id_prefix,
             "description": self.description, "created": self.created, "version": self.version}
        if self.preset:
            d["preset"] = True
        if self.datasheet:
            d["datasheet"] = self.datasheet
        d["parts"] = parts
        if self.notes:
            d["notes"] = self.notes
        if self.features:
            d["features"] = self.features
        if self.logic:
            d["logic"] = self.logic
        if self.output_format:
            d["output_format"] = self.output_format
        return d


def _versions(devices_dir, slug) -> Dict[int, str]:
    out = {}
    for p in glob.glob(os.path.join(devices_dir, f"{slug}.yaml")) + glob.glob(os.path.join(devices_dir, f"{slug}.v*.yaml")):
        m = re.fullmatch(re.escape(slug) + r"(?:\.v(\d+))?\.yaml", os.path.basename(p))
        if m:
            with open(p) as fh:
                out[int(yaml.safe_load(fh).get("version", m.group(1) or 1))] = p
    return out


def save_device(d: dict, devices_dir: str = DEVICES_DIR, parts_dir: str = PARTS_DIR) -> Device:
    """Save a device the user assembled. The slug comes from the name; an existing name gets
    version + 1 in a new file (<slug>.v<N>.yaml), so no earlier version is overwritten."""
    d = dict(d)
    d["slug"] = slugify(d["name"])
    existing = _versions(devices_dir, d["slug"])
    if existing:
        with open(existing[max(existing)]) as fh:
            prev = yaml.safe_load(fh)
        if prev["name"] != d["name"]:
            raise ParamError(f"the name {d['name']!r} gives the file name {d['slug']!r}, already used by "
                             f"{prev['name']!r}; choose another name")
        if prev.get("preset"):
            raise ParamError(f"{prev['name']!r} is a preset; save your version under a new name")
    d["version"] = max(existing) + 1 if existing else 1
    d.setdefault("created", _dt.date.today().isoformat())
    d.pop("preset", None)
    dev = Device.from_dict(d, parts_dir)                     # validate before writing
    os.makedirs(devices_dir, exist_ok=True)
    path = os.path.join(devices_dir, f"{dev.slug}.yaml" if dev.version == 1 else f"{dev.slug}.v{dev.version}.yaml")
    if os.path.exists(path):
        raise FileExistsError(path)
    with open(path, "w") as fh:
        yaml.safe_dump(dev.to_dict(), fh, sort_keys=False, allow_unicode=True)
    dev.path = path
    return dev


def list_devices(devices_dir: str = DEVICES_DIR) -> List[str]:
    """Slugs of every saved device (presets and the user's)."""
    names = {re.sub(r"(\.v\d+)?\.yaml$", "", os.path.basename(p)) for p in glob.glob(os.path.join(devices_dir, "*.yaml"))}
    return sorted(names)
