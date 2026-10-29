"""
Quantity catalog and the generic measurement model: a constant world gives readings that obey the
resolution, the range, the accuracy bound and the noise level, for every quantity in the catalog;
every stage does what it says and runs in the fixed order; datasheet wording normalises as documented.
"""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.quantities import CATALOG, MeasurementModel, ParamError, normalize
from core.quantities import rotation as rot
from core.quantities.normalize import DOC, RULES, markdown

T = "ASSUMPTION: test value"


def P(value, unit):
    return {"value": value, "unit": unit, "source": T}


# per quantity: typical datasheet-like numbers (test values only) and a constant world value
FIXTURES = {
    "air.temperature_c": ({"range": P([-40, 85], "°C"), "resolution": P(0.01, "°C"), "accuracy": P(0.5, "°C"),
                           "noise_sd": P(0.02, "°C")}, 22.0),
    "air.humidity_rh": ({"range": P([0, 100], "%RH"), "resolution": P(0.01, "%RH"), "accuracy": P(3, "%RH"),
                         "noise_sd": P(0.1, "%RH")}, 45.0),
    "air.pressure_hpa": ({"range": P([300, 1100], "hPa"), "resolution": P(0.01, "hPa"), "accuracy": P(1.0, "hPa"),
                          "noise_sd": P(0.03, "hPa")}, 1013.25),
    "air.o2_pct": ({"range": P([0, 25], "%vol"), "resolution": P(0.1, "%vol"), "accuracy": P(0.2, "%vol"),
                    "noise_sd": P(0.15, "%vol")}, 20.9),
    "air.co_ppm": ({"range": P([0, 500], "ppm"), "resolution": P(1, "ppm"), "accuracy": P(2, "ppm"),
                    "accuracy_pct_reading": P(5, "%"), "noise_sd": P(1.5, "ppm")}, 50.0),
    "air.h2s_ppm": ({"range": P([0, 100], "ppm"), "resolution": P(0.1, "ppm"), "accuracy": P(0.5, "ppm"),
                     "noise_sd": P(0.2, "ppm")}, 5.0),
    "air.lel_pct": ({"range": P([0, 100], "%LEL"), "resolution": P(1, "%LEL"), "accuracy": P(3, "%LEL"),
                     "noise_sd": P(1.5, "%LEL")}, 10.0),
    "air.voc_ppm": ({"range": P([0, 2000], "ppm"), "resolution": P(0.1, "ppm"), "accuracy": P(1, "ppm"),
                     "noise_sd": P(0.3, "ppm")}, 20.0),
    "air.co2_ppm": ({"range": P([0, 5000], "ppm"), "resolution": P(1, "ppm"), "accuracy": P(30, "ppm"),
                     "accuracy_pct_reading": P(3, "%"), "noise_sd": P(5, "ppm")}, 800.0),
    "light.lux": ({"range": P([0, 65535], "lx"), "resolution": P(1, "lx"), "accuracy_pct_reading": P(15, "%"),
                   "noise_sd": P(2, "lx")}, 300.0),
    "body.accel_g": ({"range": P([-16, 16], "g"), "resolution": P(1 / 1024, "g"), "accuracy": P(40, "mg"),
                      "noise_sd": P(3, "mg")}, [0.0, 0.0, 1.0]),
    "body.gyro_dps": ({"range": P([-2000, 2000], "dps"), "resolution": P(0.061, "dps"), "accuracy": P(1, "dps"),
                       "noise_sd": P(0.1, "dps")}, [0.0, 0.0, 0.0]),
    "body.mag_ut": ({"range": P([-1300, 1300], "µT"), "resolution": P(0.3, "µT"), "accuracy": P(2, "µT"),
                     "noise_sd": P(0.5, "µT")}, [20.0, -5.0, 40.0]),
    "water.temperature_c": ({"range": P([0, 50], "°C"), "resolution": P(0.0625, "°C"), "accuracy": P(0.5, "°C"),
                             "noise_sd": P(0.1, "°C")}, 25.0),
    "water.ph": ({"range": P([0, 14], "pH"), "resolution": P(0.01, "pH"), "accuracy": P(0.1, "pH"),
                  "noise_sd": P(0.02, "pH")}, 7.2),
    "electrical.current_a": ({"range": P([0, 20], "A"), "resolution": P(10, "mA"), "accuracy_pct_reading": P(2, "%"),
                              "noise_sd": P(0.02, "A")}, 5.0),
    "machine.vibration_mm_s": ({"range": P([0, 25], "mm/s"), "resolution": P(0.01, "mm/s"), "accuracy": P(0.1, "mm/s"),
                                "noise_sd": P(0.05, "mm/s")}, 2.5),
    "water.level_pct": ({"range": P([0, 100], "%"), "resolution": P(0.1, "%"), "accuracy": P(0.5, "%"),
                         "noise_sd": P(0.2, "%")}, 60.0),
    "electrical.energy_kwh": ({"range": P([0, 1e6], "kWh"), "resolution": P(0.1, "kWh"), "accuracy_pct_reading": P(1, "%"),
                               "noise_sd": P(0.1, "kWh")}, 120.0),
    "soil.moisture_pct": ({"range": P([0, 60], "%VWC"), "resolution": P(0.1, "%"), "accuracy": P(3, "%VWC"),
                           "noise_sd": P(0.2, "%VWC")}, 25.0),
}
N = 20000


