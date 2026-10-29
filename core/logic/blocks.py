"""
blocks.py — block [F]: device logic as generic blocks, listed in a device file under `logic:`.

Every block reads one input stream (a quantity the device measures, or the output column of an
earlier block) and writes one output column. Blocks run on the logging grid (what the device
records, every sample_interval_s, also during connection gaps: the device keeps measuring), except
the motion blocks, which run on the sensor's own fast stream (rate: internal) and report their
state at the logging times.

    constant         value                                        a fixed column (e.g. a gateway id)
    random_state     values, default, periods [lo, hi], duration_s [lo, hi]: a state that is
                     sometimes another value (e.g. a gateway's satellite link)
    rolling_mean     input, window_s, quantize: mean of the last window, samples before the start
                     count as 0 (an occupational STEL)
    cumulative_dose  input, period_s, quantize: sum of value × step since the start / period (a TWA)
    rate_of_change   input, window_s, per (s | min | h): change over the window
    threshold_alarm  input, level (number, range_min or range_max of the input's sensor), when
                     (above: >= level | below: <= level), hysteresis (default 0), latching
                     (default false), on_value / off_value (default 1 / 0)
    event_mode       event, value, default, until_back [quantities]: the value from the start of
                     that event until the listed readings are back where they were before it
    state_flag       state, on_value, off_value: on while a device event holds that state (pump, sos)
    battery          runtime_h, start_pct: linear drain over the runtime plus battery_drain events,
                     floored to whole %
    signal           range_dbm, start_dbm, step_sd_db: bounded random walk, one step per row, whole dBm
    stillness_timer  input (an accelerometer), window_s, threshold_g, detect_s, pre_alarm_s:
                     ok -> pre_alarm after detect_s without movement -> alert after pre_alarm_s more;
                     any movement -> ok
    spike_then_still input (an accelerometer), spike_g, tilt_deg, within_s, pre_alarm_s, reference_s:
                     an impact of at least spike_g followed within within_s by a tilt of at least
                     tilt_deg from the upright of the first reference_s -> pre_alarm; back upright
                     within pre_alarm_s cancels it, otherwise alert until upright again
    orientation_quat params of core/derived/fusion.py: fused orientation from accel, gyro, mag
Every number is {value, unit, source}. The same blocks run on the world's truth (no sensor errors)
to give the "expected" labels that the gate compares a device with.
"""
import numpy as np

from core.quantities import CATALOG
from core.quantities.measurement import ParamError, check_source

STATES = ("ok", "pre_alarm", "alert")


def v(p):
    return p["value"] if isinstance(p, dict) and "value" in p else p


class Stream:
    """Values of one input on the logging grid, or on a fast internal grid (t, values)."""

    def __init__(self, t, x, model=None):
        self.t, self.x, self.model = np.asarray(t, float), x, model

    def at(self, t):
        idx = np.clip(np.searchsorted(self.t, np.asarray(t, float) + 1e-9, side="right") - 1, 0, len(self.t) - 1)
        return self.x[idx]


class Context:
    """What blocks see: the logging grid, the streams so far, the device view (events), randomness."""

    def __init__(self, t_log, streams, internal, view, rng, truth=False):
        self.t, self.streams, self.internal, self.view, self.rng, self.truth = t_log, streams, internal, view, rng, truth

    @property
    def dt(self):
        return float(self.t[1] - self.t[0]) if len(self.t) > 1 else 1.0


class Block:
    kind = ""
    NEEDS = ()                  # required parameters (numbers with sources)
    OPTIONAL = {}               # optional parameters and defaults
    WORDS = ()                  # parameters that are names or plain values, no source needed
    rate = "log"

    def __init__(self, spec: dict, device_name: str = ""):
        self.spec = dict(spec)
        self.output = spec.get("output")
        self.position = spec.get("position", "normal")
        if not self.output:
            raise ParamError(f"device {device_name!r}: {self.kind} block needs an output column")
        known = set(self.NEEDS) | set(self.OPTIONAL) | set(self.WORDS) | {"block", "output", "position", "input"}
        unknown = set(spec) - known
        if unknown:
            raise ParamError(f"device {device_name!r}: {self.kind} block {self.output}: unknown key(s) {sorted(unknown)}")
        for k in self.NEEDS:
            if k not in spec:
                raise ParamError(f"device {device_name!r}: {self.kind} block {self.output} needs {k}")
        for k in list(self.NEEDS) + list(self.OPTIONAL):
            if k in spec and isinstance(spec[k], (int, float, list)) and not isinstance(spec[k], bool):
                raise ParamError(f"device {device_name!r}: {self.kind} {self.output}.{k} = {spec[k]!r} has no source; "
                                 "write {value, unit, source}")
            if k in spec and isinstance(spec[k], dict):
                check_source(f"{self.output}.{k}", spec[k])

    def p(self, k):
        return v(self.spec[k]) if k in self.spec else self.OPTIONAL[k]

    @property
    def input(self):
        return self.spec.get("input")

    def run(self, c: Context):
        raise NotImplementedError

    def describe(self):
        return {"block": self.kind, **self.spec}


