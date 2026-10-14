"""
Gas detector generator and rule gate: the specs carry exactly the datasheet values of the brief,
the generator is deterministic, quantisation/clipping come last, and the gate fails on each kind
of broken file.
"""
import copy
import os
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.gas_detector import GasDetectorEngine, load_device, quantize_clip
from validation.gas_gate import check_gas_file

CONFIGS = os.path.join(ROOT, "configs")
SHIFT = 28800.0


def failed(rep):
    return sorted({c.name for c in rep.checks if not c.passed and not c.informational})


def gen(device, assumptions=None, seed=42, duration=SHIFT):
    spec, A = load_device(device, CONFIGS)
    eng = GasDetectorEngine(spec, assumptions or A)
    return eng, eng.generate(duration, seed), spec, assumptions or A


class TestSpecs(unittest.TestCase):
    """The spec files hold exactly the datasheet numbers of the brief: (min, max, resolution)."""
    BRIEF = {
        "msa_altair_io4": {"lel": (0, 100, 1), "o2": (0, 30, 0.1), "co": (0, 1999, 1), "h2s": (0, 199, 1)},
        "msa_altair_io6": {"lel": (0, 100, 1), "o2": (0, 30, 0.1), "co": (0, 1999, 1), "h2s": (0, 199, 1),
                           "voc": (0, 4000, 0.1)},
        "blackline_g7c": {"lel": (0, 100, 1), "o2": (0, 25, 0.1), "co": (0, 500, 1), "h2s": (0, 100, 0.1)},
        "blackline_g7x_bridge": {"lel": (0, 100, 1), "o2": (0, 25, 0.1), "co": (0, 500, 1), "h2s": (0, 100, 0.1)},
        "blackline_g8": {"lel": (0, 100, 1), "o2": (0, 25, 0.1), "co": (0, 500, 1), "h2s": (0, 100, 0.1)},
    }

    def test_values_and_sources(self):
        for dev, chans in self.BRIEF.items():
            spec, _ = load_device(dev, CONFIGS)
            self.assertEqual(set(spec["channels"]), set(chans), dev)
            for g, (lo, hi, res) in chans.items():
                ch = spec["channels"][g]
                self.assertEqual((ch["range_min"]["value"], ch["range_max"]["value"], ch["resolution"]["value"]),
                                 (lo, hi, res), f"{dev}/{g}")
                for k in ("range_min", "range_max", "resolution"):
                    self.assertTrue(ch[k]["source"] and ch[k]["unit"], f"{dev}/{g}/{k}")
        io6, _ = load_device("msa_altair_io6", CONFIGS)
        self.assertIn("ASSUMPTION: same sensors as io4", io6["channels"]["co"]["assumption"])
        g7x, _ = load_device("blackline_g7x_bridge", CONFIGS)
        self.assertEqual(g7x["gateway"]["max_devices_per_bridge"]["value"], 5)

    def test_assumptions_marked(self):
        _, A = load_device("blackline_g7c", CONFIGS)

        def leaves(node):
            for k, e in node.items():
                if k.startswith("_"):
                    continue
                if isinstance(e, dict) and "value" in e:
                    yield k, e
                elif isinstance(e, dict):
                    yield from leaves(e)
        items = list(leaves(A))
        self.assertGreater(len(items), 10)
        for k, e in items:
            self.assertEqual(e["status"], "ASSUMPTION", k)
            self.assertTrue(e["reason"], k)


