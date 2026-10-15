"""
normalize.py — datasheet wording -> parameters of the generic measurement model.

Datasheets say the same thing in many ways ("accuracy", "tolerance", "max. error"; noise as RMS,
peak-to-peak or density). Each rule below turns one way of saying it into model parameters, with
the conversion written into the source string. Where a conversion needs a choice the datasheet does
not make, the source says "ASSUMPTION" and why.

docs/PARAMETER_MAPPING.md is generated from this file and from the catalog:
    python3 cli/parameter_mapping.py
"""
import math
import os
from dataclasses import dataclass
from typing import Callable

from .catalog import CATALOG
from .measurement import PARAMETERS
from .units import canonical

LN10, LN2 = math.log(10.0), math.log(2.0)
PP_TO_SD = 6.6           # Gaussian: 99.9 % of samples lie within ±3.3 sd


def _p(value, unit, source, note=""):
    return {"value": value, "unit": unit, "source": source + (f"; {note}" if note else "")}


@dataclass(frozen=True)
class Rule:
    id: str
    says: str                 # how the datasheet says it
    maps_to: str              # model parameter(s)
    how: str                  # the conversion, in words
    fn: Callable              # (value, unit, source, **ctx) -> {param: {value, unit, source}}
    example: tuple            # (quantity, value, unit, ctx, expected model attributes after from_params)
    assumption: str = ""
    example_text: str = ""    # how the example reads in the docs, when "value unit" would be unclear


def _range(v, u, s, symmetric=False):
    return {"range": _p([-v, v] if symmetric else list(v), u, s)}


def _sensitivity(v, u, s):
    lsb, per = u.split("/", 1)
    if lsb.strip().upper() != "LSB":
        raise ValueError(f"sensitivity unit must be LSB/<unit>, got {u!r}")
    return {"resolution": _p(1.0 / v, per, s, f"resolution = 1 / sensitivity ({v} {u})")}


def _bits(v, u, s, span):
    return {"resolution": _p((span[1] - span[0]) / 2 ** v, u, s, f"resolution = range / 2^{v}")}


def _pct_fs(v, u, s, full_scale):
    return {"accuracy": _p(v / 100.0 * full_scale, u, s, f"accuracy = {v} % × full scale {full_scale}")}


def _sum(v, u, s):
    a, pct = v
    return {"accuracy": _p(a, u, s), "accuracy_pct_reading": _p(pct, "%", s),
            "accuracy_combine": _p("sum", "-", s, "±(a + b % of reading)")}


def _max(v, u, s):
    a, pct = v
    return {"accuracy": _p(a, u, s), "accuracy_pct_reading": _p(pct, "%", s),
            "accuracy_combine": _p("max", "-", s, "whichever is greater")}


def _density(v, u, s, bandwidth_hz=None, odr_hz=None):
    if bandwidth_hz is None:
        if odr_hz is None:
            raise ValueError("noise density needs bandwidth_hz or odr_hz")
        return {"noise_density": _p(v, u, s),
                "bandwidth_hz": _p(odr_hz / 2, "Hz", f"ASSUMPTION: bandwidth = ODR / 2 = {odr_hz / 2:g} Hz; the "
                                                      f"datasheet gives no bandwidth (ODR from {s})")}
    return {"noise_density": _p(v, u, s), "bandwidth_hz": _p(bandwidth_hz, "Hz", s)}


def _temp_coef(v, u, s, ref_c=None):
    ref, note = (ref_c, "") if ref_c is not None else (25.0, "ASSUMPTION: reference 25 °C, none given")
    num = u.split("/")[0]
    return {"cross_sensitivity": _p({"air.temperature_c": {"factor": v, "ref": ref}}, "-", s,
                                    f"factor in {num} per °C" + (f"; {note}" if note else ""))}


def _mounting(v, u, s):
    from .rotation import from_euler_deg
    q = [round(float(c), 9) for c in from_euler_deg(*v)]
    return {"mounting_orientation": _p(q, "-", s, f"from roll/pitch/yaw {list(v)}° (Z-Y-X)")}


def _cross(v, u, s, gas, applied):
    return {"cross_sensitivity": _p({gas: {"factor": v / applied, "ref": 0.0}}, "-", s,
                                    f"{applied:g} of {gas} reads as {v:g} {u}: factor {v / applied:g}")}


