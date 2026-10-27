"""
Primitives, operators and event effect ops: each does what core/world/primitives.py says; expressions
allow only numbers, $parameters and + - * / min max; named signals drive several quantities at once
(the fridge compressor); an event on a signal changes everything that refers to it.
"""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.events import EventDef
from core.world import World
from core.world.primitives import Context, SpecError, _solar_elevation_deg, evaluate, value


def ctx(n=3601, dt=1.0, hour=None, **kw):
    t = np.arange(n) * dt
    return Context(t, dt, (t / 3600.0) % 24 if hour is None else hour, np.full(n, 100), np.random.default_rng(0), **kw)


class TestPrimitives(unittest.TestCase):
    def test_shapes(self):
        c = ctx()
        np.testing.assert_allclose(evaluate({"constant": {"value": 3, "unit": "-", "source": "x"}}, c), 3)
        s = evaluate({"step": {"at_s": 100, "value": 2}}, c)
        self.assertEqual((s[99], s[100]), (0, 2))
        r = evaluate({"ramp": {"start_s": 100, "duration_s": 100, "from": 1, "to": 3}}, c)
        self.assertEqual((r[50], r[150], r[300]), (1, 2, 3))
        p = evaluate({"pulse": {"start_s": 100, "duration_s": 50, "level": 4, "ramp_s": 10}}, c)
        self.assertEqual((p[99], p[105], p[130], p[165], p[171]), (0, 2, 4, 2, 0))
        e = evaluate({"exp_rise_decay": {"start_s": 0, "level": 10, "rise_tau_s": 10, "hold_s": 100, "decay_tau_s": 100}}, c)
        self.assertAlmostEqual(e[100], 10 * (1 - np.exp(-10)))
        self.assertAlmostEqual(e[200], e[100] * np.exp(-1))
        per = evaluate({"periodic": {"amplitude": 2, "period_s": 400, "offset": 1}}, c)
        self.assertAlmostEqual(per[100], 3)
        d = evaluate({"daily_cycle": {"mean": 10, "amplitude": 5, "peak_hour": 0}}, ctx(hour=np.zeros(3601)))
        np.testing.assert_allclose(d, 15)

    def test_duty_cycle(self):
        c = ctx(n=36001)
        x = evaluate({"duty_cycle": {"period_s": 1800, "duty": 0.4, "on_value": 1, "off_value": 0}}, c)
        self.assertAlmostEqual(x.mean(), 0.4, delta=0.01)
        self.assertEqual(int((np.diff(x) > 0).sum()), 20)                # 20 cycles in 10 h
        j = evaluate({"duty_cycle": {"period_s": 1800, "duty": 0.4, "on_value": 1, "off_value": 0, "jitter": 0.2}}, c)
        starts = np.diff(np.where(np.diff(j) > 0)[0])
        self.assertGreater(starts.std(), 50)                            # periods vary
        self.assertTrue(((starts > 1800 * 0.79) & (starts < 1800 * 1.21)).all())

    def test_random_walk_and_schedule(self):
        c = ctx(n=86401)
        rw = evaluate({"random_walk": {"mean": 5, "sd": 1, "tau_s": 600, "smooth_s": 60}}, c)
        self.assertAlmostEqual(rw.mean(), 5, delta=0.3)
        self.assertLess(np.abs(np.diff(rw)).max(), 0.2)                  # smoothed
        sc = evaluate({"schedule": {"segments": [[6, 22, 1]], "default": 0}}, c)
        self.assertEqual((sc[5 * 3600], sc[6 * 3600], sc[21 * 3600], sc[22 * 3600]), (0, 1, 1, 0))
        night = evaluate({"schedule": {"segments": [[22, 6, 1]], "default": 0}}, c)
        self.assertEqual((night[23 * 3600], night[3 * 3600], night[12 * 3600]), (1, 1, 0))

    def test_operators(self):
        nodes = {"a": np.arange(5.0)}
        c = ctx(n=5, node=lambda name: nodes[name])
        np.testing.assert_allclose(evaluate({"sum": [{"ref": "a"}, 1]}, c), np.arange(5) + 1)
        np.testing.assert_allclose(evaluate({"product": [{"ref": "a"}, 2]}, c), np.arange(5) * 2)
        np.testing.assert_allclose(evaluate({"clip": {"of": {"ref": "a"}, "min": 1, "max": 3}}, c), [1, 1, 2, 3, 3])
        lp = evaluate({"lowpass": {"of": {"step": {"at_s": 1, "value": 10}}, "tau_s": 1e9}}, ctx(n=5))
        np.testing.assert_allclose(lp, 0, atol=1e-6)                     # starts at the first input value
        lp = evaluate({"lowpass": {"of": {"step": {"at_s": 1, "value": 10}}, "tau_s": 1, "start": 4}}, ctx(n=5))
        self.assertAlmostEqual(lp[0], 4 * np.exp(-1))                    # from the given start
        with self.assertRaises(SpecError):
            evaluate({"teleport": {}}, c)
        with self.assertRaises(SpecError):
            evaluate({"constant": 1, "ramp": {}}, c)

    def test_expressions_are_safe(self):
        self.assertEqual(value("$a + 2 * $b", {"a": 1, "b": 3}), 7)
        self.assertEqual(value("max($a, 5)", {"a": 1}), 5)
        self.assertEqual(value("01:30:00"), 5400)
        for bad in ("__import__('os')", "$a.real", "[1, 2]", "$x"):
            with self.subTest(bad), self.assertRaises(SpecError):
                value(bad if "$" in bad else "$a + " + bad, {"a": 1})


