"""
derived — channels a device computes from other channels' readings (not measured from the world).
"""
from .base import DerivedChannel
from .exposure import Stel, Twa
from .fusion import OrientationQuat, madgwick

DERIVED = {c.kind: c for c in (Stel, Twa, OrientationQuat)}


def build(kind: str, **config) -> DerivedChannel:
    if kind not in DERIVED:
        raise KeyError(f"unknown derived channel {kind!r}; known: {', '.join(DERIVED)}")
    return DERIVED[kind](**config)