def _quantize(x, model):
    if model is None:
        return x
    lo, hi = model.bounds
    return np.clip(model.quantize(x), lo, hi) + 0.0


class Constant(Block):
    kind = "constant"
    WORDS = ("value",)

    def run(self, c):
        return np.array([v(self.spec["value"])] * len(c.t), dtype=object)


class RandomState(Block):
    kind = "random_state"
    NEEDS = ("periods", "duration_s")
    WORDS = ("values", "default")

    def run(self, c):
        out = np.array([self.spec["default"]] * len(c.t), dtype=object)
        lo, hi = self.p("periods")
        other = [x for x in self.spec["values"] if x != self.spec["default"]]
        span = c.t[-1] if len(c.t) else 0
        for _ in range(int(c.rng.integers(lo, hi + 1))):
            d = c.rng.uniform(*self.p("duration_s"))
            s = c.rng.uniform(0, max(0.0, span - d))
            out[(c.t >= s) & (c.t < s + d)] = other[int(c.rng.integers(len(other)))]
        return out


class RollingMean(Block):
    kind = "rolling_mean"
    NEEDS = ("window_s",)
    OPTIONAL = {"quantize": True}

    def run(self, c):
        s = c.streams[self.input]
        x = np.asarray(s.x, float)
        w = max(1, int(round(self.p("window_s") / c.dt)))
        cs = np.concatenate([[0.0], np.cumsum(x)])
        idx = np.arange(1, len(x) + 1)
        y = (cs[idx] - cs[np.maximum(idx - w, 0)]) / w
        return _quantize(y, s.model) if self.p("quantize") else y


class CumulativeDose(Block):
    kind = "cumulative_dose"
    NEEDS = ("period_s",)
    OPTIONAL = {"quantize": True}

    def run(self, c):
        s = c.streams[self.input]
        y = np.cumsum(np.asarray(s.x, float)) * c.dt / self.p("period_s")
        return _quantize(y, s.model) if self.p("quantize") else y


class RateOfChange(Block):
    kind = "rate_of_change"
    NEEDS = ("window_s",)
    WORDS = ("per",)

    def run(self, c):
        x = np.asarray(c.streams[self.input].x, float)
        w = max(1, int(round(self.p("window_s") / c.dt)))
        per = {"s": 1.0, "min": 60.0, "h": 3600.0}[self.spec.get("per", "min")]
        y = np.zeros_like(x)
        y[w:] = (x[w:] - x[:-w]) / (w * c.dt) * per
        return y


class ThresholdAlarm(Block):
    kind = "threshold_alarm"
    OPTIONAL = {"hysteresis": 0.0, "latching": False}
    WORDS = ("level", "when", "on_value", "off_value", "latching")

    def __init__(self, spec, device_name=""):
        super().__init__(spec, device_name)
        if spec.get("when") not in ("above", "below"):
            raise ParamError(f"device {device_name!r}: threshold_alarm {self.output} needs when: above | below")
        lv = spec.get("level")
        if lv not in ("range_min", "range_max"):
            check_source(f"{self.output}.level", lv)

    def level(self, model):
        lv = self.spec["level"]
        if lv in ("range_min", "range_max"):
            if model is None:
                raise ParamError(f"{self.output}: level {lv} needs a sensor reading as input")
            lo, hi = model.bounds
            return float(np.min(lo) if lv == "range_min" else np.max(hi))
        return float(v(lv))

    def run(self, c):
        s = c.streams[self.input]
        return self.apply(np.asarray(s.x, float), self.level(s.model))

    def apply(self, x, level):
        above = self.spec["when"] == "above"
        h, latch = float(self.p("hysteresis")), bool(v(self.spec.get("latching", False)))
        on_v, off_v = self.spec.get("on_value", 1), self.spec.get("off_value", 0)
        trig = x >= level if above else x <= level
        if h == 0 and not latch:
            on = trig
        else:
            clear = x < level - h if above else x > level + h
            on = np.zeros(len(x), bool)
            state = False
            for i in range(len(x)):
                state = True if trig[i] else (state if (latch or not clear[i]) else False)
                on[i] = state
        if isinstance(on_v, (int, float)) and isinstance(off_v, (int, float)):
            return np.where(on, on_v, off_v)
        return np.where(on, on_v, off_v).astype(object)


