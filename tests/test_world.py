"""
World: the relations between quantities hold (RH from temperature and vapour, O2 from gas,
pressure from altitude, body tracks from one motion), every preset carries sources and a realism
label, values stay within physical bounds, and the same seed gives the same world.
"""
import copy
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.devices import Part
from core.quantities import CATALOG
from core.quantities import rotation as rot
from core.world import MotionPlan, World, list_presets, load_preset
from core.world import physics as P
from core.world.world import check_preset

HOUR = 3600.0


class TestPresets(unittest.TestCase):
    def test_presets_load_with_sources(self):
        self.assertTrue({"indoor_worker_walking", "outdoor_day", "static_shelf", "fridge", "aquarium",
                         "pump_room"} <= set(list_presets()))
        for p in list_presets():
            d = load_preset(p)
            self.assertEqual(d["realism"], "ASSUMPTION")

    def test_number_without_source_refused(self):
        d = copy.deepcopy(load_preset("static_shelf"))
        d["drivers"]["air.temperature_c"]["random_walk"]["mean"] = 20
        with self.assertRaises(ValueError):
            check_preset(d, "x")

    def test_every_catalog_quantity_within_bounds(self):
        for p in list_presets():
            w = World(p, 2 * HOUR, 1)
            self.assertIn("body.accel_g", w.quantities(), p)
            for q in w.quantities():
                lo, hi = CATALOG[q].lower, CATALOG[q].upper
                x = w.tracks[q].values
                if lo is not None:
                    self.assertGreaterEqual(x.min(), lo, f"{p} {q}")
                if hi is not None:
                    self.assertLessEqual(x.max(), hi, f"{p} {q}")

    def test_same_seed_same_world(self):
        a, b, c = World("indoor_worker_walking", HOUR, 7), World("indoor_worker_walking", HOUR, 7), \
            World("indoor_worker_walking", HOUR, 8)
        for k in a.tracks:
            np.testing.assert_array_equal(a.tracks[k].values, b.tracks[k].values, k)
        self.assertFalse(np.array_equal(a.tracks["air.temperature_c"].values, c.tracks["air.temperature_c"].values))


class TestAirRelations(unittest.TestCase):
    def test_rh_follows_temperature(self):
        w = World("outdoor_day", 24 * HOUR, 3)
        T, e, rh = (w.tracks[k].values for k in ("air.temperature_c", "air.vapour_pressure_hpa", "air.humidity_rh"))
        np.testing.assert_allclose(rh, np.minimum(100 * e / P.saturation_vapour_pressure(T), 100))
        self.assertLess(np.corrcoef(T, rh)[0, 1], -0.8)          # warmer -> drier, same vapour content

    def test_saturation_caps_vapour(self):
        """Air that cools below its dew point holds no more vapour than saturation: RH stops at 100."""
        w = World("outdoor_day", 24 * HOUR, 1)
        T, e = w.tracks["air.temperature_c"].values, w.tracks["air.vapour_pressure_hpa"].values
        es = P.saturation_vapour_pressure(T)
        self.assertTrue((e <= es + 1e-12).all())
        capped = w.drivers["air.vapour_pressure_hpa"] > es
        self.assertTrue(capped.any())                           # it happens in this world (dawn)
        np.testing.assert_allclose(w.tracks["air.humidity_rh"].values[capped], 100.0)
        self.assertLess(capped.mean(), 0.5)

    def test_combustible_gas(self):
        for gas, vol in (("methane", 5.0), ("propane", 2.1), ("hydrogen", 4.0)):
            d = copy.deepcopy(load_preset("static_shelf"))
            d["clean_air"]["combustible_gas"]["value"] = gas
            w = World(d, 600, 1)
            w.drivers["air.lel_pct"][:] = 100
            w.drivers["air.co2_ppm"][:] = 420
            w.derive()
            np.testing.assert_allclose(w.tracks["air.o2_pct"].values, 20.9 * (1 - vol / 100))
        d["clean_air"]["combustible_gas"]["value"] = "acetylene"
        with self.assertRaises(ValueError):
            World(d, 600, 1)

    def test_magnus(self):
        self.assertAlmostEqual(float(P.saturation_vapour_pressure(20.0)), 23.37, places=1)
        self.assertAlmostEqual(float(P.relative_humidity(20.0, P.vapour_pressure(20.0, 55.0))), 55.0)

    def test_oxygen_drops_with_gas(self):
        w = World("static_shelf", HOUR, 1)
        clean = w.tracks["air.o2_pct"].values.copy()
        w.drivers["air.h2s_ppm"][:] = 10000           # 1 %vol
        w.drivers["air.lel_pct"][:] = 50              # 2.5 %vol methane
        w.derive()
        co2_excess = np.maximum(w.tracks["air.co2_ppm"].values - 420, 0) * 1e-6
        np.testing.assert_allclose(w.tracks["air.o2_pct"].values, 20.9 * (1 - 0.01 - 0.025 - co2_excess))
        self.assertTrue((w.tracks["air.o2_pct"].values < clean).all())

    def test_clean_air_oxygen(self):
        w = World("outdoor_day", HOUR, 1)
        w.drivers["air.co2_ppm"][:] = 420
        w.derive()
        np.testing.assert_allclose(w.tracks["air.o2_pct"].values, 20.9)

    def test_pressure_per_metre(self):
        slope = (P.pressure_at(1013.25, 10.0) - P.pressure_at(1013.25, 0.0)) / 10.0
        self.assertAlmostEqual(float(slope), -0.12, delta=0.005)
        w = World("static_shelf", HOUR, 1)
        w.drivers["floor_altitude_m"][:] = 100.0
        w.derive()
        np.testing.assert_allclose(w.tracks["air.pressure_hpa"].values,
                                   P.pressure_at(w.tracks["air.sea_level_pressure_hpa"].values, 101.0))

    def test_stairs_change_pressure(self):
        for seed in range(30):
            w = World("indoor_worker_walking", 8 * HOUR, seed)
            alt = w.tracks["floor_altitude_m"].values
            if alt.max() > 0:
                break
        else:
            self.fail("no floor change in 30 shifts")
        i = int(np.argmax(alt > 3.4))
        p, slp = w.tracks["air.pressure_hpa"].values, w.tracks["air.sea_level_pressure_hpa"].values
        dp = p[i + 30] - p[i - 60] - (P.pressure_at(slp[i + 30], 0) - P.pressure_at(slp[i - 60], 0))   # weather out
        self.assertAlmostEqual(dp, -0.12 * 3.5, delta=0.01)
        self.assertLess(abs(slp[i + 30] - slp[i - 60]), 0.05)      # and the weather itself moves slowly


