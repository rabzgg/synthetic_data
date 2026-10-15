"""
events — block [E]: events that change the world or a device, and scenarios that place them.
"""
from .base import DeviceView, Event, Label, ScenarioError, parse_time
from .scenario import EVENTS, Prepared, compatibility, expected_alerts, list_scenarios, load_scenario, prepare