class EventMode(Block):
    kind = "event_mode"
    WORDS = ("event", "value", "default", "until_back")

    def run(self, c):
        out = np.array([self.spec["default"]] * len(c.t), dtype=object)
        back = [q for q in self.spec.get("until_back", []) if q in c.streams]
        for lb in c.view.labels if c.view else []:
            if lb.event != self.spec["event"]:
                continue
            i0 = int(np.searchsorted(c.t, lb.start))
            i1 = int(np.searchsorted(c.t, lb.end))
            base = {q: c.streams[q].x[max(i0 - 1, 0)] for q in back}
            j = i1
            while j < len(c.t) and any(abs(c.streams[q].x[j] - base[q]) > (c.streams[q].model.resolution if
                                                                             c.streams[q].model else 0) for q in back):
                j += 1
            out[i0:j] = self.spec["value"]
        return out


class StateFlag(Block):
    kind = "state_flag"
    WORDS = ("state", "on_value", "off_value")

    def run(self, c):
        on = np.zeros(len(c.t), bool)
        for s, e in (c.view.states.get(self.spec["state"], []) if c.view else []):
            on |= (c.t >= s) & (c.t < e)
        a, b = self.spec.get("on_value", 1), self.spec.get("off_value", 0)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return np.where(on, a, b)
        return np.where(on, a, b).astype(object)


class Battery(Block):
    kind = "battery"
    NEEDS = ("runtime_h", "start_pct")

    def run(self, c):
        pct = self.p("start_pct") - 100.0 * c.t / (self.p("runtime_h") * 3600.0)
        for s, e, extra in (c.view.battery if c.view else []):
            pct = pct - extra * np.clip(np.minimum(c.t, e) - s, 0, None) / 3600.0
        return np.clip(np.floor(pct), 0, 100).astype(int)


class Signal(Block):
    kind = "signal"
    NEEDS = ("range_dbm", "start_dbm", "step_sd_db")

    def run(self, c):
        lo, hi = self.p("range_dbm")
        x = np.empty(len(c.t))
        x[0] = c.rng.uniform(*self.p("start_dbm"))
        steps = c.rng.normal(0, self.p("step_sd_db"), len(c.t))
        for i in range(1, len(c.t)):
            x[i] = min(hi, max(lo, x[i - 1] + steps[i]))
        return np.round(x).astype(int)


def _states_at(t_fast, state, t_log):
    idx = np.clip(np.searchsorted(t_fast, t_log + 1e-9, side="right") - 1, 0, len(t_fast) - 1)
    return state[idx]


class StillnessTimer(Block):
    kind = "stillness_timer"
    NEEDS = ("window_s", "threshold_g", "detect_s", "pre_alarm_s")
    rate = "internal"

    def moving(self, t, a):
        dt = float(t[1] - t[0]) if len(t) > 1 else 1.0
        w = max(2, int(round(self.p("window_s") / dt)))
        cs = np.concatenate([np.zeros((1, a.shape[1])), np.cumsum(a, axis=0)])
        cs2 = np.concatenate([np.zeros((1, a.shape[1])), np.cumsum(a * a, axis=0)])
        idx = np.arange(1, len(a) + 1)
        lo = np.maximum(idx - w, 0)
        n = (idx - lo)[:, None]
        mean = (cs[idx] - cs[lo]) / n
        var = np.maximum((cs2[idx] - cs2[lo]) / n - mean ** 2, 0)
        return np.sqrt(var).max(axis=1) > self.p("threshold_g")

    def states(self, t, a):
        mov = self.moving(t, a)
        dt = float(t[1] - t[0]) if len(t) > 1 else 1.0
        det, pre = self.p("detect_s"), self.p("pre_alarm_s")
        still = np.zeros(len(t))
        run = 0.0
        for i in range(len(t)):
            run = 0.0 if mov[i] else run + dt
            still[i] = run
        out = np.where(still >= det + pre, "alert", np.where(still >= det, "pre_alarm", "ok")).astype(object)
        return out

    def run(self, c):
        t, a = c.internal[self.input]
        return _states_at(t, self.states(t, a), c.t)


