"""
Derived channels: STEL/TWA give the same numbers as the gas detector engine; the orientation
filter (Madgwick, an ASSUMPTION) recovers a known orientation and tracks a rotation.
"""
import json
import os
import sys
import unittest

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.derived import DERIVED, OrientationQuat, Stel, Twa, build, madgwick
from core.derived.fusion import initial_orientation
from core.quantities import rotation as rot

GAS = {"co": "air.co_ppm", "h2s": "air.h2s_ppm"}


class TestExposure(unittest.TestCase):
    def test_same_as_gas_engine(self):
        """Rows before the first connection gap: every sample the STEL/TWA saw is in the CSV."""
        for dev, seed in (("blackline_g8", 43), ("msa_altair_io4", 44)):
            d = pd.read_csv(os.path.join(ROOT, "data", "gas", f"{dev}_shift_seed{seed}.csv"))
            first_gap = int(np.argmax(d["gap_before_s"].to_numpy() > 0)) or len(d)
            d = d.iloc[:first_gap]
            with open(os.path.join(ROOT, "configs", "gas", dev, "spec.json")) as fh:
                spec = json.load(fh)
            for g, qid in GAS.items():
                ch = spec["channels"][g]
                qz = (ch["resolution"]["value"], ch["range_min"]["value"], ch["range_max"]["value"])
                r = {qid: d[ch["column"]].to_numpy()}
                stel = Stel(qid, quantize=qz).compute(r, 10.0)
                twa = Twa(qid, quantize=qz).compute(r, 10.0)
                np.testing.assert_allclose(stel[f"{g}_stel_ppm"], d[f"{g}_stel_ppm"], atol=1e-9, err_msg=f"{dev} {g}")
                np.testing.assert_allclose(twa[f"{g}_twa_ppm"], d[f"{g}_twa_ppm"], atol=1e-9, err_msg=f"{dev} {g}")

    def test_window_zero_filled(self):
        out = Stel("air.h2s_ppm").compute({"air.h2s_ppm": np.full(200, 30.0)}, 10.0)["h2s_stel_ppm"]
        self.assertAlmostEqual(out[0], 30.0 / 90)          # one sample in a 90-sample window
        self.assertAlmostEqual(out[89], 30.0)

    def test_params_need_source(self):
        with self.assertRaises(ValueError):
            Stel("air.h2s_ppm", params={"window_s": {"value": 600, "unit": "s"}})
        with self.assertRaises(ValueError):
            Stel("air.h2s_ppm", params={"length": {"value": 600, "unit": "s", "source": "ASSUMPTION: x"}})
        s = Stel("air.h2s_ppm", params={"window_s": {"value": 600, "unit": "s", "source": "ASSUMPTION: test"}})
        self.assertEqual(s.p("window_s"), 600)


B_WORLD = np.array([20.0, 0.0, -45.0])          # µT: north and down (northern hemisphere)


def sensor_readings(q_sensor_to_world):
    """What an ideal sensor reads for orientation q: gravity (+1 g up) and the field, in sensor frame."""
    inv = rot.conj(q_sensor_to_world)
    return rot.rotate(inv, [0.0, 0.0, 1.0]), rot.rotate(inv, B_WORLD)


class TestFusion(unittest.TestCase):
    def test_initial_orientation_exact(self):
        rng = np.random.default_rng(0)
        for _ in range(20):
            q = rot.normalize(rng.normal(size=4))
            a, m = sensor_readings(q)
            self.assertLess(np.degrees(rot.angle_between(initial_orientation(a, m), q)), 1e-4)     # float precision

    def test_static_stays_put(self):
        q = rot.from_euler_deg(20, -35, 120)
        a, m = sensor_readings(q)
        n = 500
        out = madgwick(np.tile(a, (n, 1)), np.zeros((n, 3)), np.tile(m, (n, 1)), 0.01, 0.1)
        # Madgwick normalises the gradient, so even at zero error every step moves by beta * dt (0.057° here);
        # the estimate jitters around the truth within a few steps of that size and does not wander off
        self.assertLess(np.degrees(rot.angle_between(out, q)).max(), 4 * np.degrees(0.1 * 0.01))

    def test_converges_from_wrong_start(self):
        q = rot.from_euler_deg(10, 40, -60)
        a, m = sensor_readings(q)
        n = 3000
        out = madgwick(np.tile(a, (n, 1)), np.zeros((n, 3)), np.tile(m, (n, 1)), 0.01, 0.5, q0=np.array([1.0, 0, 0, 0]))
        self.assertGreater(np.degrees(rot.angle_between(out[0], q)), 30)
        self.assertLess(np.degrees(rot.angle_between(out[-1], q)), 0.5)

    def test_tracks_rotation(self):
        dt, n, rate = 0.01, 1200, 30.0                    # 12 s turning at 30 °/s about world up
        tilt = rot.from_euler_deg(15, -10, 0)
        yaw = np.radians(rate) * dt * np.arange(n)
        q_true = rot.mul(np.stack([np.cos(yaw / 2), 0 * yaw, 0 * yaw, np.sin(yaw / 2)], -1), tilt)
        acc, mag = zip(*(sensor_readings(q) for q in q_true))
        gyro = np.tile(rot.rotate(rot.conj(tilt), [0, 0, rate]), (n, 1))     # world-up rate seen in sensor frame
        ch = OrientationQuat()
        out = ch.compute({"body.accel_g": np.array(acc), "body.gyro_dps": gyro, "body.mag_ut": np.array(mag)}, dt)
        q = np.stack([out[c] for c in ch.columns()], -1)
        self.assertLess(np.degrees(rot.angle_between(q, q_true)).max(), 1.0)
        self.assertTrue((q[:, 0] >= 0).all())

    def test_xyz_only_and_imu(self):
        ch = OrientationQuat(params={"write_w": {"value": False, "unit": "-", "source": "ASSUMPTION: test"},
                                     "use_mag": {"value": False, "unit": "-", "source": "ASSUMPTION: test"}},
                             prefix="quat")
        self.assertEqual(ch.columns(), ["quat_x", "quat_y", "quat_z"])
        self.assertEqual(ch.inputs(), ["body.accel_g", "body.gyro_dps"])
        q = rot.from_euler_deg(25, 15, 0)
        a, _ = sensor_readings(q)
        out = ch.compute({"body.accel_g": np.tile(a, (100, 1)), "body.gyro_dps": np.zeros((100, 3))}, 0.01)
        xyz = np.stack([out[c] for c in ch.columns()], -1)[-1]
        q_est = np.r_[np.sqrt(max(0.0, 1 - xyz @ xyz)), xyz]
        # without a magnetometer only the tilt (gravity direction) is defined
        np.testing.assert_allclose(rot.rotate(rot.conj(q_est), [0, 0, 1]), a, atol=1e-6)

    def test_registry(self):
        self.assertEqual(set(DERIVED), {"stel", "twa", "orientation_quat"})
        self.assertIsInstance(build("stel", quantity="air.co_ppm"), Stel)
        self.assertTrue(OrientationQuat().algorithm.startswith("ASSUMPTION"))


if __name__ == "__main__":
    unittest.main()
