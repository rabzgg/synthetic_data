"""
Unit tests for the joint-template motion engine.

Run:  python3 -m unittest discover -s tests -v      (from clean_project/)
"""
import copy
import json
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.generator import SyntheticXDKGenerator
from core.joint_template import canonicalize, Q_COLS, A_COLS, M_COLS

CFG_DIR = os.path.join(ROOT, "configs", "robot_arm")
DURATION = 600.0
SEED = 7


def _scenario(k, joint=True):
    with open(os.path.join(CFG_DIR, f"sensor_{k}_joint.json")) as f:
        s = json.load(f)
    s["duration_s"] = DURATION
    s["motion"]["bank"] = os.path.join(CFG_DIR, s["motion"]["bank"])
    if not joint:
        s["motion"]["joint_template"] = False
    return s


_CACHE = {}


def _generate(k, joint=True, seed=SEED):
    key = (k, joint, seed)
    if key not in _CACHE:
        gen = SyntheticXDKGenerator(_scenario(k, joint), seed=seed)
        _CACHE[key] = (gen.generate(), gen)
    return _CACHE[key]


class TestCanonicalize(unittest.TestCase):
    def test_flip_negates_all_four_components(self):
        rng = np.random.default_rng(0)
        q = rng.normal(size=(1000, 4))
        q /= np.linalg.norm(q, axis=1, keepdims=True)
        out = canonicalize(q)
        self.assertTrue(np.all(out[:, 0] >= 0))
        flipped = q[:, 0] < 0
        np.testing.assert_array_equal(out[flipped], -q[flipped])      # all four together
        np.testing.assert_array_equal(out[~flipped], q[~flipped])     # untouched otherwise

    def test_output_sign_changes_are_full_flips(self):
        """Every one-sample hemisphere change in generated sensor_1 negates x, y, z together."""
        df, _ = _generate(1)
        x = df[list(Q_COLS)].to_numpy(float)
        t = (df["timestamp"].to_numpy(float) - df["timestamp"].iloc[0]) / 1000.0
        dt = np.diff(t)
        normal = dt <= 2 * np.median(dt)
        a, b = x[:-1], x[1:]
        big = np.any(np.abs(b - a) > 0.3, axis=1) & normal
        self.assertGreater(big.sum(), 0, "expected hemisphere flips in sensor_1 (rotates ~180°)")
        full = np.all(np.abs(b + a) < 0.1, axis=1)
        self.assertEqual(int(np.sum(big & ~full)), 0, "partial (non-q->-q) flip found")


class TestQuantisation(unittest.TestCase):
    def _on_grid(self, v, step):
        return np.all(np.abs(v / step - np.round(v / step)) < 1e-6)

    def test_xdk_resolution(self):
        for k in (1, 2, 3):
            df, _ = _generate(k)
            with self.subTest(sensor=k):
                self.assertTrue(self._on_grid(df[list(Q_COLS)].to_numpy(float), 1e-4), "quat not 4 decimals")
                self.assertTrue(self._on_grid(df[list(A_COLS)].to_numpy(float), 1e-3), "accel not 0.001 g")
                self.assertTrue(self._on_grid(df[list(M_COLS)].to_numpy(float), 1.0), "mag not integer")


class TestSharedSchedule(unittest.TestCase):
    def test_three_sensors_share_schedule(self):
        scheds = [_generate(k)[1].joint_schedule for k in (1, 2, 3)]
        keys = ("template", "start_s", "warp", "residual_donor")
        ref = [tuple(c[k] for k in keys) for c in scheds[0]]
        self.assertGreater(len(ref), 10)
        for k, sc in zip((2, 3), scheds[1:]):
            with self.subTest(sensor=k):
                self.assertEqual([tuple(c[kk] for kk in keys) for c in sc], ref)

    def test_schedule_depends_on_seed(self):
        a = _generate(1, seed=SEED)[1].joint_schedule
        b = _generate(1, seed=SEED + 1)[1].joint_schedule
        self.assertNotEqual([c["template"] for c in a], [c["template"] for c in b])


class TestFlagOff(unittest.TestCase):
    def test_non_motion_columns_unchanged_and_flag_off_is_noop(self):
        on, _ = _generate(2, joint=True)
        off, gen_off = _generate(2, joint=False)
        self.assertIsNone(gen_off.joint_schedule)
        motion = set(Q_COLS) | set(A_COLS) | set(M_COLS) | {"mag_res"}
        for c in on.columns:
            if c not in motion:
                np.testing.assert_array_equal(on[c].to_numpy(), off[c].to_numpy(), err_msg=c)
        # flag off == config without any "motion" key
        s = _scenario(2, joint=False)
        s.pop("motion")
        bare = SyntheticXDKGenerator(s, seed=SEED).generate()
        self.assertTrue(bare.equals(off))


if __name__ == "__main__":
    unittest.main()