def model(qid, **extra):
    params = dict(FIXTURES[qid][0]) if qid in FIXTURES else {}
    params.update(extra)
    return MeasurementModel.from_params(qid, params)


def const(qid, n=N):
    v = np.asarray(FIXTURES[qid][1], float)
    return np.tile(v, (n, 1)) if v.ndim else np.full(n, float(v))


class TestCatalog(unittest.TestCase):
    def test_required_quantities(self):
        need = {"air.temperature_c", "air.humidity_rh", "air.pressure_hpa", "air.o2_pct", "air.co_ppm", "air.h2s_ppm",
                "air.lel_pct", "air.voc_ppm", "air.co2_ppm", "light.lux", "body.accel_g", "body.gyro_dps", "body.mag_ut"}
        self.assertTrue(need <= set(CATALOG))
        self.assertTrue({"water.temperature_c", "water.ph", "electrical.current_a", "machine.vibration_mm_s",
                         "soil.moisture_pct"} <= set(CATALOG))
        self.assertEqual(CATALOG["body.accel_g"].columns(), ["accel_x_g", "accel_y_g", "accel_z_g"])
        self.assertEqual(CATALOG["air.humidity_rh"].upper, 100.0)

    def test_every_quantity_has_a_fixture(self):
        self.assertEqual(set(FIXTURES), set(CATALOG))


class TestConstantWorld(unittest.TestCase):
    """Per quantity: constant world -> resolution grid, range, bias within accuracy, noise level."""

    def test_each_quantity(self):
        for qid in CATALOG:
            with self.subTest(qid):
                m = model(qid)
                x = const(qid)
                rng = np.random.default_rng(1)
                draw = m.draw(rng)
                r = m.measure(x, 1.0, rng, draw=draw)
                v = r.values.reshape(N, -1)
                xt = x.reshape(N, -1)[0]
                res, sd = m.resolution, m.noise_sd
                # resolution grid and range
                self.assertTrue(np.allclose(v / res, np.round(v / res), atol=1e-6), "not on the resolution grid")
                lo, hi = m.bounds
                self.assertTrue((v >= lo).all() and (v <= hi).all())
                self.assertFalse(r.over_range.any() or r.under_range.any())
                # bias: where the unit's draw puts it, and within ±accuracy
                mean_err = v.mean(axis=0) - xt
                tol = res / 2 + 5 * sd / np.sqrt(N)
                np.testing.assert_allclose(mean_err, m.bias(xt, draw), atol=tol)
                self.assertTrue((np.abs(mean_err) <= m.error_bound(xt) + tol).all())
                # noise: datasheet sd plus the quantisation step (res^2 / 12)
                expect = np.sqrt(sd ** 2 + res ** 2 / 12)
                np.testing.assert_allclose(v.std(axis=0), expect, rtol=0.05)

    def test_noiseless_is_constant(self):
        m = model("air.h2s_ppm", noise_sd=P(0, "ppm"))
        r = m.measure(np.full(100, 5.0), 1.0, np.random.default_rng(0))
        self.assertEqual(len(np.unique(r.values)), 1)

    def test_same_seed_same_output(self):
        a = model("air.co_ppm").measure(const("air.co_ppm", 500), 1.0, np.random.default_rng(7)).values
        b = model("air.co_ppm").measure(const("air.co_ppm", 500), 1.0, np.random.default_rng(7)).values
        np.testing.assert_array_equal(a, b)

    def test_vector_axes_have_their_own_bias(self):
        d = model("body.accel_g").draw(np.random.default_rng(3))
        self.assertEqual(len(set(np.round(d.u_bias, 9))), 3)