class SpikeThenStill(Block):
    kind = "spike_then_still"
    NEEDS = ("spike_g", "tilt_deg", "within_s", "pre_alarm_s", "reference_s")
    rate = "internal"

    def states(self, t, a):
        dt = float(t[1] - t[0]) if len(t) > 1 else 1.0
        w = max(1, int(round(1.0 / dt)))                               # gravity direction: 1-s mean
        cs = np.concatenate([np.zeros((1, 3)), np.cumsum(a, axis=0)])
        idx = np.arange(1, len(a) + 1)
        g = (cs[idx] - cs[np.maximum(idx - w, 0)]) / (idx - np.maximum(idx - w, 0))[:, None]
        n_ref = max(1, int(round(self.p("reference_s") / dt)))
        up = a[:n_ref].mean(axis=0)
        up = up / np.linalg.norm(up)
        gn = g / np.maximum(np.linalg.norm(g, axis=1, keepdims=True), 1e-9)
        tilt = np.degrees(np.arccos(np.clip(gn @ up, -1, 1)))
        spike = np.linalg.norm(a, axis=1) >= self.p("spike_g")
        lim, within, pre = self.p("tilt_deg"), self.p("within_s"), self.p("pre_alarm_s")
        out = np.array(["ok"] * len(t), dtype=object)
        i, n = 0, len(t)
        spikes = np.where(spike)[0]
        k = 0
        while k < len(spikes):
            s = spikes[k]
            end_w = min(n, s + int(round(within / dt)))
            tilted = np.where(tilt[s:end_w] >= lim)[0]
            if len(tilted) == 0:
                k += 1
                continue
            d = s + tilted[0]                                           # fall detected
            upright = np.where(tilt[d:] < lim / 2)[0]
            u = d + upright[0] if len(upright) else n
            p_end = min(u, d + int(round(pre / dt)))
            out[d:p_end] = "pre_alarm"
            if u > d + int(round(pre / dt)):
                out[p_end:u] = "alert"
            k = int(np.searchsorted(spikes, u))
        return out

    def run(self, c):
        t, a = c.internal[self.input]
        return _states_at(t, self.states(t, a), c.t)


class OrientationQuatBlock(Block):
    kind = "orientation_quat"
    WORDS = ("params", "prefix")
    rate = "internal"

    def run(self, c):
        from core.derived import OrientationQuat
        ch = OrientationQuat(self.spec.get("params"), prefix=self.spec.get("prefix", "orientation"))
        t, acc = c.internal["body.accel_g"]
        streams = {q: c.internal[q][1] for q in ch.inputs()}
        out = ch.compute(streams, float(t[1] - t[0]))
        return {col: _states_at(t, x, c.t) for col, x in out.items()}

    def outputs(self):
        from core.derived import OrientationQuat
        return OrientationQuat(self.spec.get("params"), prefix=self.spec.get("prefix", "orientation")).columns()


BLOCKS = {b.kind: b for b in (Constant, RandomState, RollingMean, CumulativeDose, RateOfChange, ThresholdAlarm,
                              EventMode, StateFlag, Battery, Signal, StillnessTimer, SpikeThenStill, OrientationQuatBlock)}
MOTION_BLOCKS = ("stillness_timer", "spike_then_still")


def build(spec: dict, device_name: str = "") -> Block:
    kind = spec.get("block")
    if kind not in BLOCKS:
        raise ParamError(f"device {device_name!r}: unknown logic block {kind!r}; known: {', '.join(BLOCKS)}")
    return BLOCKS[kind](spec, device_name)


def outputs(block) -> list:
    return block.outputs() if hasattr(block, "outputs") else [block.output]
