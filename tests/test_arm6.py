"""
Unit tests for the six-sensor arm setup: one shared schedule, N-sensor cross-sensor checks,
the data-based copy rule and the mag-only own residual.

Run:  python3 -m unittest discover -s tests -v      (from clean_project/)
"""
import json
import os
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import physics_gate as G
import real_bootstrap as RB
import validate_physics as V
from core.generator import SyntheticXDKGenerator
from core.joint_template import A_COLS, M_COLS

CFG_DIR = os.path.join(ROOT, "configs", "robot_arm_6")
_CACHE = {}


def _generate(k, **motion):
    key = (k, tuple(sorted(motion.items())))
    if key not in _CACHE:
        s = json.load(open(os.path.join(CFG_DIR, f"sensor_{k}_joint.json")))
        s["duration_s"] = 600.0
        s["motion"]["bank"] = os.path.join(CFG_DIR, s["motion"]["bank"])
        s["motion"].update(motion)
        gen = SyntheticXDKGenerator(s, seed=7)
        _CACHE[key] = (gen.generate(), gen)
    return _CACHE[key]


def _write(path, t_s, accel, extra=None):
    d = pd.DataFrame({"timestamp": np.round(t_s * 1000).astype(int)})
    for i, c in enumerate(("acceleration_x", "acceleration_y", "acceleration_z")):
        d[c] = accel[:, i]
    for c, v in (extra or {}).items():
        d[c] = v
    d.to_csv(path, index=False)


class TestSixSensorSchedule(unittest.TestCase):
    def test_all_six_sensors_share_one_schedule(self):
        keys = ("template", "start_s", "warp", "residual_donor")
        scheds = [[tuple(c[kk] for kk in keys) for c in _generate(k)[1].joint_schedule] for k in range(1, 7)]
        self.assertGreater(len(scheds[0]), 10)
        for k, sc in enumerate(scheds[1:], 2):
            with self.subTest(sensor=k):
                self.assertEqual(sc, scheds[0])


class TestMagResidual(unittest.TestCase):
    def test_mag_own_changes_mag_only(self):
        a, _ = _generate(4, mag_residual=None)
        b, _ = _generate(4, mag_residual="own")
        np.testing.assert_array_equal(a[list(A_COLS)].to_numpy(), b[list(A_COLS)].to_numpy())
        self.assertGreater(np.abs(a[list(M_COLS)].to_numpy() - b[list(M_COLS)].to_numpy()).max(), 0)


class TestInterSensorN(unittest.TestCase):
    def test_pairs_agreement_and_desynchronised_sensor(self):
        """4 sensors on one clock: 3 move together, the 4th runs on its own schedule."""
        rng = np.random.default_rng(0)
        t = 1.7e9 + np.arange(0, 1200, 0.1)
        on = (np.sin(2 * np.pi * (t - t[0]) / 37.0) > 0)
        off = (np.sin(2 * np.pi * (t - t[0]) / 41.3 + 1.0) > 0)
        with tempfile.TemporaryDirectory() as td:
            paths = []
            for i, mv in enumerate((on, on, on, off)):
                acc = np.c_[np.zeros(len(t)), np.zeros(len(t)), np.ones(len(t))]
                acc += rng.normal(0, 0.002, acc.shape) + mv[:, None] * rng.normal(0, 0.05, acc.shape)
                paths.append(os.path.join(td, f"s{i}.csv"))
                _write(paths[-1], t, acc)
            c = V.check_inter_sensor(paths, None)["real"]
            self.assertEqual(len(c["activity_corr"]), 6)                       # every pair
            self.assertGreater(c["activity_corr"]["s1-s2"], 0.8)
            self.assertLess(abs(c["activity_corr"]["s1-s4"]), 0.3)
            c3 = V.check_inter_sensor(paths[:3], None)["real"]
            self.assertGreater(c3["all_agree_pct"], c["all_agree_pct"] + 20)   # 4-way agreement drops


class TestCopyRule(unittest.TestCase):
    def _real(self, td, repeat):
        """95 min of 37 s cycles; repeat=True -> every cycle identical, else each cycle differs."""
        rng = np.random.default_rng(1)
        t = np.arange(0, 95 * 60, 0.1)
        ph = (t % 37.0) / 37.0
        cyc = (t // 37.0).astype(int)
        amp = np.ones(cyc.max() + 1) if repeat else rng.uniform(0.3, 1.7, cyc.max() + 1)
        shape = np.sin(2 * np.pi * ph)[:, None] * amp[cyc][:, None] * np.array([1.0, 0.5, -0.7])
        if not repeat:
            shape += np.sin(6 * np.pi * ph + rng.uniform(0, 6, cyc.max() + 1)[cyc])[:, None] * 0.6
        extra = {c: shape[:, i % 3] * (0.1 + 0.1 * i) for i, c in enumerate(G.MOTION9) if not c.startswith("accel")}
        p = os.path.join(td, f"real_{repeat}.csv")
        _write(p, t, shape, extra)
        return p

    def test_repetitive_real_makes_copy_uninformative(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(G.copy_informative(self._real(td, True), 37.0)["informative"])
            self.assertTrue(G.copy_informative(self._real(td, False), 37.0)["informative"])


class TestBlockBootstrap(unittest.TestCase):
    def test_blocks_are_whole_consecutive_cycles(self):
        period, n_cyc = 37.0, 97
        t = np.arange(0, n_cyc * period, 0.1)
        cyc = np.floor(t / period).astype(int)
        masks = list(RB.block_masks(t, 0.0, n_cyc * period, period, n_boot=20, seed=3))
        self.assertEqual(len(masks), 20)
        per_cycle = np.bincount(cyc)
        for m in masks:
            counts = np.bincount(cyc[m], minlength=n_cyc)
            used = np.flatnonzero(counts)
            np.testing.assert_array_equal(counts[used] % per_cycle[used], 0)     # whole cycles only
            self.assertEqual(len(m), per_cycle[:n_cyc].mean() * n_cyc)          # as many cycles as the span
        again = list(RB.block_masks(t, 0.0, n_cyc * period, period, n_boot=20, seed=3))
        np.testing.assert_array_equal(masks[5], again[5])

    def test_sd_tracks_between_cycle_variation(self):
        """The bootstrap sd of a mean shrinks when cycles agree with each other."""
        rng = np.random.default_rng(0)
        period, n_cyc = 37.0, 97
        t = np.arange(0, n_cyc * period, 0.1)
        cyc = np.floor(t / period).astype(int)
        sd = {}
        for spread in (0.1, 1.0):
            x = rng.normal(0, spread, n_cyc)[cyc] + rng.normal(0, 0.01, len(t))
            sd[spread] = RB.sd_boot([x[m].mean() for m in RB.block_masks(t, 0.0, n_cyc * period, period)])
        self.assertGreater(sd[1.0], 5 * sd[0.1])


if __name__ == "__main__":
    unittest.main()