class TestStages(unittest.TestCase):
    rng = np.random.default_rng(0)

    def bare(self, qid="air.co_ppm", rng_=(0, 1000), res=0.001, **kw):
        return MeasurementModel.from_params(qid, {"range": P(list(rng_), "ppm"), "resolution": P(res, "ppm"), **kw})

    def test_range_clip_and_flags(self):
        m = self.bare(rng_=(0, 500), res=1)
        r = m.measure(np.array([-5.0, 250.0, 900.0]), 1.0, self.rng)
        np.testing.assert_array_equal(r.values, [0, 250, 500])
        np.testing.assert_array_equal(r.over_range, [False, False, True])
        np.testing.assert_array_equal(r.under_range, [True, False, False])

    def test_t90(self):
        dt = 0.1
        m = self.bare(t90_s=P(15, "s"))
        x = np.r_[np.zeros(10), np.full(3000, 100.0)]
        y = m.measure(x, dt, self.rng).values
        t_cross = (np.argmax(y >= 90) - 9) * dt          # step happens between sample 9 and 10
        self.assertAlmostEqual(t_cross, 15.0, delta=dt)

    def test_t90_up_and_down(self):
        dt = 0.5
        m = self.bare(t90_up_s=P(10, "s"), t90_down_s=P(40, "s"))
        x = np.r_[np.zeros(1), np.full(400, 100.0), np.zeros(800)]
        y = m.measure(x, dt, self.rng).values
        up = np.argmax(y >= 90) * dt
        down = (np.argmax(y[401:] <= 10) + 1) * dt
        self.assertAlmostEqual(up, 10, delta=dt)
        self.assertAlmostEqual(down, 40, delta=dt)

    def test_accuracy_combine_max(self):
        m = self.bare(accuracy=P(2, "ppm"), accuracy_pct_reading=P(10, "%"), accuracy_combine=P("max", "-"))
        np.testing.assert_allclose(m.error_bound(np.array([5.0, 100.0])), [2.0, 10.0])
        s = self.bare(accuracy=P(2, "ppm"), accuracy_pct_reading=P(10, "%"))
        np.testing.assert_allclose(s.error_bound(np.array([5.0, 100.0])), [2.5, 12.0])

    def test_drift_is_linear_within_bound(self):
        m = self.bare(drift_per_hour=P(1.0, "ppm/h"))
        rng = np.random.default_rng(2)
        d = m.draw(rng)
        y = m.measure(np.full(3601, 100.0), 10.0, rng, draw=d).values      # 10 h
        slope = (y[-1] - y[0]) / 10.0
        self.assertAlmostEqual(slope, d.u_drift[0] * 1.0, delta=0.001)
        self.assertLessEqual(abs(slope), 1.0 + 1e-3)

    def test_drift_per_year_unit(self):
        m = self.bare(drift_per_hour=P(8.76, "ppm/year"))
        self.assertAlmostEqual(m.drift_per_hour, 0.001)

    def test_hysteresis(self):
        m = self.bare(hysteresis=P(2.0, "ppm"))
        ramp = np.r_[np.linspace(0, 50, 501), np.linspace(50, 0, 501)]
        y = m.measure(ramp, 1.0, self.rng).values
        up, down = y[100:400], y[601:900]
        np.testing.assert_allclose(up, ramp[100:400] - 1.0, atol=1e-6)        # lags by h/2 going up
        np.testing.assert_allclose(down, ramp[601:900] + 1.0, atol=1e-6)      # and going down
        self.assertAlmostEqual(np.interp(25, ramp[601:900][::-1], down[::-1]) - np.interp(25, ramp[100:400], up), 2.0,
                               places=6)

    def test_deadband(self):
        m = self.bare(deadband=P(1.0, "ppm"))
        y = m.measure(np.array([0.5, -0.9, 1.5]), 1.0, self.rng).values
        np.testing.assert_allclose(y, [0, 0, 1.5])
        o2 = MeasurementModel.from_params("air.o2_pct", {"range": P([0, 25], "%vol"), "resolution": P(0.1, "%vol"),
                                                         "deadband": P(0.3, "%vol"), "deadband_center": P(20.9, "%vol")})
        np.testing.assert_allclose(o2.measure(np.array([20.7, 20.5]), 1.0, self.rng).values, [20.9, 20.5])

    def test_order_deadband_quantize_clip(self):
        # deadband before quantisation: 0.9 is suppressed (quantising first would give 1, outside the deadband)
        m = self.bare(res=1, deadband=P(1.0, "ppm"))
        self.assertEqual(m.measure(np.array([0.9]), 1.0, self.rng).values[0], 0.0)
        # quantise before clip: 100.4 -> 100 (in range); 100.6 -> 101 -> clipped to 100 and flagged
        m = self.bare(rng_=(0, 100), res=1)
        r = m.measure(np.array([100.4, 100.6]), 1.0, self.rng)
        np.testing.assert_array_equal(r.values, [100, 100])
        np.testing.assert_array_equal(r.over_range, [False, True])

    def test_stage_order_recorded(self):
        m = self.bare(t90_s=P(5, "s"), noise_sd=P(0.1, "ppm"), cross_sensitivity=P(
            {"air.h2s_ppm": {"factor": 0.1, "ref": 0}}, "-"))
        r = m.measure(np.full(10, 1.0), 1.0, self.rng, others={"air.h2s_ppm": np.zeros(10)}, keep_stages=True)
        self.assertEqual(list(r.stages), ["world", "frame", "cross", "response", "bandwidth", "bias_drift", "noise",
                                          "hysteresis", "deadband", "quantized"])

    def test_bandwidth_low_pass(self):
        dt, fc = 0.001, 5.0
        m = self.bare(bandwidth_hz=P(fc, "Hz"))
        y = m.measure(np.r_[0.0, np.full(2000, 100.0)], dt, self.rng).values
        tau = 1 / (2 * np.pi * fc)
        self.assertAlmostEqual(np.argmax(y >= 100 * (1 - np.exp(-1))) * dt, tau, delta=2 * dt)

    def test_bandwidth_after_response(self):
        # response then bandwidth: two first-order stages in series are slower than either alone
        dt = 0.01
        x = np.r_[0.0, np.full(3000, 100.0)]
        both = self.bare(t90_s=P(1, "s"), bandwidth_hz=P(0.5, "Hz")).measure(x, dt, self.rng, keep_stages=True)
        np.testing.assert_allclose(both.stages["bandwidth"], self.bare(bandwidth_hz=P(0.5, "Hz")).band_limit(
            both.stages["response"], dt))

    def test_odr_gives_bandwidth(self):
        m = self.bare(odr_hz=P(100, "Hz"))
        self.assertEqual(m.bandwidth_hz, 50)
        self.assertTrue(m.sources["bandwidth_hz"].startswith("ASSUMPTION"))
        self.assertEqual(self.bare(odr_hz=P(100, "Hz"), bandwidth_hz=P(20, "Hz")).bandwidth_hz, 20)

    def test_bias_distribution(self):
        m = self.bare(accuracy=P(1, "ppm"))
        self.assertTrue(m.sources["bias_distribution"].startswith("ASSUMPTION"))
        self.assertEqual(m.bias_distribution, "uniform")
        n = self.bare(accuracy=P(1, "ppm"), bias_distribution=P("normal", "-"))
        rng = np.random.default_rng(4)
        u = np.array([n.draw(rng).u_bias[0] for _ in range(20000)])
        self.assertLessEqual(np.abs(u).max(), 1.0)
        self.assertAlmostEqual(u.std(), 1 / 3, delta=0.01)
        uu = np.array([m.draw(rng).u_bias[0] for _ in range(20000)])
        self.assertAlmostEqual(uu.std(), 1 / np.sqrt(3), delta=0.01)
        stated = self.bare(accuracy=P(1, "ppm"),                     # a datasheet that says its limits are 3-sigma
                           bias_distribution={"value": "normal", "unit": "-", "source": "datasheet X p.2 note 3"})
        self.assertEqual(stated.bias_distribution, "normal")
        with self.assertRaises(ParamError):
            self.bare(bias_distribution={"value": "gamma", "unit": "-", "source": "ASSUMPTION: x"})


