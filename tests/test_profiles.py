"""
Sensor profiles: the XDK profile must give exactly what the CLI path gives, and the gate-as-filter
loop must try seeds in order and return the right attempt.

The generate/validate equivalence test runs the six-sensor engine and the full gate on 10-min
outputs (about a minute).
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.profiles import registry
from core.profiles.base import FAILED, PASSED, GateCheck, GateReport, SensorProfile
from core.profiles.xdk import XDKProfile
from core.joint_template import JointBank
from validation.physics_gate import check_physics_gate, load_thresholds

DUR, SEED = 600.0, 7


class TestRegistry(unittest.TestCase):
    def test_xdk_registered(self):
        self.assertEqual([p.name for p in registry.all_profiles()], ["xdk"])
        self.assertIsInstance(registry.get("xdk"), XDKProfile)

    def test_scenarios_and_durations(self):
        p = XDKProfile()
        sc = p.scenarios()
        self.assertEqual(sc[0], "robot_arm_6")
        self.assertIn("robot_arm", sc)
        self.assertEqual(p.sensors("robot_arm_6"), [f"sensor_{k}" for k in range(1, 7)])
        bank = JointBank(os.path.join(ROOT, "configs", "robot_arm_6", "joint_bank_arm6.npz"))
        self.assertEqual(p.max_duration_s("robot_arm_6"), bank.recording_s)
        self.assertAlmostEqual(p.max_duration_s("robot_arm_6") / 60, 94.9, places=1)
        self.assertEqual(p.max_attempts("robot_arm_6"), 5)


class TestXDKMatchesCLI(unittest.TestCase):
    """XDKProfile.generate + validate == cli/main.py per sensor + the physics gate (regression path)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.p = XDKProfile()
        cls.paths = cls.p.generate("robot_arm_6", DUR, SEED, os.path.join(cls.tmp.name, "profile"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_generate_identical_to_cli(self):
        cfg_dir = os.path.join(ROOT, "configs", "robot_arm_6")
        for path in self.paths:
            s = os.path.basename(path).split("_seed")[0]
            out = os.path.join(self.tmp.name, f"cli_{s}.csv")
            subprocess.run(["python3", "cli/main.py", "--config", os.path.join(cfg_dir, f"{s}_joint.json"), "--output",
                            out, "--duration", str(DUR), "--seed", str(SEED), "--no-physics-gate"],
                           cwd=ROOT, check=True, capture_output=True)
            self.assertEqual(open(path, "rb").read(), open(out, "rb").read(), s)

    def test_validate_identical_to_cli_gate(self):
        bank = JointBank(os.path.join(ROOT, "configs", "robot_arm_6", "joint_bank_arm6.npz"))
        syn = {os.path.basename(p).split("_seed")[0]: p for p in self.paths}
        real = {s: os.path.join(ROOT, "data", "arm6", "original", f"{s}.csv.gz") for s in syn}   # repo copies
        thr = load_thresholds(os.path.join(ROOT, "configs", "robot_arm_6", "gate_thresholds.json"))
        ref = check_physics_gate(syn, real, bank.period, cross_sensor=True, thresholds=thr).to_dict()
        got = self.p.validate("robot_arm_6", self.paths)
        self.assertEqual(got.to_dict()["checks"], json.loads(json.dumps(ref["checks"])))
        self.assertEqual(got.passed, ref["passed"])
        # the bank's own real files, when present, give the same gate (the repo copies are identical)
        if all(os.path.exists(bank.real_path(s)) for s in syn):
            ref2 = check_physics_gate(syn, {s: bank.real_path(s) for s in syn}, bank.period, True, thr).to_dict()
            self.assertEqual(ref2["checks"], ref["checks"])


class _Fake(SensorProfile):
    """Passes on the seeds in `good`; fails with `n_fail[seed]` blocking checks otherwise."""
    name, label = "fake", "Fake"

    def __init__(self, good=(), n_fail=None):
        self.good, self.n_fail, self.seen = set(good), n_fail or {}, []

    def scenarios(self):
        return ["s"]

    def max_duration_s(self, scenario):
        return None

    def max_attempts(self, scenario):
        return 5

    def generate(self, scenario, duration_s, seed, out_dir, progress=None):
        self.seen.append(seed)
        return [os.path.join(out_dir, f"x_seed{seed}.csv")]

    def validate(self, scenario, csv_paths):
        seed = int(csv_paths[0].split("seed")[-1][:-4])
        if seed in self.good:
            return GateReport(PASSED, [GateCheck("c", "x", 0.0, "-", True)])
        return GateReport(FAILED, [GateCheck(f"c{i}", "x", 1.0, "-", False) for i in range(self.n_fail.get(seed, 1))])


class TestGateAsFilter(unittest.TestCase):
    def test_stops_at_first_pass(self):
        with tempfile.TemporaryDirectory() as d:
            p = _Fake(good={44})
            run = p.generate_validated("s", 60, 42, d)
        self.assertEqual(p.seen, [42, 43, 44])
        self.assertEqual((run.chosen.number, run.chosen.seed, run.chosen.report.passed), (3, 44, True))

    def test_all_fail_returns_fewest_failures(self):
        with tempfile.TemporaryDirectory() as d:
            p = _Fake(n_fail={42: 3, 43: 1, 44: 2, 45: 1, 46: 4})
            run = p.generate_validated("s", 60, 42, d)
        self.assertEqual(p.seen, [42, 43, 44, 45, 46])
        self.assertEqual((run.chosen.seed, run.chosen.report.passed), (43, False))
        self.assertIn("FAILED", p.readme(run))


if __name__ == "__main__":
    unittest.main()
