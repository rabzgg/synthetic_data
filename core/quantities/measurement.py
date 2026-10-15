"""
measurement.py — the generic way a sensor turns the world's true value into a reading.

The same model serves every quantity in the catalog; only its parameters differ. The parameters
are the standard ones datasheets give (after normalisation, see normalize.py):

    range, resolution, accuracy (+ % of reading), noise_sd (or noise_density + bandwidth_hz),
    t90_s (optionally t90_up_s / t90_down_s), bandwidth_hz / odr_hz, hysteresis, drift_per_hour,
    deadband, cross_sensitivity, bias_distribution; for vector quantities also
    mounting_orientation, cross_axis_pct, misalignment_deg

The stages always run in this order:

    f. frame               vector quantities: world frame -> body (world's orientation) -> sensor
                           (mounting_orientation) -> this unit's axes (misalignment, cross-axis)
    0. cross-sensitivity   interfering quantities are added to what the sensing element sees
    1. response            first order, time constant tau = t90 / ln(10)
    2. bandwidth           first-order low-pass, cutoff bandwidth_hz (default ODR / 2 when only odr_hz is given)
    3. bias + drift        one bias per unit and axis, drawn once within ±accuracy; drift grows linearly
    4. noise               white Gaussian, sd per sample
    5. hysteresis          play operator: the output lags a reversal by up to hysteresis / 2
    6. deadband            values within ±deadband of deadband_center read as deadband_center
    7. quantisation        to the resolution
    8. clip                to the range; over_range / under_range flag what was cut off

What is fixed for one physical unit (bias, drift rate, axis errors) is drawn once per unit, within
the datasheet bound, from bias_distribution: uniform (default) or normal with sd = bound / 3,
truncated at the bound. Both are ASSUMPTIONs: datasheets give the bound, not the distribution.

Every parameter in a part file is {"value", "unit", "source"}; the source is either
"datasheet <document> p.<page>" or "ASSUMPTION: <reason>". from_params enforces that and converts
the unit to the quantity's canonical unit.
"""
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy.signal import lfilter

from . import rotation as rot
from .catalog import Quantity, get
from .units import UnitError, convert

LN10 = float(np.log(10.0))
STAGES = ("world", "frame", "cross", "response", "bandwidth", "bias_drift", "noise", "hysteresis", "deadband",
          "quantized")


@dataclass(frozen=True)
class Param:
    kind: str        # q = quantity unit, q/h, q/√Hz, s, Hz, %, deg, quat, - (no unit), cross
    default: object
    meaning: str
    vector_only: bool = False


PARAMETERS = {
    "range": Param("q", None, "[low, high] the sensor can report (vectors: one pair, or one pair per axis); required"),
    "resolution": Param("q", None, "smallest reported step; required"),
    "accuracy": Param("q", 0.0, "± bound of the bias of one unit (absolute part)"),
    "accuracy_pct_reading": Param("%", 0.0, "± bound of the bias of one unit, in % of the reading"),
    "accuracy_combine": Param("-", "sum", "how the two accuracy parts combine: sum (±(a + b %)) or max (whichever greater)"),
    "bias_distribution": Param("-", "uniform", "how per-unit errors are drawn within their bound: uniform, or normal "
                                               "(sd = bound / 3, truncated at the bound); source must be an ASSUMPTION"),
    "noise_sd": Param("q", 0.0, "standard deviation of the white noise per sample"),
    "noise_density": Param("q/√Hz", None, "noise spectral density; noise_sd = noise_density × √bandwidth_hz"),
    "bandwidth_hz": Param("Hz", None, "cutoff of the first-order low-pass on the signal; also sets noise_sd from "
                                      "noise_density"),
    "odr_hz": Param("Hz", None, "output data rate; when bandwidth_hz is not given, bandwidth = ODR / 2 (ASSUMPTION)"),
    "t90_s": Param("s", 0.0, "time to reach 90 % of a step; 0 = instant"),
    "t90_up_s": Param("s", None, "t90 for a rising input (default t90_s)"),
    "t90_down_s": Param("s", None, "t90 for a falling input (default t90_s)"),
    "hysteresis": Param("q", 0.0, "full width of the hysteresis band"),
    "drift_per_hour": Param("q/h", 0.0, "± bound of the linear drift rate of one unit"),
    "deadband": Param("q", 0.0, "values within ±deadband of deadband_center are reported as deadband_center"),
    "deadband_center": Param("q", 0.0, "centre of the deadband (e.g. 0 for a toxic gas, 20.9 for O2)"),
    "cross_sensitivity": Param("cross", {}, "{quantity: {factor, ref}}: adds factor × (other − ref) to the input"),
    "mounting_orientation": Param("quat", None, "how the part sits on the body: quaternion [w, x, y, z] from sensor "
                                                "frame to body frame (default: aligned)", True),
    "cross_axis_pct": Param("%", 0.0, "± bound of each off-diagonal element of the cross-axis matrix of one unit", True),
    "misalignment_deg": Param("deg", 0.0, "± bound of the angle by which the axes of one unit are rotated", True),
}
SOURCE_PREFIXES = ("datasheet", "ASSUMPTION")
DEFAULT_SOURCES = {"bias_distribution": "ASSUMPTION: default; uniform within the datasheet bound (the datasheet "
                                        "gives the bound, not the distribution)"}