class TestKinds(unittest.TestCase):
    """typical = a 1σ spread (normal, sd = value, cut at 3σ); max = a hard bound."""

    def units(self, m, n=20000, seed=5):
        rng = np.random.default_rng(seed)
        return np.array([m.bias(np.array([100.0]), m.draw(rng))[0] for _ in range(n)])

    def base(self, **kw):
        return MeasurementModel.from_params("air.co_ppm", {"range": P([0, 1000], "ppm"), "resolution": P(0.1, "ppm"), **kw})

    def test_typical_is_one_sigma(self):
        m = self.base(**normalize("accuracy_typical", 2, "ppm", "datasheet X p.1"))
        self.assertEqual(m.kind("accuracy"), "typical")
        b = self.units(m)
        self.assertAlmostEqual(b.std(), 2.0, delta=0.05)
        self.assertLessEqual(np.abs(b).max(), 6.0)
        self.assertGreater(np.abs(b).max(), 4.0)                # not cut at the typical value
        self.assertEqual(m.error_bound(100.0), 6.0)              # the gate's bound: 3σ

    def test_max_is_a_hard_bound(self):
        for dist in ("uniform", "normal"):
            m = self.base(accuracy=dict(P(2, "ppm"), kind="max"), bias_distribution=P(dist, "-"))
            b = self.units(m)
            self.assertLessEqual(np.abs(b).max(), 2.0)
            self.assertAlmostEqual(b.std(), 2 / np.sqrt(3) if dist == "uniform" else 2 / 3, delta=0.03)
            self.assertEqual(m.error_bound(100.0), 2.0)

    def test_mixed_kinds(self):
        # BMM150 style: offset typical + gain max, summed; each part drawn on its own
        m = self.base(accuracy=dict(P(2, "ppm"), kind="typical"), accuracy_pct_reading=dict(P(5, "%"), kind="max"))
        self.assertEqual(m.error_bound(100.0), 6.0 + 5.0)
        self.assertLessEqual(np.abs(self.units(m)).max(), 11.0)
        with self.assertRaises(ParamError):                     # whichever-greater needs one kind
            self.base(accuracy=dict(P(2, "ppm"), kind="typical"), accuracy_pct_reading=dict(P(5, "%"), kind="max"),
                      accuracy_combine=P("max", "-"))

    def test_kind_checked(self):
        with self.assertRaises(ParamError):
            self.base(noise_sd=dict(P(1, "ppm"), kind="typical"))
        with self.assertRaises(ParamError):
            self.base(accuracy=dict(P(1, "ppm"), kind="average"))
        d = normalize("drift", 1, "ppm/year", "datasheet X p.1", kind="typical")
        self.assertEqual(d["drift_per_hour"]["kind"], "typical")
        self.assertEqual(self.base().kind("accuracy"), "max")   # not stated -> hard bound

    def test_typical_drift_spread(self):
        m = self.base(drift_per_hour=dict(P(1.0, "ppm/h"), kind="typical"))
        rng = np.random.default_rng(1)
        u = np.array([m.draw(rng).u_drift[0] for _ in range(20000)])
        self.assertAlmostEqual(u.std(), 1.0, delta=0.03)
        self.assertLessEqual(np.abs(u).max(), 3.0)