def event(d):
    return EventDef(dict({"kind": "t", "params": {"duration_s": {"value": 600, "unit": "s", "source": "ASSUMPTION: t"}}}, **d))


class TestIntegrate(unittest.TestCase):
    def test_stock_stays_within_bounds(self):
        c = ctx(n=7201)
        lv = evaluate({"integrate": {"start": 50, "inflow": [{"step": {"at_s": 3600, "value": 100}}], "outflow": [20],
                                     "per": "h", "lower": 0, "upper": 100}}, c)
        self.assertAlmostEqual(lv[1800], 50 - 10, places=6)               # -20 %/h for half an hour
        self.assertEqual(lv[3600:].max(), 100)                            # stops at the top, does not pass it
        empty = evaluate({"integrate": {"start": 5, "outflow": [50], "per": "h", "lower": 0, "upper": 100}}, c)
        self.assertEqual(empty.min(), 0)
        self.assertEqual(empty[-1], 0)

    def test_relax(self):
        lv = evaluate({"integrate": {"start": 40, "relax_to": 25, "relax_tau_s": 3600}}, ctx(n=3601))
        self.assertAlmostEqual(lv[3600] - 25, 15 * np.exp(-1), delta=0.01)

    def test_leak_is_an_outflow(self):
        w = World("water_tank", 48 * 3600, 42)
        base = w.tracks["water.level_pct"].values.copy()
        ev = event({"params": {"duration_s": {"value": 3 * 3600, "unit": "s", "source": "ASSUMPTION: t"}},
                    "effects": [{"target": "leak", "op": "add", "shape": 25, "after": "revert"}]})(12 * 3600.0)
        ev.apply_world(w)
        w.evaluate()
        lv = w.tracks["water.level_pct"].values
        np.testing.assert_allclose(lv[:12 * 3600 + 1], base[:12 * 3600 + 1])
        self.assertGreaterEqual(lv.min(), 0)
        self.assertLess(lv[15 * 3600], base[15 * 3600] - 30)              # drained by the leak
        self.assertGreater(lv[-1], 90)                                    # and filled again by the pump

    def test_energy_counts_up(self):
        e = World("pump_room", 24 * 3600, 42).tracks["electrical.energy_kwh"].values
        self.assertTrue((np.diff(e) >= 0).all())
        self.assertAlmostEqual(e[-1], 16 * 14 * 0.589, delta=10)         # 16 h at about 8.2 kW


class TestAfter(unittest.TestCase):
    def apply(self, op, after, shape=None, value=None):
        w = World("static_shelf", 4 * 3600, 3)
        T0 = w.tracks["air.temperature_c"].values.copy()
        eff = {"target": "air.temperature_c", "op": op, "after": after}
        eff.update({"shape": shape} if shape is not None else {"value": value})
        event({"effects": [eff]})(3600.0, {"duration_s": {"value": 3600, "unit": "s", "source": "ASSUMPTION: t"}}).apply_world(w)
        w.evaluate()
        return w.tracks["air.temperature_c"].values - T0

    def test_revert_and_hold(self):
        ramp = {"ramp": {"start_s": 0, "duration_s": 3600, "from": 0, "to": 4}}
        d = self.apply("add", "revert", ramp)
        self.assertEqual((d[3599], d[7199] > 3.9, d[7200], d[-1]), (0, True, 0, 0))
        d = self.apply("add", "hold", ramp)
        self.assertGreater(d[-1], 3.9)                                    # stays as reached
        d = self.apply("set", "hold", value=-10)
        self.assertTrue(np.allclose(d[7200:] + self.apply("set", "revert", value=0)[0], d[7200:]))
        T = World("static_shelf", 4 * 3600, 3).tracks["air.temperature_c"].values
        np.testing.assert_allclose((T + d)[7200:], -10)

    def test_bad_after(self):
        with self.assertRaises(ValueError):
            self.apply("add", "forever", 1)


