"""
catalog.py — the physical quantities a world can hold and a sensor can measure.

One entry per quantity: id, plain name, unit, CSV column stem and physical bounds. Nothing here is
about a particular sensor; a part (datasheet) says which quantities it measures and with which
parameters, and core/quantities/measurement.py turns the world value into a reading.

Physical bounds are hard limits of nature (RH cannot exceed 100 %, a concentration cannot be
negative). A sensor's own range is a datasheet parameter, not a property of the quantity.
"""
from dataclasses import dataclass
from typing import Optional, Tuple

AXES = ("x", "y", "z")


@dataclass(frozen=True)
class Quantity:
    id: str                       # "<domain>.<name>_<unit>"
    name: str                     # plain English, shown in the UI
    unit: str                     # canonical unit; every parameter is converted to it
    column: str                   # CSV column; "{axis}" is replaced by x / y / z for vector quantities
    lower: Optional[float]        # physical bounds, None = unbounded
    upper: Optional[float]
    axes: Tuple[str, ...] = ()    # () = scalar
    note: str = ""

    @property
    def vector(self) -> bool:
        return bool(self.axes)

    def columns(self) -> list:
        return [self.column.format(axis=a) for a in self.axes] if self.axes else [self.column]


_Q = [
    Quantity("air.temperature_c", "Air temperature", "°C", "temperature_c", -273.15, None),
    Quantity("air.humidity_rh", "Relative humidity", "%RH", "humidity_rh", 0.0, 100.0,
             note="Relative to saturation at the current air temperature."),
    Quantity("air.pressure_hpa", "Air pressure", "hPa", "pressure_hpa", 0.0, None),
    Quantity("air.o2_pct", "Oxygen", "%vol", "o2_pct_vol", 0.0, 100.0),
    Quantity("air.co_ppm", "Carbon monoxide", "ppm", "co_ppm", 0.0, 1e6),
    Quantity("air.h2s_ppm", "Hydrogen sulfide", "ppm", "h2s_ppm", 0.0, 1e6),
    Quantity("air.lel_pct", "Combustible gas", "%LEL", "lel_pct_lel", 0.0, None,
             note="Percent of the lower explosive limit; above 100 %LEL the air is explosive (no upper bound)."),
    Quantity("air.voc_ppm", "Volatile organic compounds", "ppm", "voc_ppm", 0.0, 1e6),
    Quantity("air.co2_ppm", "Carbon dioxide", "ppm", "co2_ppm", 0.0, 1e6),
    Quantity("light.lux", "Illuminance", "lx", "light_lux", 0.0, None),
    Quantity("body.accel_g", "Acceleration", "g", "accel_{axis}_g", None, None, AXES,
             note="Specific force in the sensor frame: a sensor at rest reads 1 g against gravity."),
    Quantity("body.gyro_dps", "Angular rate", "°/s", "gyro_{axis}_dps", None, None, AXES),
    Quantity("body.mag_ut", "Magnetic field", "µT", "mag_{axis}_ut", None, None, AXES),
]
CATALOG = {q.id: q for q in _Q}


def get(quantity_id: str) -> Quantity:
    try:
        return CATALOG[quantity_id]
    except KeyError:
        raise KeyError(f"unknown quantity {quantity_id!r}; known: {', '.join(CATALOG)}") from None
