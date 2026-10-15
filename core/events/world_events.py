"""
world_events.py — events that change the world. They edit drivers or the motion plan; the world
derives RH, O2, pressure and the body tracks again afterwards (World.derive()).
"""
import numpy as np

from core.world import physics as P

from .base import GAS_Q, GAS_UNIT, Event, ScenarioError, trapezoid


def A(value, unit, why):
    return {"value": value, "unit": unit, "source": f"ASSUMPTION: {why}"}


class GasRelease(Event):
    kind = "gas_release"
    name = "Gas release"
    description = "A gas leaks into the air around the devices, holds at a level for a while, then clears."
    PARAMS = {"gas": A("h2s", "-", "default gas"),
              "level": A(20, "gas unit", "a level that crosses typical alarm setpoints"),
              "duration_s": A(600, "s", "time at the level"),
              "ramp_s": A(30, "s", "the gas builds up and clears over half a minute")}

    def affects(self):
        return [GAS_Q[self.p("gas")], "air.o2_pct"]

    @property
    def end(self):
        return self.at + 2 * self.p("ramp_s") + self.p("duration_s")

    def visible_to(self, device, mount, level=None):
        """Seen by a device that measures the gas, or through O2 when the gas displaces enough air for
        the device's O2 sensor to resolve the drop."""
        g = self.p("gas")
        meas = device.measured()
        if GAS_Q[g] in meas:
            return True, ""
        if "air.o2_pct" in meas:
            drop = o2_drop(g, self.p("level") if level is None else level)
            res = min(m.resolution for _, q, m in device.models() if q == "air.o2_pct")
            if drop >= res:
                return True, ""
            return False, (f"it does not measure {g.upper()}, and the O2 drop it causes ({drop:.3g} %vol) is below the "
                           f"O2 resolution ({res:g} %vol)")
        return False, f"the device measures neither {g.upper()} nor O2"

    def check(self):
        if self.p("gas") not in GAS_Q or self.p("gas") == "o2":
            raise ScenarioError(f"gas_release: gas must be one of {[g for g in GAS_Q if g != 'o2']}")

    def apply_world(self, world):
        self.check()
        t = world.tracks["air.temperature_c"].times()
        q = GAS_Q[self.p("gas")]
        world.drivers[q] = world.drivers[q] + trapezoid(t, self.at, self.p("ramp_s"), self.p("duration_s"), self.p("level"))
        g = self.p("gas")
        return [self.label(f"{g.upper()} {self.p('level'):.3g} {GAS_UNIT[g]}")]


def o2_drop(gas, level, lel_vol_pct=5.0, o2_clean=20.9):
    """%vol of O2 lost when `level` of `gas` displaces air (methane assumed for LEL here; the world uses
    its own combustible gas when it derives O2)."""
    frac = level / 100.0 * lel_vol_pct / 100.0 if gas == "lel" else level * 1e-6
    return o2_clean * frac


def _lying_at(world, t) -> bool:
    return world.motion.at(t).get("posture") == "lying"


class Fall(Event):
    kind = "fall"
    name = "Fall"
    description = "The wearer falls to the ground, lies there for a while and gets up again."
    body = True
    PARAMS = {"fall_s": A(1.5, "s", "from losing balance to lying at rest"),
              "lying_s": A(30, "s", "time on the ground before getting up"),
              "rise_s": A(3, "s", "getting up")}

    def affects(self):
        return ["body.accel_g", "body.gyro_dps", "air.pressure_hpa"]

    @property
    def end(self):
        return self.at + self.p("fall_s") + self.p("lying_s") + self.p("rise_s")

    def apply_world(self, world):
        if _lying_at(world, self.at):
            raise ScenarioError(f"fall at {self.at:.0f} s: the wearer is already lying down")
        a, b, c = self.at + self.p("fall_s"), self.at + self.p("fall_s") + self.p("lying_s"), self.end
        world.motion.insert(self.at, a, "fall")
        world.motion.insert(a, b, "still", posture="lying")
        world.motion.insert(b, c, "rise")
        return [self.label("whole fall"), self.label(start=self.at, end=a, event="fall:falling"),
                self.label(start=a, end=b, event="fall:lying"), self.label(start=b, end=c, event="fall:rise")]


class NoMotion(Event):
    kind = "no_motion"
    name = "No motion"
    description = "The wearer stops moving completely (standing or lying), as when unconscious."
    body = True
    PARAMS = {"duration_s": A(300, "s", "five minutes without any movement")}

    def affects(self):
        return ["body.accel_g", "body.gyro_dps"]

    def apply_world(self, world):
        posture = "lying" if _lying_at(world, self.at) else "upright"
        world.motion.insert(self.at, self.end, "motionless", posture=posture)
        return [self.label(posture)]