class TestGenerator(unittest.TestCase):
    def test_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            for i in (1, 2):
                eng, df, _, _ = gen("blackline_g8")
                eng.write_csv(df, os.path.join(d, f"{i}.csv"))
            self.assertEqual(open(os.path.join(d, "1.csv"), "rb").read(), open(os.path.join(d, "2.csv"), "rb").read())

    def test_quantize_then_clip(self):
        q = quantize_clip([-0.04, 0.05, 12.34, 140.6], 0.1, 0, 100)
        self.assertEqual(q.tolist(), [0.0, 0.0, 12.3, 100.0])
        self.assertFalse(np.signbit(q).any())

    def test_over_range_is_clipped_and_flagged(self):
        _, A = load_device("blackline_g7c", CONFIGS)
        A = copy.deepcopy(A)
        A["exposure"]["gases"]["value"] = ["lel"]
        A["exposure"]["peak"]["value"]["lel"] = [150, 150]           # above the 100 %LEL range
        _, df, spec, _ = gen("blackline_g7c", A)
        self.assertEqual(df["lel_pct_lel"].max(), 100)
        self.assertGreater(df["lel_over_range"].sum(), 0)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.csv")
            GasDetectorEngine(spec, A).write_csv(df, p)
            self.assertEqual(failed(check_gas_file(p, "blackline_g7c", spec, A)), [])

    def test_stel_alarm_fires_with_cause(self):
        _, A = load_device("blackline_g7c", CONFIGS)
        A = copy.deepcopy(A)
        A["exposure"]["gases"]["value"] = ["h2s"]
        A["exposure"]["peak"]["value"]["h2s"] = [40, 40]
        A["exposure"]["plateau_s"]["value"] = [900, 900]
        _, df, spec, _ = gen("blackline_g7c", A)
        self.assertGreater(df["h2s_alarm_stel"].sum(), 0)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.csv")
            GasDetectorEngine(spec, A).write_csv(df, p)
            self.assertEqual(failed(check_gas_file(p, "blackline_g7c", spec, A)), [])


class TestGateCatchesFaults(unittest.TestCase):
    """Each corruption must fail exactly the check it targets (and the clean file must pass)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        eng, cls.df, _, _ = gen("blackline_g7c")
        cls.eng = eng
        cls.clean = os.path.join(cls.tmp.name, "clean.csv")
        eng.write_csv(cls.df, cls.clean)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def broken(self, edit):
        d = pd.read_csv(self.clean, dtype=str)
        edit(d)
        p = os.path.join(self.tmp.name, "broken.csv")
        d.to_csv(p, index=False)
        return failed(check_gas_file(p, "blackline_g7c"))

    def test_clean_passes(self):
        self.assertEqual(failed(check_gas_file(self.clean, "blackline_g7c")), [])

    def test_alarm_flag_flipped(self):
        def e(d):
            d.loc[500, "co_alarm_low"] = "1" if d.loc[500, "co_alarm_low"] == "0" else "0"
        self.assertIn("alarm_setpoints", self.broken(e))

    def test_value_off_resolution(self):
        def e(d):
            d.loc[700, "h2s_ppm"] = "0.05"
        self.assertIn("resolution", self.broken(e))

    def test_value_out_of_range(self):
        def e(d):
            d.loc[700, "o2_pct_vol"] = "25.5"
        self.assertIn("range", self.broken(e))

    def test_missing_row(self):
        def e(d):
            d.drop(index=1000, inplace=True)
        self.assertIn("timestamps", self.broken(e))

    def test_stel_wrong(self):
        def e(d):
            d.loc[900, "co_stel_ppm"] = str(int(d.loc[900, "co_stel_ppm"]) + 3)
        self.assertIn("stel_formula", self.broken(e))

    def test_bump_not_simultaneous(self):
        s = int(np.where(self.df["device_mode"] == "bump_test")[0][0])

        def e(d):
            d.loc[s, "co_ppm"] = d.loc[s - 1, "co_ppm"]            # CO starts one sample late
        self.assertIn("bump_simultaneous", self.broken(e))

    def test_alarm_without_cause(self):
        i = int(np.where(self.df["lel_alarm_low"] == 1)[0][0])

        def e(d):
            d.loc[i, "event"] = "none"
        self.assertIn("alarm_cause", self.broken(e))


if __name__ == "__main__":
    unittest.main()
