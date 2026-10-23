"""
quantities — block [A] of the sensor-agnostic generator: what can exist in the world and the one
generic way a sensor measures it. See docs/PARAMETER_MAPPING.md.
"""
from .catalog import ALIASES, AXES, CATALOG, Quantity, get, resolve
from .measurement import PARAMETERS, MeasurementModel, ParamError, Reading, UnitDraw
from .normalize import RULES, normalize
from .units import UnitError, convert
