"""
registry.py — the sensor profiles the UI offers. Add a new profile here (see docs/ADDING_A_SENSOR.md).
"""
from .gas import GasDetectorProfile, gas_devices
from .xdk import XDKProfile

PROFILES = {p.name: p for p in [XDKProfile()] + [GasDetectorProfile(d) for d in gas_devices()]}


def get(name: str):
    return PROFILES[name]


def all_profiles() -> list:
    return list(PROFILES.values())
