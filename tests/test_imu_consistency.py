"""
Unit tests for imu_consistency.py (cross-column IMU checks).

Run:  python3 -m unittest discover -s tests -v      (from clean_project/)
"""
import os
import sys
import unittest

import numpy as np
from scipy.spatial.transform import Rotation

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from validation import imu_consistency as IC


def _signals(rot, M, A, speed):
    return {"rot": rot, "M": M, "A": A, "speed": speed, "grav": rot.inv().apply([0, 0, 1])}


class TestHardIron(unittest.TestCase):
    def test_recovers_offset_from_a_narrow_sweep(self):
        """Arm-like motion: only ±40° about two axes. A sphere fit is ill-posed there; the
        attitude-based least squares must still recover b."""
        rng = np.random.default_rng(0)
        n = 5000
        ang = np.c_[rng.uniform(-40, 40, n), rng.uniform(-40, 40, n), np.zeros(n)]
        rot = Rotation.from_euler("xyz", ang, degrees=True)
        m_world = np.array([20.0, -5.0, -45.0])
        b = np.array([-28.0, -23.0, 120.0])
        M = rot.inv().apply(m_world) + b + rng.normal(0, 0.5, (n, 3))
        est = IC.hard_iron_from_attitude(_signals(rot, M, np.zeros((n, 3)), np.zeros(n)))
        np.testing.assert_allclose(est, b, atol=1.0)

    def test_spread_small_when_consistent_large_when_not(self):
        rng = np.random.default_rng(1)
        n = 4000
        rot = Rotation.from_euler("xyz", np.c_[rng.uniform(-60, 60, (n, 2)), np.zeros(n)], degrees=True)
        m_world = np.array([20.0, 0.0, -45.0])
        b = np.zeros(3)
        M_ok = rot.inv().apply(m_world) + rng.normal(0, 0.3, (n, 3))
        M_bad = M_ok[rng.permutation(n)]                     # mag no longer tied to orientation
        A = rot.inv().apply([0, 0, 1])
        speed = np.full(n, 10.0)                             # all samples "moving"
        ok = IC.metrics(_signals(rot, M_ok, A, speed), b)
        bad = IC.metrics(_signals(rot, M_bad, A, speed), b)
        self.assertLess(ok["mag_world_spread_moving_deg"], 2.0)
        self.assertGreater(bad["mag_world_spread_moving_deg"], 10 * ok["mag_world_spread_moving_deg"])
        self.assertLess(ok["grav_moving_p95_deg"], 1e-4)     # accel == gravity exactly (arccos precision)


if __name__ == "__main__":
    unittest.main()