class TestDefaults(unittest.TestCase):
    def test_minimal_world(self):
        w = World({"name": "one", "realism": "ASSUMPTION",
                   "drivers": {"water.ph": {"constant": {"value": 7.1, "unit": "pH", "source": "ASSUMPTION: t"}}}}, 3600, 1)
        np.testing.assert_allclose(w.tracks["water.ph"].values, 7.1)
        self.assertEqual(set(w.defaults_used), {"grid", "time", "earth_field_ut", "motion"})
        self.assertTrue(all("ASSUMPTION" in str(v) for v in w.defaults_used.values()))
        np.testing.assert_allclose(w.at("body.accel_g", [0.0]), [[0, 0, 1]])
        with self.assertRaises(ValueError):                               # realism is never defaulted
            World({"name": "x", "drivers": {}}, 60, 1)

    def test_short_presets(self):
        for name in ("fridge", "aquarium", "pump_room", "water_tank"):
            w = World(name, 3600, 1)
            self.assertIn("motion", w.defaults_used, name)


def _a(v, unit="-"):
    return {"value": v, "unit": unit, "source": "ASSUMPTION: test"}


class TestSky(unittest.TestCase):
    """Daylight under a clear, a partly cloudy and an overcast sky, as a fraction of the clear-sky curve."""
    BASE = {"latitude_deg": _a(52, "°"), "clear_sky": _a(110000, "lx"), "haze_sd": _a(0.02), "haze_tau_s": _a(120, "s")}
    PARTLY = {"shade_fraction": _a(0.3), "sun_mean_s": _a(300, "s"), "shade_mean_s": _a(180, "s"),
              "transition_s": _a(10, "s")}

    def ratio(self, sky, **extra):
        c = ctx(n=86400)
        lux = evaluate({"solar": dict(self.BASE, sky=_a(sky), **extra)}, c)
        curve = 110000 * np.clip(np.sin(np.radians(_solar_elevation_deg(c.hour, c.doy, 52))), 0, None)
        day = curve > 0.3 * 110000                              # one block around noon
        return lux[day] / curve[day]

    def test_partly_cloudy_has_two_levels(self):
        r = self.ratio("partly_cloudy", **self.PARTLY)
        share, edges = np.histogram(r, bins=25, range=(0, 1.25))
        share = share / share.sum()
        mid = (edges[:-1] + edges[1:]) / 2
        peaks = [mid[i] for i in range(25) if share[i] > 0.05 and share[i] >= share[max(i - 1, 0)]
                 and share[i] >= share[min(i + 1, 24)]]
        self.assertEqual(len(peaks), 2, peaks)
        self.assertAlmostEqual(peaks[0], 0.3, delta=0.06)              # cloud shadow
        self.assertAlmostEqual(peaks[1], 1.0, delta=0.06)              # sun
        self.assertLess(np.mean((r > 0.4) & (r < 0.85)), 0.05)        # little time in between: changes are quick
        self.assertLessEqual(r.max(), 1.0)                             # never above the clear curve

    def test_clear_stays_above_90_percent(self):
        r = self.ratio("clear")
        self.assertGreaterEqual(r.min(), 0.9)
        self.assertLessEqual(r.max(), 1.0)

    def test_overcast_is_low_and_smooth(self):
        r = self.ratio("overcast", overcast_fraction=_a(0.22), overcast_sd=_a(0.03), overcast_tau_s=_a(1800, "s"),
                       overcast_smooth_s=_a(600, "s"))
        self.assertTrue(0.15 <= np.median(r) <= 0.3, np.median(r))
        self.assertLessEqual(r.max(), 1.0)
        self.assertLess(np.abs(np.diff(r)).max(), 0.002)               # no jumps from one second to the next

    def test_cloud_edge_enhancement(self):
        r = self.ratio("partly_cloudy", edge_enhancement=_a(1.2), edge_s=_a(20, "s"), **self.PARTLY)
        self.assertGreater(r.max(), 1.05)
        self.assertLessEqual(r.max(), 1.2)

    def test_old_cloud_parameters_refused(self):
        with self.assertRaises(SpecError):
            evaluate({"solar": dict(self.BASE, cloud_mean=_a(0.7), cloud_sd=_a(0.2), cloud_tau_s=_a(600, "s"))}, ctx())
        with self.assertRaises(SpecError):
            self.ratio("stormy")

    def test_outdoor_presets_are_partly_cloudy(self):
        for name in ("outdoor_day", "field_day"):
            self.assertEqual(World(name, 3600, 1).preset["drivers"]["light.lux"]["solar"]["sky"]["value"], "partly_cloudy")