class TestVectorFrames(unittest.TestCase):
    rng = np.random.default_rng(0)

    def vec(self, qid="body.accel_g", unit="g", **kw):
        return MeasurementModel.from_params(qid, {"range": P([-100, 100], unit), "resolution": P(1e-6, unit), **kw})

    def test_mounting_orientation(self):
        # sensor rolled 90° on the body: body z (up) lies along sensor y
        m = self.vec(**normalize("mounting_euler", (90, 0, 0), "°", T))
        y = m.measure(np.tile([0.0, 0.0, 1.0], (5, 1)), 1.0, self.rng).values
        np.testing.assert_allclose(y, np.tile([0, 1, 0], (5, 1)), atol=1e-6)

    def test_body_orientation_from_world(self):
        # body yawed 90° (body -> world): world north appears on body −y
        m = self.vec("body.mag_ut", "µT")
        q = np.tile(rot.from_euler_deg(0, 0, 90), (3, 1))
        y = m.measure(np.tile([30.0, 0.0, -40.0], (3, 1)), 1.0, self.rng, body_quat=q).values
        np.testing.assert_allclose(y, np.tile([0, -30, -40], (3, 1)), atol=1e-5)

    def test_cross_axis_bound(self):
        m = self.vec(cross_axis_pct=P(2, "%"))
        for s in range(50):
            a = m.draw(np.random.default_rng(s)).axes
            np.testing.assert_allclose(np.diag(a), 1.0)
            self.assertLessEqual(np.abs(a - np.diag(np.diag(a))).max(), 0.02 + 1e-12)

    def test_misalignment_bound(self):
        m = self.vec(misalignment_deg=P(1, "deg"))
        angles = []
        for s in range(50):
            a = m.draw(np.random.default_rng(s)).axes
            np.testing.assert_allclose(a @ a.T, np.eye(3), atol=1e-12)           # a pure rotation
            angles.append(np.degrees(np.arccos(np.clip((np.trace(a) - 1) / 2, -1, 1))))
        self.assertLessEqual(max(angles), 1.0 + 1e-9)
        self.assertGreater(max(angles), 0.5)

    def test_range_per_axis(self):
        m = self.vec("body.mag_ut", "µT", range=P([[-1300, 1300], [-1300, 1300], [-2500, 2500]], "µT"))
        r = m.measure(np.tile([2000.0, 0.0, 2000.0], (2, 1)), 1.0, self.rng)
        np.testing.assert_allclose(r.values[0], [1300, 0, 2000])
        np.testing.assert_array_equal(r.over_range[0], [True, False, False])
        with self.assertRaises(ParamError):
            self.vec(range=P([[-1, 1], [-1, 1]], "g"))

    def test_vector_only_params_rejected_for_scalar(self):
        with self.assertRaises(ParamError):
            model("air.co_ppm", cross_axis_pct=P(1, "%"))
        with self.assertRaises(ParamError):
            model("air.co_ppm", mounting_orientation=P([1, 0, 0, 0], "-"))

    def test_cross_sensitivity(self):
        m = MeasurementModel.from_params("air.h2s_ppm", {
            "range": P([0, 100], "ppm"), "resolution": P(0.1, "ppm"),
            **normalize("cross_gas", 6, "ppm", T, gas="air.co_ppm", applied=300)})
        y = m.measure(np.zeros(5), 1.0, self.rng, others={"air.co_ppm": np.full(5, 300.0)}).values
        np.testing.assert_allclose(y, 6.0)
        with self.assertRaises(ValueError):
            m.measure(np.zeros(5), 1.0, self.rng)

    def test_vector_shape_checked(self):
        with self.assertRaises(ValueError):
            model("body.accel_g").measure(np.zeros(10), 1.0, self.rng)