RULES = [
    Rule("range", "Measurement range 0 … R, or lo … hi", "range", "taken as is",
         _range, ("air.humidity_rh", [0, 100], "%RH", {}, {"range": (0, 100)})),
    Rule("range_symmetric", "Full scale ±R (e.g. ±16 g)", "range", "[−R, +R]",
         lambda v, u, s: _range(v, u, s, True), ("body.accel_g", 16, "g", {}, {"range": (-16, 16)})),
    Rule("resolution", "Resolution X; LSB size X", "resolution", "taken as is",
         lambda v, u, s: {"resolution": _p(v, u, s)}, ("air.h2s_ppm", 0.1, "ppm", {}, {"resolution": 0.1})),
    Rule("sensitivity_lsb", "Sensitivity S LSB/unit (digital sensors)", "resolution", "resolution = 1 / S",
         _sensitivity, ("body.accel_g", 1024, "LSB/g", {}, {"resolution": 1 / 1024})),
    Rule("bits", "N-bit output over a span", "resolution", "resolution = span / 2^N",
         _bits, ("air.pressure_hpa", 16, "hPa", {"span": [300, 1100]}, {"resolution": 800 / 2 ** 16}),
         example_text="16 bit over 300 … 1100 hPa"),
    Rule("accuracy", "Accuracy ±X; tolerance ±X; max. error ±X; absolute accuracy ±X", "accuracy",
         "bias of one unit drawn uniformly in ±X, fixed for the whole run",
         lambda v, u, s: {"accuracy": _p(v, u, s)}, ("air.temperature_c", 0.5, "°C", {}, {"accuracy": 0.5})),
    Rule("accuracy_pct_reading", "Accuracy ±Y % of reading", "accuracy_pct_reading",
         "bias drawn in ±Y % of the current value (a gain error)",
         lambda v, u, s: {"accuracy_pct_reading": _p(v, "%", s)}, ("air.co_ppm", 5, "%", {}, {"accuracy_pct_reading": 5})),
    Rule("accuracy_pct_fs", "Accuracy ±Y % of full scale (FS)", "accuracy", "accuracy = Y / 100 × FS",
         _pct_fs, ("air.co_ppm", 2, "ppm", {"full_scale": 500}, {"accuracy": 10.0})),
    Rule("accuracy_sum", "Accuracy ±(X + Y % of reading)", "accuracy, accuracy_pct_reading, accuracy_combine = sum",
         "bound = X + Y % × |value|", _sum, ("air.co2_ppm", (30, 3), "ppm", {}, {"accuracy": 30, "accuracy_pct_reading": 3, "accuracy_combine": "sum"}),
         example_text="±(30 ppm + 3 % of reading)"),
    Rule("accuracy_max", "Accuracy ±X or ±Y % of reading, whichever is greater",
         "accuracy, accuracy_pct_reading, accuracy_combine = max", "bound = max(X, Y % × |value|)",
         _max, ("air.h2s_ppm", (2, 10), "ppm", {}, {"accuracy": 2, "accuracy_pct_reading": 10, "accuracy_combine": "max"}),
         example_text="±2 ppm or ±10 % of reading"),
    Rule("accuracy_typical", "Typical accuracy ±X, no maximum given", "accuracy", "used as the bound",
         lambda v, u, s: {"accuracy": _p(v, u, s, "ASSUMPTION: typical value used as the bound, no maximum given")},
         ("air.pressure_hpa", 1.0, "hPa", {}, {"accuracy": 1.0}),
         "A typical value is not a guaranteed bound; real units can be worse."),
    Rule("noise_rms", "Noise X RMS; noise sd X; 1σ X", "noise_sd", "taken as is",
         lambda v, u, s: {"noise_sd": _p(v, u, s)}, ("air.temperature_c", 0.02, "°C", {}, {"noise_sd": 0.02})),
    Rule("noise_pp", "Noise X peak-to-peak", "noise_sd", f"noise_sd = X / {PP_TO_SD}",
         lambda v, u, s: {"noise_sd": _p(v / PP_TO_SD, u, s, f"ASSUMPTION: Gaussian, peak-to-peak = {PP_TO_SD} × sd")},
         ("body.accel_g", 0.66, "mg", {}, {"noise_sd": 1e-4}), "Gaussian noise; 99.9 % of samples within ±3.3 sd."),
    Rule("noise_density", "Noise density D per √Hz", "noise_density, bandwidth_hz",
         "noise_sd = D × √bandwidth; without a bandwidth, bandwidth = ODR / 2",
         _density, ("body.accel_g", 150, "µg/√Hz", {"bandwidth_hz": 100}, {"noise_sd": 1.5e-3}),
         "Only when the datasheet gives no bandwidth: ODR / 2 (Nyquist)."),
    Rule("repeatability", "Repeatability ±X (no σ stated)", "noise_sd", "noise_sd = X / 2",
         lambda v, u, s: {"noise_sd": _p(v / 2, u, s, "ASSUMPTION: ±X read as ±2 sd")},
         ("air.humidity_rh", 0.2, "%RH", {}, {"noise_sd": 0.1}), "±X read as ±2 sd (95 %)."),
    Rule("t90", "Response time T90 (t90)", "t90_s", "taken as is; first order, tau = T90 / ln 10",
         lambda v, u, s: {"t90_s": _p(v, u, s)}, ("air.h2s_ppm", 15, "s", {}, {"t90_s": 15})),
    Rule("t63", "Time constant tau; T63", "t90_s", "t90 = tau × ln 10",
         lambda v, u, s: {"t90_s": _p(v * LN10, u, s, "t90 = tau × ln 10 (first order)")},
         ("air.temperature_c", 1, "s", {}, {"t90_s": LN10})),
    Rule("t50", "Response time T50", "t90_s", "t90 = T50 × ln 10 / ln 2",
         lambda v, u, s: {"t90_s": _p(v * LN10 / LN2, u, s, "t90 = T50 × ln 10 / ln 2 (first order)")},
         ("air.co_ppm", 10, "s", {}, {"t90_s": 10 * LN10 / LN2})),
    Rule("recovery_t90", "Recovery / fall time T90 (back to zero)", "t90_down_s", "taken as is",
         lambda v, u, s: {"t90_down_s": _p(v, u, s)}, ("air.co_ppm", 60, "s", {}, {"t90_down_s": 60})),
    Rule("drift", "Long-term stability / drift ±X per year (month, day)", "drift_per_hour",
         "unit conversion to per hour (year = 8760 h, month = 730 h)",
         lambda v, u, s: {"drift_per_hour": _p(v, u, s)}, ("air.humidity_rh", 0.25, "%RH/year", {}, {"drift_per_hour": 0.25 / 8760})),
    Rule("hysteresis_pm", "Hysteresis ±X", "hysteresis", "full width = 2X",
         lambda v, u, s: {"hysteresis": _p(2 * v, u, s, "±X read as a band of full width 2X")},
         ("air.humidity_rh", 1, "%RH", {}, {"hysteresis": 2})),
    Rule("hysteresis", "Hysteresis X (difference between rising and falling)", "hysteresis", "taken as is",
         lambda v, u, s: {"hysteresis": _p(v, u, s)}, ("air.humidity_rh", 0.5, "%RH", {}, {"hysteresis": 0.5})),
    Rule("bandwidth", "Bandwidth X Hz; −3 dB cutoff X Hz", "bandwidth_hz", "first-order low-pass with cutoff X",
         lambda v, u, s: {"bandwidth_hz": _p(v, u, s)}, ("body.accel_g", 62.5, "Hz", {}, {"bandwidth_hz": 62.5})),
    Rule("odr", "Output data rate (ODR) X Hz", "odr_hz", "taken as is; without a bandwidth, bandwidth = ODR / 2",
         lambda v, u, s: {"odr_hz": _p(v, u, s)}, ("body.gyro_dps", 100, "Hz", {}, {"odr_hz": 100, "bandwidth_hz": 50}),
         "Only when the datasheet gives no bandwidth: ODR / 2 (Nyquist)."),
    Rule("cross_axis", "Cross-axis sensitivity ±X %", "cross_axis_pct",
         "each off-diagonal element of one unit's axes matrix drawn within ±X %",
         lambda v, u, s: {"cross_axis_pct": _p(v, "%", s)}, ("body.accel_g", 1, "%", {}, {"cross_axis_pct": 1})),
    Rule("misalignment", "Axis misalignment / alignment error ±X°", "misalignment_deg",
         "one unit's axes rotated by up to X° about a random axis",
         lambda v, u, s: {"misalignment_deg": _p(v, "deg", s)}, ("body.mag_ut", 0.5, "°", {}, {"misalignment_deg": 0.5})),
    Rule("mounting_euler", "Mounting as roll, pitch, yaw (degrees, Z-Y-X)", "mounting_orientation",
         "quaternion sensor → body from yaw, then pitch, then roll", _mounting,
         ("body.accel_g", (90, 0, 0), "°", {}, {"mounting_orientation": (0.7071068, 0.7071068, 0.0, 0.0)}),
         example_text="roll 90°, pitch 0°, yaw 0°"),
    Rule("deadband", "Zero deadband / zero suppression X", "deadband (deadband_center = 0)",
         "values within ±X of zero are reported as zero",
         lambda v, u, s, center=0.0: {"deadband": _p(v, u, s), "deadband_center": _p(center, u, s)},
         ("air.co_ppm", 2, "ppm", {}, {"deadband": 2, "deadband_center": 0.0})),
    Rule("temperature_coefficient", "Temperature coefficient X per °C (of offset)", "cross_sensitivity to air.temperature_c",
         "adds X × (T − T_ref) to the input", _temp_coef,
         ("air.pressure_hpa", 0.01, "hPa/°C", {"ref_c": 25},
          {"cross_sensitivity": {"air.temperature_c": {"factor": 0.01, "ref": 25}}}),
         "Reference 25 °C when the datasheet gives none."),
    Rule("cross_gas", "Cross-sensitivity: C of gas G reads as R", "cross_sensitivity to G", "factor = R / C, ref 0",
         _cross, ("air.h2s_ppm", 6, "ppm", {"gas": "air.co_ppm", "applied": 300},
                  {"cross_sensitivity": {"air.co_ppm": {"factor": 0.02, "ref": 0.0}}})),
]
RULE_BY_ID = {r.id: r for r in RULES}


