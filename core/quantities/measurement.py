"""
measurement.py — the generic way a sensor turns the world's true value into a reading.

The same model serves every quantity in the catalog; only its parameters differ. The parameters
are the standard ones datasheets give (after normalisation, see normalize.py):

    range, resolution, accuracy (+ % of reading), noise_sd (or noise_density + bandwidth_hz),
    t90_s (optionally t90_up_s / t90_down_s), hysteresis, drift_per_hour, deadband,
    cross_sensitivity

The stages always run in this order:

    0. cross-sensitivity   interfering quantities are added to what the sensing element sees
    1. response            first order, time constant tau = t90 / ln(10)
    2. bias + drift        one bias per unit and axis, drawn once within ±accuracy; drift grows linearly
    3. noise               white Gaussian, sd per sample
    4. hysteresis          play operator: the output lags a reversal by up to hysteresis / 2
    5. deadband            values within ±deadband of deadband_center read as deadband_center
    6. quantisation        to the resolution
    7. clip                to the range; over_range / under_range flag what was cut off

Every parameter in a part file is {"value", "unit", "source"}; the source is either
"datasheet <document> p.<page>" or "ASSUMPTION: <reason>". from_params enforces that and converts
the unit to the quantity's canonical unit.
"""
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy.signal import lfilter

from .catalog import Quantity, get
from .units import UnitError, convert

LN10 = float(np.log(10.0))


@dataclass(frozen=True)
class Param:
    kind: str        # q = quantity unit, q/h, q/√Hz, s, Hz, %, - (no unit), cross
    default: object
    meaning: str


PARAMETERS = {
    "range": Param("q", None, "[low, high] the sensor can report; required"),
    "resolution": Param("q", None, "smallest reported step; required"),
    "accuracy": Param("q", 0.0, "± bound of the bias of one unit (absolute part)"),
    "accuracy_pct_reading": Param("%", 0.0, "± bound of the bias of one unit, in % of the reading"),
    "accuracy_combine": Param("-", "sum", "how the two accuracy parts combine: sum (±(a + b %)) or max (whichever greater)"),
    "noise_sd": Param("q", 0.0, "standard deviation of the white noise per sample"),
    "noise_density": Param("q/√Hz", None, "noise spectral density; noise_sd = noise_density × √bandwidth_hz"),
    "bandwidth_hz": Param("Hz", None, "measurement bandwidth, used with noise_density"),
    "t90_s": Param("s", 0.0, "time to reach 90 % of a step; 0 = instant"),
    "t90_up_s": Param("s", None, "t90 for a rising input (default t90_s)"),
    "t90_down_s": Param("s", None, "t90 for a falling input (default t90_s)"),
    "hysteresis": Param("q", 0.0, "full width of the hysteresis band"),
    "drift_per_hour": Param("q/h", 0.0, "± bound of the linear drift rate of one unit"),
    "deadband": Param("q", 0.0, "values within ±deadband of deadband_center are reported as deadband_center"),
    "deadband_center": Param("q", 0.0, "centre of the deadband (e.g. 0 for a toxic gas, 20.9 for O2)"),
    "cross_sensitivity": Param("cross", {}, "{quantity: {factor, ref}}: adds factor × (other − ref) to the input"),
}
SOURCE_PREFIXES = ("datasheet", "ASSUMPTION")


class ParamError(ValueError):
    pass


def check_source(name: str, p: dict):
    if not isinstance(p, dict) or not {"value", "unit", "source"} <= set(p):
        raise ParamError(f"{name}: expected {{value, unit, source}}, got {p!r}")
    if not str(p["source"]).startswith(SOURCE_PREFIXES):
        raise ParamError(f"{name}: source must start with 'datasheet' or 'ASSUMPTION', got {p['source']!r}")


