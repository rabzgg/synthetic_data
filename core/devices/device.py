"""
device.py — block [C]: a device the user assembles from parts, names and saves
(configs/devices/<slug>.yaml; later versions <slug>.v<N>.yaml).

    name: "Tank Monitor v1"            # free name from the user; the slug is made from it
    device_id_prefix: TANKMON          # device_id column = <prefix>-0001 (default: slug in capitals)
    description: "..."
    created: 2026-10-15
    version: 1
    parts:
      - part: bosch_bme280
      - part: blackline_h2s_cell
        overrides: {t90_s: {value: 25}}      # no source given -> "ASSUMPTION: user tweak"
        log: true                            # false, or a list of quantities, to measure without writing
        as: cell                             # column suffix when two parts measure the same quantity
    features:                                # all optional, each value {value, unit, source}
      sample_interval_s, alarms, exposure, over_range, derived, bump_test, states, battery_hours,
      connectivity, gateway

The CSV columns follow from the parts and features (columns()); nothing is typed twice.
Saving under a name that exists gives version + 1 in a new file; an older file is never overwritten.
"""
import datetime as _dt
import glob
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml

from core.derived import DERIVED, Stel, Twa
from core.quantities import CATALOG
from core.quantities.measurement import ParamError, check_source

from .parts import PARTS_DIR, Part

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEVICES_DIR = os.path.join(ROOT, "configs", "devices")

