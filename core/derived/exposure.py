"""
exposure.py — STEL and TWA of a gas reading, as a gas detector computes them.

STEL: average of the readings in the last window (15 min); samples before the start count as 0
and the sum is always divided by the full window. TWA: sum of reading × step since the start,
divided by the averaging period (8 h). Both are rounded to the reading's resolution and clipped to
its range when the part's (resolution, low, high) is given. Same rule as the gas detector engine.
"""
import numpy as np

from core.quantities import get

from .base import DerivedChannel

REG = "ASSUMPTION: occupational exposure convention (15-min STEL); limits and window vary by regulation"


def _column(qid, what):
    q = get(qid)
    stem, unit = q.column.split("_", 1)
    return f"{stem}_{what}_{unit}"


def _round(x, quantize):
    if not quantize:
        return x
    res, lo, hi = quantize
    return np.clip(np.round(np.round(x / res) * res, 10), lo, hi) + 0.0


class Stel(DerivedChannel):
    kind = "stel"
    name = "Short-term exposure (15-min average)"
    algorithm = "Rolling mean over window_s; samples before the start count as 0 (always divided by the full window)."
    PARAMS = {"window_s": {"value": 900, "unit": "s", "source": REG}}

    def __init__(self, quantity: str, params: dict = None, quantize: tuple = None):
        super().__init__(params, quantity=quantity)
        if get(quantity).vector:
            raise ValueError("stel needs a scalar quantity")
        self.quantity, self.quantize = quantity, quantize

    def inputs(self):
        return [self.quantity]

    def columns(self):
        return [_column(self.quantity, "stel")]

    def compute(self, readings, dt):
        v = np.asarray(readings[self.quantity], float)
        w = int(round(self.p("window_s") / dt))
        csum = np.concatenate([[0.0], np.cumsum(v)])
        idx = np.arange(1, len(v) + 1)
        return {self.columns()[0]: _round((csum[idx] - csum[np.maximum(idx - w, 0)]) / w, self.quantize)}


class Twa(DerivedChannel):
    kind = "twa"
    name = "Time-weighted average (8-h shift)"
    algorithm = "Sum of reading × step since the start, divided by period_s."
    PARAMS = {"period_s": {"value": 28800, "unit": "s",
                           "source": "ASSUMPTION: occupational exposure convention (8-h TWA)"}}

    def __init__(self, quantity: str, params: dict = None, quantize: tuple = None):
        super().__init__(params, quantity=quantity)
        if get(quantity).vector:
            raise ValueError("twa needs a scalar quantity")
        self.quantity, self.quantize = quantity, quantize

    def inputs(self):
        return [self.quantity]

    def columns(self):
        return [_column(self.quantity, "twa")]

    def compute(self, readings, dt):
        v = np.asarray(readings[self.quantity], float)
        return {self.columns()[0]: _round(np.cumsum(v) * dt / self.p("period_s"), self.quantize)}