class TestParams(unittest.TestCase):
    base = {"range": P([0, 100], "ppm"), "resolution": P(0.1, "ppm")}

    def test_source_required(self):
        with self.assertRaises(ParamError):
            MeasurementModel.from_params("air.co_ppm", {**self.base, "accuracy": {"value": 1, "unit": "ppm"}})
        with self.assertRaises(ParamError):
            MeasurementModel.from_params("air.co_ppm", {**self.base, "accuracy": {"value": 1, "unit": "ppm",
                                                                                 "source": "a guess"}})

    def test_unit_checked_and_converted(self):
        with self.assertRaises(ParamError):
            MeasurementModel.from_params("air.co_ppm", {**self.base, "accuracy": P(1, "°C")})
        m = MeasurementModel.from_params("air.pressure_hpa", {"range": P([30000, 110000], "Pa"),
                                                              "resolution": P(1, "Pa")})
        self.assertEqual(m.range, (300.0, 1100.0))
        self.assertAlmostEqual(m.resolution, 0.01)
        g = MeasurementModel.from_params("body.gyro_dps", {"range": P([-2000, 2000], "dps"),
                                                           "resolution": P(70, "mdps")})
        self.assertAlmostEqual(g.resolution, 0.07)
        t = MeasurementModel.from_params("air.temperature_c", {"range": P([-40, 85], "C"),
                                                               "resolution": P(0.01, "degC")})
        self.assertEqual(t.range, (-40, 85))

    def test_unknown_and_missing(self):
        with self.assertRaises(ParamError):
            MeasurementModel.from_params("air.co_ppm", {**self.base, "gain": P(1, "-")})
        with self.assertRaises(ParamError):
            MeasurementModel.from_params("air.co_ppm", {"range": P([0, 100], "ppm")})
        with self.assertRaises(ParamError):
            MeasurementModel.from_params("air.co_ppm", {**self.base, "noise_density": P(1, "ppm/√Hz")})
        with self.assertRaises(KeyError):
            MeasurementModel.from_params("air.nothing", self.base)

    def test_sources_kept(self):
        m = MeasurementModel.from_params("body.accel_g", {
            "range": P([-16, 16], "g"), "resolution": P(1 / 1024, "g"),
            **normalize("noise_density", 150, "µg/√Hz", "datasheet X p.3", odr_hz=200)})
        self.assertAlmostEqual(m.noise_sd, 150e-6 * np.sqrt(100))
        self.assertIn("ASSUMPTION: bandwidth = ODR / 2", m.sources["noise_sd"])