class Collapse(Event):
    kind = "collapse"
    name = "Collapse"
    description = ("A gas release makes the wearer collapse: the gas rises, the wearer falls, moves a little, "
                   "then lies without moving until rescued.")
    body = True
    PARAMS = {**{k: v for k, v in GasRelease.PARAMS.items()},
              "fall_after_s": A(60, "s", "time in the gas before collapsing"),
              "fall_s": A(1.5, "s", "from losing balance to lying at rest"),
              "no_motion_after_s": A(20, "s", "the wearer still moves a little after the fall"),
              "no_motion_s": A(600, "s", "lies without moving until rescued"),
              "rise_s": A(5, "s", "lifted up by the rescuers")}

    def affects(self):
        return [GAS_Q[self.p("gas")], "air.o2_pct", "body.accel_g", "body.gyro_dps", "air.pressure_hpa"]

    def visible_to(self, device, mount):
        """The gas part reaches every device; the fall and no motion only the worn ones."""
        gas_seen, why = GasRelease.visible_to(self, device, mount)
        if gas_seen:
            return True, ""
        if mount.kind != "body":
            return False, "it reaches fixed devices only through the gas, and " + why
        body = {"body.accel_g", "body.gyro_dps", "air.pressure_hpa"} & set(device.measured())
        return (True, "") if body else (False, why + "; and it measures no motion or pressure")

    def steps(self):
        t_fall = self.at + self.p("fall_after_s")
        t_stir = t_fall + self.p("fall_s")
        t_still = t_stir + self.p("no_motion_after_s")
        t_rise = t_still + self.p("no_motion_s")
        return t_fall, t_stir, t_still, t_rise, t_rise + self.p("rise_s")

    @property
    def end(self):
        gas_end = self.at + 2 * self.p("ramp_s") + self.p("duration_s")
        return max(gas_end, self.steps()[-1])

    def apply_world(self, world):
        GasRelease.check(self)
        t = world.tracks["air.temperature_c"].times()
        q = GAS_Q[self.p("gas")]
        world.drivers[q] = world.drivers[q] + trapezoid(t, self.at, self.p("ramp_s"), self.p("duration_s"), self.p("level"))
        t_fall, t_stir, t_still, t_rise, t_up = self.steps()
        if _lying_at(world, t_fall):
            raise ScenarioError(f"collapse: the wearer is already lying at {t_fall:.0f} s")
        world.motion.insert(t_fall, t_stir, "fall")
        if t_still > t_stir:
            world.motion.insert(t_stir, t_still, "stir", posture="lying")
        world.motion.insert(t_still, t_rise, "motionless", posture="lying")
        world.motion.insert(t_rise, t_up, "rise")
        g = self.p("gas")
        gas_end = self.at + 2 * self.p("ramp_s") + self.p("duration_s")
        return [self.label(f"{g.upper()} {self.p('level'):.3g} {GAS_UNIT[g]}"),
                self.label(start=self.at, end=gas_end, event="collapse:gas_release",
                           detail=f"{g.upper()} {self.p('level'):.3g} {GAS_UNIT[g]}"),
                self.label(start=t_fall, end=t_stir, event="collapse:fall"),
                self.label(start=t_stir, end=t_still, event="collapse:stir"),
                self.label(start=t_still, end=t_rise, event="collapse:no_motion", detail="lying"),
                self.label(start=t_rise, end=t_up, event="collapse:rescue")]


class TemperatureChange(Event):
    kind = "temperature_change"
    name = "Temperature change"
    description = "The air warms or cools by a set amount and stays there for a while; RH follows."
    PARAMS = {"delta_c": A(5, "°C", "a noticeable change"),
              "ramp_s": A(600, "s", "air changes temperature over ten minutes"),
              "duration_s": A(3600, "s", "one hour at the new temperature")}

    def affects(self):
        return ["air.temperature_c", "air.humidity_rh"]

    @property
    def end(self):
        return self.at + 2 * self.p("ramp_s") + self.p("duration_s")

    def apply_world(self, world):
        t = world.tracks["air.temperature_c"].times()
        world.drivers["air.temperature_c"] = world.drivers["air.temperature_c"] + trapezoid(
            t, self.at, self.p("ramp_s"), self.p("duration_s"), self.p("delta_c"))
        return [self.label(f"{self.p('delta_c'):+g} °C")]


class DoorOpen(Event):
    kind = "door_open"
    name = "Door open"
    description = "A door to the outside stays open: indoor air mixes towards the outdoor temperature, humidity and CO2, and daylight comes in."
    PARAMS = {"duration_s": A(120, "s", "door held open for two minutes"),
              "outside_temperature_c": A(5, "°C", "a winter day"),
              "outside_rh_pct": A(80, "%RH", "a winter day"),
              "outside_co2_ppm": A(420, "ppm", "outdoor background"),
              "light_add_lux": A(1500, "lx", "daylight through the open door"),
              "exchange_tau_s": A(120, "s", "time constant of air exchange near the door"),
              "recovery_tau_s": A(900, "s", "time constant of the room getting back after the door closes")}

    def affects(self):
        return ["air.temperature_c", "air.humidity_rh", "light.lux", "air.co2_ppm"]

    def _mix(self, t, base, target):
        s, e, tau, tau_r = self.at, self.end, self.p("exchange_tau_s"), self.p("recovery_tau_s")
        during = (t >= s) & (t < e)
        delta = np.zeros_like(base)
        delta[during] = (target - base[during]) * (1 - np.exp(-(t[during] - s) / tau))
        i_end = min(np.searchsorted(t, e), len(t) - 1)
        d_end = (target - base[i_end]) * (1 - np.exp(-(e - s) / tau))
        after = t >= e
        delta[after] = d_end * np.exp(-(t[after] - e) / tau_r)
        return base + delta

    def apply_world(self, world):
        t, d = world.tracks["air.temperature_c"].times(), world.drivers
        d["air.temperature_c"] = self._mix(t, d["air.temperature_c"], self.p("outside_temperature_c"))
        e_out = float(P.vapour_pressure(self.p("outside_temperature_c"), self.p("outside_rh_pct")))
        d["air.vapour_pressure_hpa"] = self._mix(t, d["air.vapour_pressure_hpa"], e_out)
        d["air.co2_ppm"] = self._mix(t, d["air.co2_ppm"], self.p("outside_co2_ppm"))
        d["light.lux"] = d["light.lux"] + np.where((t >= self.at) & (t < self.end), self.p("light_add_lux"), 0.0)
        return [self.label(f"outside {self.p('outside_temperature_c'):g} °C")]


WORLD_EVENTS = [GasRelease, Fall, NoMotion, Collapse, TemperatureChange, DoorOpen]