class TestEffects(unittest.TestCase):
    def test_signal_drives_several_quantities(self):
        w = World("fridge", 6 * 3600, 3)
        comp = w.signals["compressor"]
        cur = w.tracks["electrical.current_a"].values
        self.assertGreater(np.corrcoef(comp, cur)[0, 1], 0.95)
        dT = np.gradient(w.tracks["air.temperature_c"].values)
        self.assertLess(np.corrcoef(comp, dT)[0, 1], -0.5)              # cooling while it runs

    def test_set_on_a_signal(self):
        w = World("fridge", 6 * 3600, 3)
        T0 = w.tracks["air.temperature_c"].values.copy()
        ev = event({"effects": [{"target": "compressor", "op": "set", "value": 0}]})(3600.0,
                                                                                    {"duration_s": {"value": 7200, "unit": "s", "source": "ASSUMPTION: t"}})
        ev.apply_world(w)
        w.evaluate()
        T1, I1 = w.tracks["air.temperature_c"].values, w.tracks["electrical.current_a"].values
        self.assertGreater(T1[3600 + 7200] - T0[3600 + 7200], 5)           # warmed up without cooling
        self.assertLess(I1[3600:10800].max(), 0.2)                        # compressor current gone
        np.testing.assert_allclose(T1[:3600], T0[:3600])

    def test_multiply_add_approach(self):
        w = World("pump_room", 24 * 3600, 3)
        v0 = w.tracks["machine.vibration_mm_s"].values.copy()
        ev = event({"effects": [{"target": "machine.vibration_mm_s", "op": "multiply",
                                 "shape": {"ramp": {"start_s": 0, "duration_s": "$duration_s", "from": 1, "to": 2}}}]})
        ev(0.0, {"duration_s": {"value": 86400, "unit": "s", "source": "ASSUMPTION: t"}}).apply_world(w)
        w.evaluate()
        v1 = w.tracks["machine.vibration_mm_s"].values
        self.assertAlmostEqual(v1[43200] / v0[43200], 1.5, places=6)
        night = 17 * 3600 + 1800                                           # 23:30, the world starts 06:00
        self.assertLess(v1[night], 0.2)                                    # still quiet when the pump is off
        w = World("static_shelf", 4 * 3600, 3)
        T0 = w.tracks["air.temperature_c"].values.copy()
        ev = event({"params": {"duration_s": {"value": 1200, "unit": "s", "source": "ASSUMPTION: t"}},
                    "effects": [{"target": "air.temperature_c", "op": "approach", "value": 0, "tau_s": 100,
                                 "recovery_tau_s": 600}]})
        ev(3600.0).apply_world(w)
        w.evaluate()
        T1 = w.tracks["air.temperature_c"].values
        self.assertAlmostEqual(T1[3600 + 1199], 0, delta=0.01)
        rec = (T1[4800 + 600] - T0[4800 + 600]) / (T1[4799] - T0[4799])
        self.assertAlmostEqual(rec, np.exp(-1), delta=0.01)

    def test_unknown_target_refused(self):
        w = World("aquarium", 3600, 1)
        ev = event({"effects": [{"target": "air.h2s_ppm", "op": "add", "shape": 5}]})(0.0)
        with self.assertRaises(ValueError):
            ev.apply_world(w)
        ok = event({"effects": [{"target": "air.h2s_ppm", "op": "add", "shape": 5, "optional": True},
                                {"target": "water.ph", "op": "add", "shape": 1}]})(0.0)
        ok.apply_world(w)
        w.evaluate()
        ph = w.tracks["water.ph"].values
        self.assertGreater(ph[:600].min(), 7.5)                          # during the event
        self.assertLess(ph[700:].max(), 7.4)                             # reverted after it


if __name__ == "__main__":
    unittest.main()
