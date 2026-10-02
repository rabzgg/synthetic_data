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


def _scenario(k, joint=True, motion=None):
    with open(os.path.join(CFG_DIR, f"sensor_{k}_joint.json")) as f:
        s = json.load(f)
    s["duration_s"] = DURATION
    s["motion"]["bank"] = os.path.join(CFG_DIR, s["motion"]["bank"])
    s["motion"].update(motion or {})
    if not joint:
        s["motion"]["joint_template"] = False
    return s


_CACHE = {}


def _generate(k, joint=True, seed=SEED, **motion):
    key = (k, joint, seed, tuple(sorted(motion.items())))
    if key not in _CACHE:
        gen = SyntheticXDKGenerator(_scenario(k, joint, motion), seed=seed)
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


class TestClock(unittest.TestCase):
    """The real XDK samples on a regular internal clock (100.003 ms) and only the logged timestamp
    is offset: a heavy-tailed delivery delay (late sample then catch-up, backlogs delivered within a
    few ms) that is shared between sensors. Step angle is uncorrelated with dt."""

    def test_regular_ticks_and_gaps(self):
        on, _ = _generate(1, joint=True, log_jitter="none")
        off, _ = _generate(1, joint=False)
        ts = on["timestamp"].to_numpy(float)
        self.assertTrue(np.all(np.abs((ts - ts[0]) / 100.0 - np.round((ts - ts[0]) / 100.0)) < 1e-9),
                        "without logging offsets every timestamp sits on the 100 ms tick grid")
        dt_off = np.diff(off["timestamp"].to_numpy(float))
        self.assertEqual(len(ts), len(off))
        self.assertEqual(int(np.sum(np.diff(ts) > 150)), int(np.sum(np.round(dt_off / 100.0) > 1)),
                         "missing ticks (gaps) not preserved")

    def test_empirical_offsets_heavy_tailed(self):
        df, _ = _generate(1)
        dt = np.diff(df["timestamp"].to_numpy(float))
        self.assertTrue(np.all(dt > 0), "timestamps must be strictly increasing")
        core = dt[(dt > 50) & (dt < 150)]
        self.assertTrue(96 <= np.percentile(core, 25) <= 99 and 101 <= np.percentile(core, 75) <= 104)
        self.assertGreater(np.mean(dt < 40), 0.001, "no catch-up / backlog samples")
        self.assertGreater(np.mean((dt > 150) & (dt < 1000)), 0.001, "no late samples")

    def test_empirical_offsets_shared_between_sensors(self):
        from core.joint_template import JointBank, empirical_log_offsets
        bank = JointBank(os.path.join(CFG_DIR, "joint_bank_arm.npz"))
        off = empirical_log_offsets(bank, 20000, SEED)
        late = {s: off[s] > 50 for s in bank.sensors}
        a, b = late["sensor_1"], late["sensor_3"]
        both = np.mean(a & b)
        self.assertGreater(both, 3 * a.mean() * b.mean(), "late deliveries should coincide across sensors")

    def test_real_dropped_ticks(self):
        """Ticks the real logger dropped (same real blocks as the offsets) are removed: rate in the
        real in-block range (0.3-0.7 %), and log_drops=False keeps every row."""
        df, gen = _generate(1)
        full, _ = _generate(1, log_drops=False)
        rate = 1 - len(df) / len(full)
        self.assertTrue(0.001 < rate < 0.015, f"drop rate {100 * rate:.2f} %")
        self.assertEqual(len(df), int(gen.joint_keep.sum()))

    def test_step_angle_uncorrelated_with_dt(self):
        df, _ = _generate(1)
        x = df[list(Q_COLS)].to_numpy(float)
        w = np.sqrt(np.clip(1 - (x ** 2).sum(1), 0, None))
        q = np.c_[w, x]
        ang = np.degrees(2 * np.arccos(np.clip(np.abs((q[1:] * q[:-1]).sum(1)), 0, 1)))
        dt = np.diff(df["timestamp"].to_numpy(float))
        steady = (dt > 50) & (dt < 150) & (ang > 1.5)
        self.assertGreater(steady.sum(), 200)
        self.assertLess(abs(np.corrcoef(dt[steady], ang[steady])[0, 1]), 0.15)

    def test_no_frozen_quaternion_while_moving(self):
        """Real XDK: the fused quaternion repeats only while truly static (~0 % above 0.5 deg/s)."""
        df, _ = _generate(1)
        x = df[list(Q_COLS)].to_numpy(float)
        same = np.all(x[1:] == x[:-1], axis=1)
        w = np.sqrt(np.clip(1 - (x ** 2).sum(1), 0, None))
        q = np.c_[w, x]
        ang = np.degrees(2 * np.arccos(np.clip(np.abs((q[1:] * q[:-1]).sum(1)), 0, 1)))
        moving = np.r_[ang[1:], 0] > 2.0          # the following step clearly rotates
        self.assertLess(same[moving].mean(), 0.01)


class TestFlagOff(unittest.TestCase):
    def test_non_motion_columns_unchanged_and_flag_off_is_noop(self):
        on, gen_on = _generate(2, joint=True)
        off, gen_off = _generate(2, joint=False)
        self.assertIsNone(gen_off.joint_schedule)
        keep = gen_on.joint_keep                      # rows the real logger dropped are removed
        self.assertEqual(len(on), int(keep.sum()))
        motion = set(Q_COLS) | set(A_COLS) | set(M_COLS) | {"mag_res", "timestamp"}   # timestamp: see TestClock
        for c in on.columns:
            if c not in motion:
                np.testing.assert_array_equal(on[c].to_numpy(), off[c].to_numpy()[keep], err_msg=c)
        # flag off == config without any "motion" key
        s = _scenario(2, joint=False)
        s.pop("motion")
        bare = SyntheticXDKGenerator(s, seed=SEED).generate()
        self.assertTrue(bare.equals(off))


if __name__ == "__main__":
    unittest.main()