class TestBody(unittest.TestCase):
    def setUp(self):
        self.w = World("indoor_worker_walking", HOUR, 5)
        self.q = self.w.tracks["body.orientation"].values
        self.g = self.w.tracks["body.gyro_dps"].values
        self.dt = self.w.body_dt

    def test_gyro_integrates_to_orientation(self):
        q = self.q[0].copy()
        out = [q]
        for k in range(30000):                                     # 20 min
            rv = np.radians(self.g[k]) * self.dt
            q = rot.normalize(rot.mul(rot.from_axis_angle(rv), q))
            out.append(q)
        err = np.degrees(rot.angle_between(np.array(out), self.q[:30001]))
        self.assertLess(err.max(), 0.01)

    def test_still_reads_gravity_only(self):
        still = self.w.motion_state.values == "still"
        away = still & (np.convolve(~still, np.ones(11), mode="same") == 0)      # 5 samples from any walk
        f = self.w.tracks["body.accel_g"].values[away]
        np.testing.assert_allclose(f, np.tile([0, 0, 1.0], (len(f), 1)), atol=1e-9)    # no translation
        rate = np.linalg.norm(self.g[away], axis=1)
        self.assertGreater(rate.mean(), 0.5)                    # a standing person sways a little
        self.assertLess(rate.mean(), 20)

    def test_walking_mean_is_gravity(self):
        walk = self.w.motion_state.values == "walk"
        f = self.w.tracks["body.accel_g"].values[walk]
        np.testing.assert_allclose(f.mean(axis=0), [0, 0, 1], atol=0.01)
        self.assertGreater(f[:, 2].std(), 0.1)                   # steps are visible

    def test_magnetic_field_constant_in_world(self):
        b = self.w.at("body.mag_ut", [0, 100, 2000])
        np.testing.assert_allclose(np.linalg.norm(b, axis=1), np.hypot(19.5, 44.5))

    def test_sensor_sees_gravity_in_its_frame(self):
        """An accelerometer on the body reads world gravity rotated into the body frame."""
        m = Part.load("bosch_bma280").models()["body.accel_g"]
        t = np.arange(0, 600, self.dt)
        q, f = self.w.at("body.orientation", t), self.w.at("body.accel_g", t)
        draw = m.draw(np.random.default_rng(0))
        draw.u_bias[:] = 0
        draw.axes = np.eye(3)
        m.noise_sd = 0.0
        r = m.measure(f, self.dt, np.random.default_rng(0), draw=draw, body_quat=q, keep_stages=True)
        np.testing.assert_allclose(r.stages["frame"], rot.rotate(rot.conj(q), f), atol=1e-12)
        self.assertAlmostEqual(np.linalg.norm(r.stages["frame"], axis=1).mean(),
                               np.linalg.norm(f, axis=1).mean(), places=9)


class TestFall(unittest.TestCase):
    """A fall in the motion plan (events will place it in phase 4) gives free fall, impact and lying."""

    def setUp(self):
        self.w = World("static_shelf", 120, 1)
        m = dict(self.w.preset["motion"], device_height_m={"value": 1.3, "unit": "m", "source": "ASSUMPTION: test"})
        self.w.preset["motion"] = m
        self.w.motion_params = m
        self.w.motion = MotionPlan(120)
        self.w.motion.insert(60, 61.5, "fall")
        self.w.motion.insert(61.5, 120, "still", posture="lying")
        self.w.derive()

    def test_free_fall_impact_lying(self):
        dt = self.w.body_dt
        f = self.w.tracks["body.accel_g"].values
        mag = np.linalg.norm(f, axis=1)
        t = np.arange(len(f)) * dt
        ff = (t > 60.05) & (t < 60.4)
        self.assertLess(mag[ff].max(), 0.1)                        # weightless while falling
        self.assertGreater(mag[(t > 60.4) & (t < 60.7)].max(), 3)  # impact
        q_end = self.w.tracks["body.orientation"].values[-1]
        np.testing.assert_allclose(rot.rotate(rot.conj(q_end), [0, 0, 1.0]), [-1, 0, 0], atol=1e-6)   # lying face down
        np.testing.assert_allclose(mag[t > 62], 1.0, atol=1e-6)
        self.assertEqual(self.w.state_at(100.0)[0], "lying")

    def test_fall_raises_pressure(self):
        p = self.w.tracks["air.pressure_hpa"].values
        slp = self.w.tracks["air.sea_level_pressure_hpa"].values
        dp = (p[100] - P.pressure_at(slp[100], 0)) - (p[30] - P.pressure_at(slp[30], 0))
        self.assertAlmostEqual(dp, 0.12 * (1.3 - self.w.tracks["body.height_m"].values[-1]), delta=0.01)


if __name__ == "__main__":
    unittest.main()