class TestNormalize(unittest.TestCase):
    def test_every_rule_example(self):
        for r in RULES:
            with self.subTest(r.id):
                qid, v, u, ctx, expected = r.example
                params = normalize(r.id, v, u, "datasheet test p.1", **ctx)
                qu = CATALOG[qid].unit
                params.setdefault("range", P([-1e5, 1e5], qu))
                params.setdefault("resolution", P(1e-6, qu))
                m = MeasurementModel.from_params(qid, params)
                for k, e in expected.items():
                    got = getattr(m, k)
                    if isinstance(e, (int, float)) and not isinstance(e, bool):
                        self.assertAlmostEqual(got, e, places=9, msg=k)
                    elif isinstance(e, tuple):
                        np.testing.assert_allclose(got, e)
                    else:
                        self.assertEqual(got, e, k)
                for p in params.values():
                    self.assertTrue(p["source"].startswith(("datasheet", "ASSUMPTION")))

    def test_assumption_marked_in_source(self):
        self.assertIn("ASSUMPTION", normalize("noise_pp", 1, "mg", "datasheet X p.2")["noise_sd"]["source"])
        self.assertNotIn("ASSUMPTION", normalize("accuracy", 1, "hPa", "datasheet X p.2")["accuracy"]["source"])

    def test_doc_is_generated_from_code(self):
        with open(DOC) as fh:
            self.assertEqual(fh.read(), markdown(), "run: python3 cli/parameter_mapping.py")


if __name__ == "__main__":
    unittest.main()
