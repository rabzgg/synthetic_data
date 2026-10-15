"""
physics.py — the relations between quantities that hold in the world, so that every sensor reading
the same world agrees with every other.

    humidity     RH from temperature and the water vapour pressure (Magnus formula): warmer air at
                 the same vapour content has a lower RH
    oxygen       foreign gas displaces air: O2 = O2_clean × (1 − foreign volume fraction)
    pressure     from sea-level pressure and altitude (standard atmosphere), about −0.12 hPa per m
                 near sea level
    body motion  orientation, angular rate and specific force come from one kinematic description
                 (see motion.py), so the gyroscope integrates to the orientation and the
                 accelerometer sees gravity in the orientation's frame
"""
import numpy as np

G = 9.80665                       # m/s², standard gravity
# Magnus formula over water, WMO constants (WMO-No. 8, 2008, Annex 4.B)
MAGNUS = (6.112, 17.62, 243.12)   # hPa, -, °C
# International standard atmosphere (ICAO), troposphere
ISA_K, ISA_EXP = 2.25577e-5, 5.25588


def saturation_vapour_pressure(t_c):
    """hPa over water at temperature t_c (°C)."""
    a, b, c = MAGNUS
    return a * np.exp(b * np.asarray(t_c, float) / (c + np.asarray(t_c, float)))


def relative_humidity(t_c, e_hpa):
    """%RH from temperature and vapour pressure; 100 at saturation."""
    return np.minimum(100.0 * np.asarray(e_hpa, float) / saturation_vapour_pressure(t_c), 100.0)


def vapour_pressure(t_c, rh_pct):
    return np.asarray(rh_pct, float) / 100.0 * saturation_vapour_pressure(t_c)


def pressure_at(sea_level_hpa, altitude_m):
    return np.asarray(sea_level_hpa, float) * (1 - ISA_K * np.asarray(altitude_m, float)) ** ISA_EXP


def foreign_fraction(gases: dict, clean: dict, lel_gas_vol_pct: float):
    """Volume fraction of gas that is not normal air: ppm gases above their clean-air level, plus
    the combustible gas (100 %LEL = lel_gas_vol_pct %vol)."""
    x = 0.0
    for q, v in gases.items():
        excess = np.maximum(np.asarray(v, float) - clean.get(q, 0.0), 0.0)
        x = x + (excess / 100.0 * lel_gas_vol_pct / 100.0 if q == "air.lel_pct" else excess * 1e-6)
    return x


def oxygen(o2_clean_pct, fraction):
    return o2_clean_pct * (1 - np.asarray(fraction, float))
