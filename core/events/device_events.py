"""
device_events.py — events that change one device, not the world: what its sensors are given (bump
test gas, a sensor fault), its states (pump, SOS, battery) or its connection.
"""
from core.quantities import CATALOG

from .base import GAS_Q, Event, ScenarioError
from .world_events import A


class BumpTest(Event):
    kind = "bump_test"
    name = "Bump test"
    description = "Test gas is applied to the detector's inlet for a minute to check that every sensor reacts and alarms."
    scope = "device"
    PARAMS = {"mix": {"value": {"lel": 50, "h2s": 25, "co": 100, "o2": 18}, "unit": "%LEL / ppm / ppm / %vol",
                      "source": "ASSUMPTION: example mix from the task brief (configs/gas/assumptions.json bump_test.gas_mix)"},
              "applied_s": {"value": 60, "unit": "s",
                            "source": "ASSUMPTION: test gas applied for 60 s (configs/gas/assumptions.json bump_test)"}}

    def requires(self):
        return ["bump_test"]

    def affects(self):
        return [GAS_Q[g] for g in self.p("mix")]

    def duration_s(self):
        return float(self.p("applied_s"))

    def apply_device(self, view):
        measured = set(view.device.measured())
        given = []
        for g, level in self.p("mix").items():
            if GAS_Q[g] in measured:
                view.overrides.append((GAS_Q[g], self.at, self.end, "value", float(level)))
                given.append(f"{g.upper()} {level:g}")
        return [self.label(", ".join(given))]


class ConnectionLoss(Event):
    kind = "connection_loss"
    name = "Connection loss"
    description = "The device loses its connection: it keeps measuring, but no rows reach the log until it is back."
    scope = "device"
    PARAMS = {"duration_s": A(120, "s", "two minutes without a connection")}

    def requires(self):
        return ["connectivity"]

    def apply_device(self, view):
        view.gaps.append((self.at, self.end))
        return [self.label(f"{self.duration_s():.0f} s without rows")]


class _State(Event):
    scope = "device"
    state = ""

    def requires(self):
        return [f"states.{self.state}"]

    def apply_device(self, view):
        view.states.setdefault(self.state, []).append((self.at, self.end))
        return [self.label()]


class PumpFault(_State):
    kind = "pump_fault"
    name = "Pump fault"
    description = "The sampling pump stops: the pump alarm is on; the gas readings are not changed."
    state = "pump"
    PARAMS = {"duration_s": A(300, "s", "five minutes (configs/gas/assumptions.json pump_fault: 120-600 s)")}


class Sos(_State):
    kind = "sos"
    name = "SOS"
    description = "The wearer presses the SOS button; the SOS state is on for a while."
    state = "sos"
    PARAMS = {"duration_s": A(120, "s", "two minutes (configs/gas/assumptions.json sos: 60-300 s)")}


class BatteryDrain(Event):
    kind = "battery_drain"
    name = "Battery drain"
    description = "The battery drains faster than normal for a while, e.g. from a weak signal or a faulty cell."
    scope = "device"
    PARAMS = {"duration_s": A(3600, "s", "one hour"),
              "extra_pct_per_h": A(10, "%/h", "on top of the normal drain")}

    def requires(self):
        return ["battery"]

    def apply_device(self, view):
        view.battery.append((self.at, self.end, float(self.p("extra_pct_per_h"))))
        return [self.label(f"+{self.p('extra_pct_per_h'):.3g} %/h")]


class SensorFault(Event):
    kind = "sensor_fault"
    name = "Sensor fault"
    description = "One sensor of the device fails for a while: it sticks at its last value, reads zero, or reads off by a fixed amount."
    scope = "device"
    PARAMS = {"quantity": A("air.h2s_ppm", "-", "default quantity"),
              "mode": A("stuck", "-", "stuck | zero | offset"),
              "offset": A(0, "quantity unit", "used with mode offset"),
              "duration_s": A(600, "s", "ten minutes")}

    def affects(self):
        return [self.p("quantity")]

    def apply_device(self, view):
        q, mode = self.p("quantity"), self.p("mode")
        if q not in CATALOG:
            raise ScenarioError(f"sensor_fault: unknown quantity {q!r}")
        if mode not in ("stuck", "zero", "offset"):
            raise ScenarioError("sensor_fault: mode must be stuck, zero or offset")
        view.overrides.append((q, self.at, self.end, mode, float(self.p("offset"))))
        return [self.label(f"{q} {mode}" + (f" {self.p('offset'):+g}" if mode == "offset" else ""))]


DEVICE_EVENTS = [BumpTest, ConnectionLoss, PumpFault, Sos, BatteryDrain, SensorFault]
