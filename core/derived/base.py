"""
base.py — a derived channel is computed by the device from other channels' readings; it does not
measure the world. Examples: a 15-min STEL from a gas reading, an orientation quaternion fused
from accelerometer, gyroscope and magnetometer.

Each kind declares its inputs (quantity ids), its parameters with defaults and sources (same
{value, unit, source} rule as part parameters) and the algorithm it uses. A device lists the derived
channels it reports; their inputs must be measured by its parts (they need not be logged).
"""
from abc import ABC, abstractmethod
from typing import ClassVar, Dict, List

from core.quantities.measurement import check_source


class DerivedChannel(ABC):
    kind: ClassVar[str] = ""
    name: ClassVar[str] = ""                  # plain English, for the UI
    algorithm: ClassVar[str] = ""             # what is computed and how, with its source
    PARAMS: ClassVar[Dict[str, dict]] = {}    # {name: {value, unit, source}} defaults

    def __init__(self, params: dict = None, **config):
        unknown = set(params or {}) - set(self.PARAMS)
        if unknown:
            raise ValueError(f"{self.kind}: unknown parameter(s) {sorted(unknown)}; known: {list(self.PARAMS)}")
        self.params = {k: dict(v) for k, v in self.PARAMS.items()}
        for k, v in (params or {}).items():
            check_source(f"{self.kind}.{k}", v)
            self.params[k] = dict(v)
        self.config = config

    def p(self, name):
        return self.params[name]["value"]

    @abstractmethod
    def inputs(self) -> List[str]:
        """Quantity ids whose readings this channel needs."""

    @abstractmethod
    def columns(self) -> List[str]:
        """CSV columns it writes."""

    @abstractmethod
    def compute(self, readings: dict, dt: float) -> dict:
        """readings: {quantity_id: array of readings at step dt (s)} -> {column: array}."""

    def describe(self) -> dict:
        return {"kind": self.kind, "name": self.name, "algorithm": self.algorithm, "inputs": self.inputs(),
                "columns": self.columns(), "params": self.params}