class ParamError(ValueError):
    pass


def check_source(name: str, p: dict):
    if not isinstance(p, dict) or not {"value", "unit", "source"} <= set(p):
        raise ParamError(f"{name}: expected {{value, unit, source}}, got {p!r}")
    if not str(p["source"]).startswith(SOURCE_PREFIXES):
        raise ParamError(f"{name}: source must start with 'datasheet' or 'ASSUMPTION', got {p['source']!r}")


@dataclass
class UnitDraw:
    """What is fixed for one physical unit, each as a fraction of its bound in [-1, 1]:
    where in ±accuracy its bias sits and its drift rate; for vectors also the axes matrix."""
    u_bias: np.ndarray
    u_drift: np.ndarray
    axes: Optional[np.ndarray] = None         # (3, 3): this unit's axes (misalignment @ (I + cross-axis))


@dataclass
class Reading:
    values: np.ndarray
    over_range: np.ndarray
    under_range: np.ndarray
    stages: dict = field(default_factory=dict)


@dataclass
class MeasurementModel:
    quantity: Quantity
    range: tuple
    resolution: float
    accuracy: float = 0.0
    accuracy_pct_reading: float = 0.0
    accuracy_combine: str = "sum"
    bias_distribution: str = "uniform"
    noise_sd: float = 0.0
    bandwidth_hz: Optional[float] = None
    odr_hz: Optional[float] = None
    t90_s: float = 0.0
    t90_up_s: Optional[float] = None
    t90_down_s: Optional[float] = None
    hysteresis: float = 0.0
    drift_per_hour: float = 0.0
    deadband: float = 0.0
    deadband_center: float = 0.0
    cross_sensitivity: dict = field(default_factory=dict)
    mounting_orientation: Optional[tuple] = None
    cross_axis_pct: float = 0.0
    misalignment_deg: float = 0.0
    sources: dict = field(default_factory=dict)

    def __post_init__(self):
        qid = self.quantity.id
        r = np.asarray(self.range, float)
        if r.shape not in ((2,), (self.n_axes, 2)):
            raise ParamError(f"{qid}: range must be [low, high]" + (" or one pair per axis" if self.quantity.vector else ""))
        if not (r[..., 0] < r[..., 1]).all():
            raise ParamError(f"{qid}: range low must be below high, got {self.range}")
        if self.resolution <= 0:
            raise ParamError(f"{qid}: resolution must be > 0")
        if self.accuracy_combine not in ("sum", "max"):
            raise ParamError(f"{qid}: accuracy_combine must be 'sum' or 'max'")
        if self.bias_distribution not in ("uniform", "normal"):
            raise ParamError(f"{qid}: bias_distribution must be 'uniform' or 'normal'")
        for k in ("accuracy", "accuracy_pct_reading", "noise_sd", "t90_s", "hysteresis", "drift_per_hour", "deadband",
                  "cross_axis_pct", "misalignment_deg"):
            if getattr(self, k) < 0:
                raise ParamError(f"{qid}: {k} must be >= 0")
        for k in ("bandwidth_hz", "odr_hz"):
            if getattr(self, k) is not None and getattr(self, k) <= 0:
                raise ParamError(f"{qid}: {k} must be > 0")
        if not self.quantity.vector:
            for k, p in PARAMETERS.items():
                if p.vector_only and getattr(self, k) not in (None, 0.0):
                    raise ParamError(f"{qid}: {k} only applies to vector quantities")
        if self.mounting_orientation is not None:
            q = np.asarray(self.mounting_orientation, float)
            if q.shape != (4,) or abs(np.linalg.norm(q) - 1) > 1e-6:
                raise ParamError(f"{qid}: mounting_orientation must be a unit quaternion [w, x, y, z]")
        for q, c in self.cross_sensitivity.items():
            if get(q).vector:
                raise ParamError(f"{qid}: cross-sensitivity to a vector quantity ({q}) is not supported")
            if set(c) != {"factor", "ref"}:
                raise ParamError(f"{qid}: cross_sensitivity[{q}] needs factor and ref")
        for k, s in DEFAULT_SOURCES.items():
            self.sources.setdefault(k, s)

    # construction from a part file
    @classmethod
    def from_params(cls, quantity_id: str, params: dict) -> "MeasurementModel":
        """params: {name: {value, unit, source}} as written in a part file, in any convertible unit."""
        q = get(quantity_id)
        unknown = set(params) - set(PARAMETERS)
        if unknown:
            raise ParamError(f"{quantity_id}: unknown parameter(s) {sorted(unknown)}; known: {list(PARAMETERS)}")
        for req in ("range", "resolution"):
            if req not in params:
                raise ParamError(f"{quantity_id}: {req} is required")
        kw, sources = {}, {}
        for name, p in params.items():
            check_source(name, p)
            sources[name] = p["source"]
            kw[name] = _to_canonical(q, name, p)
        if "bias_distribution" in params and not str(params["bias_distribution"]["source"]).startswith("ASSUMPTION"):
            raise ParamError(f"{quantity_id}: bias_distribution is never in a datasheet; its source must be an ASSUMPTION")
        if "bandwidth_hz" not in kw and "odr_hz" in kw:
            kw["bandwidth_hz"] = kw["odr_hz"] / 2
            sources["bandwidth_hz"] = f"ASSUMPTION: bandwidth = ODR / 2 (no bandwidth given; ODR: {sources['odr_hz']})"
        if "noise_density" in kw:
            if "bandwidth_hz" not in kw:
                raise ParamError(f"{quantity_id}: noise_density needs bandwidth_hz (or odr_hz)")
            if "noise_sd" in kw:
                raise ParamError(f"{quantity_id}: give noise_sd or noise_density, not both")
            kw["noise_sd"] = kw.pop("noise_density") * float(np.sqrt(kw["bandwidth_hz"]))
            sources["noise_sd"] = f"{sources['noise_density']}; noise_density × √bandwidth_hz ({sources['bandwidth_hz']})"
        kw["range"] = tuple(tuple(r) if isinstance(r, (list, tuple)) else r for r in kw["range"])
        if kw.get("mounting_orientation") is not None:
            kw["mounting_orientation"] = tuple(kw["mounting_orientation"])
        return cls(quantity=q, sources=sources, **kw)

    # helpers
    @property
    def n_axes(self) -> int:
        return len(self.quantity.axes) or 1

    @property
    def bounds(self):
        """(low, high), each a float or an array per axis."""
        r = np.asarray(self.range, float)
        return r[..., 0], r[..., 1]

    def t90(self, rising: bool) -> float:
        v = self.t90_up_s if rising else self.t90_down_s
        return self.t90_s if v is None else v

    def error_bound(self, x):
        """Bias bound at true value x: accuracy and % of reading, combined as declared."""
        a, b = self.accuracy, self.accuracy_pct_reading / 100.0 * np.abs(x)
        return a + b if self.accuracy_combine == "sum" else np.maximum(a, b)

    def _unit_fraction(self, rng, size):
        """Fractions of a bound in [-1, 1]: uniform, or normal with sd 1/3 truncated at ±1."""
        if self.bias_distribution == "uniform":
            return rng.uniform(-1, 1, size)
        u = rng.normal(0, 1 / 3, size)
        while (bad := np.abs(u) > 1).any():
            u[bad] = rng.normal(0, 1 / 3, int(bad.sum()))
        return u

    def draw(self, rng) -> UnitDraw:
        d = UnitDraw(self._unit_fraction(rng, self.n_axes), self._unit_fraction(rng, self.n_axes))
        if self.quantity.vector:
            c = self._unit_fraction(rng, (3, 3)) * self.cross_axis_pct / 100.0
            np.fill_diagonal(c, 0.0)
            axis = rng.normal(size=3)
            angle = np.radians(self.misalignment_deg) * abs(self._unit_fraction(rng, 1)[0])
            mis = rot.to_matrix(rot.from_axis_angle(axis / np.linalg.norm(axis) * angle))
            d.axes = mis @ (np.eye(3) + c)
        return d

    # stages
    def to_sensor_frame(self, x, body_quat, draw: UnitDraw):
        """World-frame vectors -> this unit's sensor axes. body_quat: body -> world, (4,) or (n, 4);
        None = the body frame is the world frame."""
        v = x if body_quat is None else rot.rotate(rot.conj(body_quat), x)
        if self.mounting_orientation is not None:
            v = rot.rotate(rot.conj(self.mounting_orientation), v)
        return v if draw.axes is None else v @ draw.axes.T

    def respond(self, x, dt):
        up, down = self.t90(True), self.t90(False)
        if up == 0 and down == 0:
            return x.copy()
        ku = 1.0 if up == 0 else 1 - np.exp(-dt * LN10 / up)
        kd = 1.0 if down == 0 else 1 - np.exp(-dt * LN10 / down)
        if ku == kd:
            return _first_order(x, ku)
        y = np.empty_like(x)
        prev = x[0].copy()
        for i in range(len(x)):
            d = x[i] - prev
            prev = prev + d * np.where(d > 0, ku, kd)
            y[i] = prev
        return y

    def band_limit(self, x, dt):
        if self.bandwidth_hz is None:
            return x
        return _first_order(x, 1 - np.exp(-2 * np.pi * self.bandwidth_hz * dt))

    def bias_drift(self, y, t_h, draw: UnitDraw):
        return (y + draw.u_bias * self.error_bound(y)
                + draw.u_drift * self.drift_per_hour * t_h.reshape((-1,) + (1,) * (y.ndim - 1)))

    def hysteresize(self, y):
        h = self.hysteresis / 2
        if h == 0:
            return y
        out = np.empty_like(y)
        prev = y[0].copy()
        for i in range(len(y)):
            prev = np.minimum(np.maximum(prev, y[i] - h), y[i] + h)
            out[i] = prev
        return out

    def apply_deadband(self, y):
        if self.deadband == 0:
            return y
        return np.where(np.abs(y - self.deadband_center) < self.deadband, self.deadband_center, y)

    def quantize(self, y):
        return np.round(np.round(y / self.resolution) * self.resolution, 10) + 0.0     # + 0.0: no -0.0

    # the whole chain
    def measure(self, x, dt: float, rng, others: dict = None, draw: UnitDraw = None, t0_s: float = 0.0,
                body_quat=None, keep_stages: bool = False) -> Reading:
        """x: true world values at a fixed step dt (s); shape (n,) for a scalar, (n, 3) for a vector
        quantity (in the world frame). others: {quantity_id: array (n,)} for cross-sensitivity.
        draw: the unit's fixed errors (drawn from rng when not given). body_quat: body -> world."""
        x = np.asarray(x, float)
        if self.quantity.vector and (x.ndim != 2 or x.shape[1] != self.n_axes):
            raise ValueError(f"{self.quantity.id}: expected shape (n, {self.n_axes}), got {x.shape}")
        if not self.quantity.vector and x.ndim != 1:
            raise ValueError(f"{self.quantity.id}: expected shape (n,), got {x.shape}")
        draw = draw or self.draw(rng)
        st = {"world": x}
        if self.quantity.vector:
            x = self.to_sensor_frame(x, body_quat, draw)
        st["frame"] = x
        if self.cross_sensitivity:
            missing = set(self.cross_sensitivity) - set(others or {})
            if missing:
                raise ValueError(f"{self.quantity.id}: cross-sensitivity needs world values of {sorted(missing)}")
            x = x + sum(c["factor"] * (np.asarray(others[q], float) - c["ref"])
                        for q, c in self.cross_sensitivity.items())
        st["cross"] = x
        y = st["response"] = self.respond(x, dt)
        y = st["bandwidth"] = self.band_limit(y, dt)
        t_h = (t0_s + dt * np.arange(len(x))) / 3600.0
        y = st["bias_drift"] = self.bias_drift(y, t_h, draw)
        if self.noise_sd > 0:
            y = y + rng.normal(0.0, self.noise_sd, y.shape)
        st["noise"] = y
        y = st["hysteresis"] = self.hysteresize(y)
        y = st["deadband"] = self.apply_deadband(y)
        y = st["quantized"] = self.quantize(y)
        lo, hi = self.bounds
        r = Reading(np.clip(y, lo, hi) + 0.0, y > hi, y < lo)
        if keep_stages:
            r.stages = st
        return r


def _first_order(x, k):
    """y[i] = y[i-1] + k (x[i] - y[i-1]), starting at y[0] = x[0]."""
    if k >= 1:
        return x.copy()
    return lfilter([k], [1, -(1 - k)], x, axis=0, zi=(1 - k) * x[:1])[0]


def _to_canonical(q: Quantity, name: str, p: dict):
    kind, v, u = PARAMETERS[name].kind, p["value"], p["unit"]
    try:
        if kind == "q":
            return convert(v, u, q.unit)
        if kind in ("q/h", "q/√Hz"):
            return convert(v, u, q.unit + kind[1:])
        if kind in ("s", "Hz"):
            return convert(v, u, kind)
        if kind == "%":
            if u != "%":
                raise UnitError(f"expected '%', got {u!r}")
            return v
        if kind == "deg":
            if u not in ("°", "deg"):
                raise UnitError(f"expected '°' or 'deg', got {u!r}")
            return v
        if kind in ("-", "quat"):
            return v
        # cross: {quantity: {factor, ref}}, factor in this quantity's unit per the other's unit
        return {oq: {"factor": c["factor"], "ref": c["ref"]} for oq, c in v.items()}
    except UnitError as e:
        raise ParamError(f"{q.id}.{name}: {e}") from None
