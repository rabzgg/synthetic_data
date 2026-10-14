"""
registry.py — the sensor profiles the UI offers. Add a new profile here (see docs/ADDING_A_SENSOR.md).
"""
from .xdk import XDKProfile

PROFILES = {p.name: p for p in (XDKProfile(),)}


def get(name: str):
    return PROFILES[name]


def all_profiles() -> list:
    return list(PROFILES.values())
