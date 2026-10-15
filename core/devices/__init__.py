"""
devices — blocks [B] parts (one sensor from its datasheet) and [C] devices (parts assembled and
named by the user). Both are data files under configs/; see parts.py and device.py.
"""
from .device import DEVICES_DIR, Device, PartUse, list_devices, save_device, slugify
from .parts import PARTS_DIR, Part, apply_overrides, list_parts