# feature -> what it means; the column rules are in Device.columns()
FEATURES = {
    "sample_interval_s": "logging interval",
    "alarms": "per quantity: low / high {value, unit, when: above|below, source}, stel / twa limits; latching",
    "exposure": "window_s (STEL) and period_s (TWA) for the exposure channels",
    "over_range": "quantities with an over-range flag column and when it is set",
    "derived": "derived channels: list of {kind, params, ...}",
    "bump_test": "the device runs bump tests (device_mode column)",
    "states": "device states with their own columns: sos, pump",
    "battery_hours": "battery runtime (battery_pct column)",
    "connectivity": "how it reports (signal_strength_dbm column)",
    "gateway": "reports through a gateway (gateway id and link columns)",
    "motion_alerts": "fall and no-motion detection from the accelerometer: fall_state and no_motion_state columns "
                     "(ok / pre_alarm / alert), written last",
}
MOTION_ALERTS = {"fall": ("pre_alarm_s",), "no_motion": ("detect_s", "pre_alarm_s")}
STATE_COLUMNS = {"sos": ["sos_state"], "pump": ["pump_state", "pump_alarm"]}
GATEWAY_COLUMNS = {"bridge": ["bridge_id", "bridge_link"]}
ALARM_LEVELS = ("low", "high", "stel", "twa")


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
    path: str = ""

    # loading
    @classmethod
    def from_dict(cls, d: dict, parts_dir: str = PARTS_DIR, path: str = "") -> "Device":
        unknown = set(d) - {"name", "slug", "device_id_prefix", "description", "created", "version", "preset",
                            "datasheet", "parts", "features", "notes"}
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
                  bool(d.get("preset", False)), d.get("datasheet", ""), list(d.get("notes") or []), path)
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

    # features
    def feature(self, key, default=None):
        f = self.features.get(key, default)
        return f["value"] if isinstance(f, dict) and "value" in f else f

    def alarms(self) -> Dict[str, dict]:
        return {q: a for q, a in (self.features.get("alarms") or {}).items() if q in CATALOG}

    def derived(self) -> list:
        """Derived channels: STEL / TWA for every alarm that has those limits, then features.derived."""
        exp = self.features.get("exposure") or {}
        out = []
        res = {q: m for _, q, m in self.models()}
        for q, a in self.alarms().items():
            m = res[q]
            qz = (m.resolution, float(m.bounds[0]), float(m.bounds[1]))
            if "stel" in a:
                out.append(Stel(q, {"window_s": exp["window_s"]} if "window_s" in exp else None, qz))
            if "twa" in a:
                out.append(Twa(q, {"period_s": exp["period_s"]} if "period_s" in exp else None, qz))
        for spec in self.features.get("derived") or []:
            spec = dict(spec)
            out.append(DERIVED[spec.pop("kind")](**spec))
        return out

    def stem(self, qid) -> str:
        return CATALOG[qid].column.split("_")[0]

    def columns(self) -> List[str]:
        """CSV columns, in this order: timestamp, device_id, gateway, readings, derived channels,
        device_mode, states, battery, signal, then per alarmed quantity its alarm flags and over-range,
        then the motion alert states (added later, so the gas columns keep their old order)."""
        f = self.features
        cols = ["timestamp", "device_id"]
        if f.get("gateway"):
            cols += GATEWAY_COLUMNS[f["gateway"]["kind"]]
        for _, _, c in self.reading_columns():
            cols += c
        for d in self.derived():
            cols += d.columns()
        if self.feature("bump_test"):
            cols.append("device_mode")
        for s, v in (f.get("states") or {}).items():
            if v.get("value"):
                cols += STATE_COLUMNS[s]
        if f.get("battery_hours"):
            cols.append("battery_pct")
        if f.get("connectivity"):
            cols.append("signal_strength_dbm")
        over = set((f.get("over_range") or {}).get("quantities", []))
        tail = [f"{k}_state" for k in MOTION_ALERTS if v_(f.get("motion_alerts", {}).get(k))]
        flagged = list(self.alarms()) + [q for q in self.measured() if q in over and q not in self.alarms()]
        for q in flagged:
            a = self.alarms().get(q, {})
            cols += [f"{self.stem(q)}_alarm_{lv}" for lv in ALARM_LEVELS if lv in a]
            if q in over:
                cols.append(f"{self.stem(q)}_over_range")
        return cols + tail

    def device_id(self, n: int = 1) -> str:
        return f"{self.device_id_prefix}-{n:04d}"

    # checks
    def validate(self):
        name, meas = self.name, self.measured()
        unknown = set(self.features) - set(FEATURES)
        if unknown:
            raise ParamError(f"device {name!r}: unknown feature(s) {sorted(unknown)}; known: {list(FEATURES)}")
        for k in ("sample_interval_s", "battery_hours", "connectivity", "bump_test"):
            if k in self.features:
                check_source(f"{name}.{k}", self.features[k])
        alarms = self.features.get("alarms") or {}
        for q, a in alarms.items():
            if q == "latching":
                check_source(f"{name}.alarms.latching", a)
                continue
            if q not in meas:
                raise ParamError(f"device {name!r}: alarm on {q}, which no part measures")
            if CATALOG[q].vector:
                raise ParamError(f"device {name!r}: alarms on vector quantities are not supported ({q})")
            for lv, spec in a.items():
                if lv not in ALARM_LEVELS:
                    raise ParamError(f"device {name!r}: unknown alarm level {lv!r} for {q}")
                check_source(f"{name}.alarms.{q}.{lv}", spec)
                if lv in ("low", "high") and spec.get("when") not in ("above", "below"):
                    raise ParamError(f"device {name!r}: alarm {q}.{lv} needs when: above|below")
        for k, v in (self.features.get("exposure") or {}).items():
            check_source(f"{name}.exposure.{k}", v)
        over = self.features.get("over_range")
        if over:
            check_source(f"{name}.over_range", {k: over.get(k) for k in ("value", "unit", "source")})
            for q in over.get("quantities", []):
                if q not in meas:
                    raise ParamError(f"device {name!r}: over_range on {q}, which no part measures")
        for s, v in (self.features.get("states") or {}).items():
            if s not in STATE_COLUMNS:
                raise ParamError(f"device {name!r}: unknown state {s!r}; known: {list(STATE_COLUMNS)}")
            check_source(f"{name}.states.{s}", v)
        ma = self.features.get("motion_alerts") or {}
        for k, spec in ma.items():
            if k not in MOTION_ALERTS:
                raise ParamError(f"device {name!r}: unknown motion alert {k!r}; known: {list(MOTION_ALERTS)}")
            check_source(f"{name}.motion_alerts.{k}", spec)
            for p in MOTION_ALERTS[k]:
                if p not in spec:
                    raise ParamError(f"device {name!r}: motion_alerts.{k} needs {p}")
                check_source(f"{name}.motion_alerts.{k}.{p}", spec[p])
        if ma and "body.accel_g" not in meas:
            raise ParamError(f"device {name!r}: motion alerts need an accelerometer (body.accel_g)")
        gw = self.features.get("gateway")
        if gw and gw.get("kind") not in GATEWAY_COLUMNS:
            raise ParamError(f"device {name!r}: unknown gateway kind {gw.get('kind')!r}")
        for d in self.derived():
            missing = set(d.inputs()) - set(meas)
            if missing:
                raise ParamError(f"device {name!r}: derived channel {d.kind} needs {sorted(missing)}, not measured")
        cols = self.columns()
        dup = {c for c in cols if cols.count(c) > 1}
        if dup:
            raise ParamError(f"device {name!r}: duplicate columns {sorted(dup)}; give the parts an 'as' alias")

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