def normalize(rule_id: str, value, unit: str, source: str, **ctx) -> dict:
    """One datasheet statement -> {param: {value, unit, source}} for MeasurementModel.from_params."""
    if rule_id not in RULE_BY_ID:
        raise KeyError(f"unknown rule {rule_id!r}; known: {', '.join(RULE_BY_ID)}")
    return RULE_BY_ID[rule_id].fn(value, canonical(unit), source, **ctx)


def markdown() -> str:
    """docs/PARAMETER_MAPPING.md, generated from the catalog, PARAMETERS and RULES."""
    from .measurement import __doc__ as mdoc
    L = ["# Parameter mapping", "",
         "_Generated by `python3 cli/parameter_mapping.py` from `core/quantities/`; do not edit by hand._", "",
         "How a datasheet becomes a simulated reading: the **quantity catalog** says what can be measured, the "
         "**model parameters** are the one generic way every sensor measures, and the **normalisation rules** turn "
         "datasheet wording into those parameters.", "",
         "## Quantity catalog", "", "| id | name | unit | CSV column | physical bounds | note |", "|---|---|---|---|---|---|"]
    for q in CATALOG.values():
        b = f"{'−∞' if q.lower is None else f'{q.lower:g}'} … {'∞' if q.upper is None else f'{q.upper:g}'}"
        L.append(f"| `{q.id}` | {q.name} | {q.unit} | `{', '.join(q.columns())}` | {b} | {q.note} |")
    stages = mdoc.split("The stages always run in this order:")[1].split("What is fixed")[0].strip("\n")
    L += ["", "## Model parameters", "",
          "Every parameter in a part file is `{value, unit, source}`; `source` starts with `datasheet` or "
          "`ASSUMPTION`. Units are converted to the quantity's unit (`q` below).", "",
          "| parameter | unit | default | meaning |", "|---|---|---|---|"]
    for n, p in PARAMETERS.items():
        d = "required" if p.default is None and n in ("range", "resolution") else ("—" if p.default in (None, {}) else p.default)
        L.append(f"| `{n}` | {p.kind} | {d} | {p.meaning} |")
    unit_errors = " ".join(mdoc.split("What is fixed")[1].split("Every parameter")[0].split())
    L += ["", "## Order of the stages", "", "```", "\n".join(s[4:] for s in stages.splitlines()), "```", "",
          "What is fixed " + unit_errors, "",
          "## Normalisation rules", "",
          "| rule | the datasheet says | maps to | conversion | example | assumption |", "|---|---|---|---|---|---|"]
    for r in RULES:
        qid, v, u, ctx, exp = r.example
        q = CATALOG[qid]
        given = r.example_text or (f"{v} {u}" + (f" ({', '.join(f'{k}={c}' for k, c in ctx.items())})" if ctx else ""))
        ex = f"{q.name}: {given} → " + \
             ", ".join(f"{k} = {_fmt(e)}{_unit(q, k)}" for k, e in exp.items())
        L.append("| " + " | ".join(_cell(c) for c in (f"`{r.id}`", r.says, r.maps_to, r.how, ex, r.assumption or "—")) + " |")
    return "\n".join(L) + "\n"


def _cell(c):
    return str(c).replace("|", "\\|")


def _fmt(e):
    if isinstance(e, dict):
        return "; ".join(f"{q}: factor {c['factor']:g}, ref {c['ref']:g}" for q, c in e.items())
    if isinstance(e, tuple):
        return "[" + ", ".join(f"{x:.4g}" if isinstance(x, float) else str(x) for x in e) + "]"
    return f"{e:.6g}" if isinstance(e, float) else str(e)


def _unit(q, param):
    kind = PARAMETERS[param].kind
    u = {"q": q.unit, "q/h": q.unit + "/h", "s": "s", "Hz": "Hz", "%": " %", "deg": "°"}.get(kind, "")
    return f" {u}" if u and u != " %" else u


DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "docs",
                   "PARAMETER_MAPPING.md")