@dataclass
class UnitDraw:
    """What is fixed for one physical unit: where in ±accuracy its bias sits, and its drift rate."""
    u_bias: np.ndarray
    u_drift: np.ndarray


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
    noise_sd: float = 0.0
    t90_s: float = 0.0
    t90_up_s: Optional[float] = None
    t90_down_s: Optional[float] = None
    hysteresis: float = 0.0
    drift_per_hour: float = 0.0
    deadband: float = 0.0
    deadband_center: float = 0.0
    cross_sensitivity: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)

    def __post_init__(self):
        lo, hi = self.range
        if not lo < hi:
            raise ParamError(f"{self.quantity.id}: range low {lo} must be below high {hi}")
        if self.resolution <= 0:
            raise ParamError(f"{self.quantity.id}: resolution must be > 0")
        if self.accuracy_combine not in ("sum", "max"):
            raise ParamError(f"{self.quantity.id}: accuracy_combine must be 'sum' or 'max'")
        for k in ("accuracy", "accuracy_pct_reading", "noise_sd", "t90_s", "hysteresis", "drift_per_hour", "deadband"):
            if getattr(self, k) < 0:
                raise ParamError(f"{self.quantity.id}: {k} must be >= 0")
        for q, c in self.cross_sensitivity.items():
            if get(q).vector:
                raise ParamError(f"{self.quantity.id}: cross-sensitivity to a vector quantity ({q}) is not supported")
            if set(c) != {"factor", "ref"}:
                raise ParamError(f"{self.quantity.id}: cross_sensitivity[{q}] needs factor and ref")

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
        if "noise_density" in kw:
            if "bandwidth_hz" not in kw:
                raise ParamError(f"{quantity_id}: noise_density needs bandwidth_hz")
            if "noise_sd" in kw:
                raise ParamError(f"{quantity_id}: give noise_sd or noise_density, not both")
            kw["noise_sd"] = kw["noise_density"] * float(np.sqrt(kw["bandwidth_hz"]))
            sources["noise_sd"] = f"{sources['noise_density']}; noise_density × √bandwidth_hz ({sources['bandwidth_hz']})"
        kw.pop("noise_density", None)
        kw.pop("bandwidth_hz", None)
        kw["range"] = tuple(kw["range"])
        return cls(quantity=q, sources=sources, **kw)

    # helpers
    @property
    def n_axes(self) -> int:
        return len(self.quantity.axes) or 1

    def t90(self, rising: bool) -> float:
        v = self.t90_up_s if rising else self.t90_down_s
        return self.t90_s if v is None else v

    def error_bound(self, x):
        """Bias bound at true value x: accuracy and % of reading, combined as declared."""
        a, b = self.accuracy, self.accuracy_pct_reading / 100.0 * np.abs(x)
        return a + b if self.accuracy_combine == "sum" else np.maximum(a, b)

    def draw(self, rng) -> UnitDraw:
        return UnitDraw(rng.uniform(-1, 1, self.n_axes), rng.uniform(-1, 1, self.n_axes))

    # stages
    def respond(self, x, dt):
        up, down = self.t90(True), self.t90(False)
        if up == 0 and down == 0:
            return x.copy()
        ku = 1.0 if up == 0 else 1 - np.exp(-dt * LN10 / up)
        kd = 1.0 if down == 0 else 1 - np.exp(-dt * LN10 / down)
        if ku == kd:
            zi = (1 - ku) * x[:1]
            return lfilter([ku], [1, -(1 - ku)], x, axis=0, zi=zi)[0]
        y = np.empty_like(x)
        prev = x[0].copy()
        for i in range(len(x)):
            d = x[i] - prev
            prev = prev + d * np.where(d > 0, ku, kd)
            y[i] = prev
        return y

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
                keep_stages: bool = False) -> Reading:
        """x: true world values at a fixed step dt (s); shape (n,) for a scalar, (n, 3) for a vector
        quantity. others: {quantity_id: array (n,)} for cross-sensitivity. draw: the unit's fixed bias
        and drift (drawn from rng when not given)."""
        x = np.asarray(x, float)
        if self.quantity.vector and (x.ndim != 2 or x.shape[1] != self.n_axes):
            raise ValueError(f"{self.quantity.id}: expected shape (n, {self.n_axes}), got {x.shape}")
        if not self.quantity.vector and x.ndim != 1:
            raise ValueError(f"{self.quantity.id}: expected shape (n,), got {x.shape}")
        draw = draw or self.draw(rng)
        st = {"world": x}
        if self.cross_sensitivity:
            missing = set(self.cross_sensitivity) - set(others or {})
            if missing:
                raise ValueError(f"{self.quantity.id}: cross-sensitivity needs world values of {sorted(missing)}")
            x = x + sum(c["factor"] * (np.asarray(others[q], float) - c["ref"])
                        for q, c in self.cross_sensitivity.items())
            st["cross"] = x
        y = st["response"] = self.respond(x, dt)
        t_h = (t0_s + dt * np.arange(len(x))) / 3600.0
        y = st["bias_drift"] = self.bias_drift(y, t_h, draw)
        if self.noise_sd > 0:
            y = y + rng.normal(0.0, self.noise_sd, y.shape)
        st["noise"] = y
        y = st["hysteresis"] = self.hysteresize(y)
        y = st["deadband"] = self.apply_deadband(y)
        y = st["quantized"] = self.quantize(y)
        lo, hi = self.range
        r = Reading(np.clip(y, lo, hi) + 0.0, y > hi, y < lo)
        if keep_stages:
            r.stages = st
        return r


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
        if kind == "-":
            return v
        # cross: {quantity: {factor, ref}}, factor in this quantity's unit per the other's unit
        return {oq: {"factor": c["factor"], "ref": c["ref"]} for oq, c in v.items()}
    except UnitError as e:
        raise ParamError(f"{q.id}.{name}: {e}") from None
