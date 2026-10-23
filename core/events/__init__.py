"""
events — block [E]: events that change the world or a device (configs/events/*.yaml, applied by
library.py), and scenarios that place them (scenario.py).
"""
from .base import DeviceView, Label, ScenarioError, parse_time
from .library import EVENTS, EventDef, Instance, load_events
from .scenario import (Prepared, compatibility, compatible_events, event_rows, expected_alerts, list_scenarios,
                       load_scenario, prepare)
