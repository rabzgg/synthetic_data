"""
Gas detector generator and rule gate: the specs carry exactly the datasheet values, the generator is
deterministic, quantisation/clipping come last, the 5-seed set covers every required event, and the
gate fails on each kind of broken file while accepting an announced connection gap.
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
from core.gas_detector import GasDetectorEngine, _v, load_device, quantize_clip
from validation.gas_gate import check_gas_file, inventory

CONFIGS = os.path.join(ROOT, "configs")
SHIFT = 28800.0
DEVICES = ["blackline_g7c", "blackline_g7x_bridge", "blackline_g8", "msa_altair_io4", "msa_altair_io6"]


def failed(rep):
    return sorted({c.name for c in rep.checks if not c.passed and not c.informational})


def gen(device, assumptions=None, seed=42, forced=None):
    spec, A = load_device(device, CONFIGS)
    eng = GasDetectorEngine(spec, assumptions or A)
    return eng, eng.generate(SHIFT, seed, forced), spec, assumptions or A


class TestSpecs(unittest.TestCase):
    """The spec files hold exactly the datasheet numbers: (min, max, resolution) and battery hours."""
    BRIEF = {
        "msa_altair_io4": {"lel": (0, 100, 1), "o2": (0, 30, 0.1), "co": (0, 1999, 1), "h2s": (0, 199, 1)},
        "msa_altair_io6": {"lel": (0, 100, 1), "o2": (0, 30, 0.1), "co": (0, 1999, 1), "h2s": (0, 199, 1),
                           "voc": (0, 4000, 0.1)},
        "blackline_g7c": {"lel": (0, 100, 1), "o2": (0, 25, 0.1), "co": (0, 500, 1), "h2s": (0, 100, 0.1)},
        "blackline_g7x_bridge": {"lel": (0, 100, 1), "o2": (0, 25, 0.1), "co": (0, 500, 1), "h2s": (0, 100, 0.1)},
        "blackline_g8": {"lel": (0, 100, 1), "o2": (0, 25, 0.1), "co": (0, 500, 1), "h2s": (0, 100, 0.1)},
    }
    BATTERY_H = {"msa_altair_io4": 17, "msa_altair_io6": 17, "blackline_g7c": 18, "blackline_g7x_bridge": 18,
                 "blackline_g8": 18}

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
            self.assertEqual(spec["battery_runtime_h"]["value"], self.BATTERY_H[dev], dev)
        io6, _ = load_device("msa_altair_io6", CONFIGS)
        self.assertIn("ASSUMPTION: same sensors as io4", io6["channels"]["co"]["assumption"])
        self.assertEqual(io6["channels"]["voc"]["resolution"]["source"],
                         "ASSUMPTION: borrowed from Blackline PID (G7c R28); io6 PID table not found")
        self.assertIn("ASSUMPTION", io6["battery_runtime_h"]["assumption"])
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
        self.assertGreater(len(items), 15)
        for k, e in items:
            self.assertEqual(e["status"], "ASSUMPTION", k)
            self.assertTrue(e["reason"], k)


class TestGenerator(unittest.TestCase):
    def test_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            for i in (1, 2):
                eng, df, _, _ = gen("blackline_g8")
                eng.write_csv(df, os.path.join(d, f"{i}.csv"))
            with open(os.path.join(d, "1.csv"), "rb") as a, open(os.path.join(d, "2.csv"), "rb") as b:
                self.assertEqual(a.read(), b.read())

    def test_quantize_then_clip(self):
        q = quantize_clip([-0.04, 0.05, 12.34, 140.6], 0.1, 0, 100)
        self.assertEqual(q.tolist(), [0.0, 0.0, 12.3, 100.0])
        self.assertFalse(np.signbit(q).any())

    def test_battery_follows_datasheet_runtime(self):
        _, df, spec, _ = gen("msa_altair_io4")
        t = (pd.to_datetime(df["timestamp"]) - pd.to_datetime(df["timestamp"].iloc[0])).dt.total_seconds().to_numpy()
        self.assertTrue((np.diff(df["battery_pct"]) <= 0).all())
        np.testing.assert_array_equal(df["battery_pct"], np.floor(100 - 100 * t / (17 * 3600)).astype(int))

    def test_coverage_of_seed_set(self):
        """Across seeds 42-46: STEL alarm, TWA alarm and over-range on every device; VOC and pump fault on
        io6; SOS on G8."""
        for dev in DEVICES:
            inv = [inventory(gen(dev, seed=s)[1]) for s in range(42, 47)]
            self.assertTrue(any(i["stel_alarm_samples"] for i in inv), dev)
            self.assertTrue(any(i["twa_alarm_samples"] for i in inv), dev)
            self.assertTrue(any(i["over_range_samples"] for i in inv), dev)
            if dev == "msa_altair_io6":
                self.assertTrue(any(i["voc_exposures"] for i in inv))
                self.assertTrue(any(i["pump_faults"] for i in inv))
            if dev == "blackline_g8":
                self.assertTrue(all(i["sos"] == 1 for i in inv))
            if dev == "blackline_g7x_bridge":
                self.assertTrue(all(i["satellite_periods"] >= 1 for i in inv))

    def test_stel_alarm_fires_with_cause(self):
        _, A = load_device("blackline_g7c", CONFIGS)
        A = copy.deepcopy(A)
        A["exposure"]["gases"]["value"] = ["h2s"]
        A["exposure"]["peak"]["value"]["h2s"] = [40, 40]
        A["exposure"]["plateau_s"]["value"] = [900, 900]
        eng, df, spec, _ = gen("blackline_g7c", A, forced=[])
        self.assertGreater(df["h2s_alarm_stel"].sum(), 0)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.csv")
            eng.write_csv(df, p)
            self.assertEqual(failed(check_gas_file(p, "blackline_g7c", None, spec, A)), [])


class TestGateCatchesFaults(unittest.TestCase):
    """Each corruption must fail the check it targets; the clean file and an announced gap must pass."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.files = {}
        for dev in ("blackline_g7c", "msa_altair_io6"):
            eng, df, _, _ = gen(dev, seed=46)
            p = os.path.join(cls.tmp.name, f"{dev}.csv")
            eng.write_csv(df, p)
            cls.files[dev] = (p, df)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def broken(self, edit, dev="blackline_g7c"):
        d = pd.read_csv(self.files[dev][0], dtype=str)
        out = edit(d)                                        # an edit changes d, or returns a new frame
        d = d if out is None else out
        p = os.path.join(self.tmp.name, "broken.csv")
        d.to_csv(p, index=False)
        return failed(check_gas_file(p, dev, 46))

    def quiet_row(self, dev="blackline_g7c"):
        """A row well inside the shift, away from events and gaps."""
        df = self.files[dev][1]
        ok = (df["event"] == "none") & (df["gap_before_s"] == 0) & (df.index > 1500)
        return int(np.where(ok)[0][0])

    def test_clean_passes(self):
        for dev, (p, _) in self.files.items():
            self.assertEqual(failed(check_gas_file(p, dev, 46)), [], dev)

    def test_unannounced_missing_row_fails(self):
        i = self.quiet_row()
        self.assertIn("timestamps", self.broken(lambda d: d.drop(index=i)))

    def test_announced_gap_passes_timestamps(self):
        i = self.quiet_row()

        def e(d):
            d = d.drop(index=range(i, i + 6))
            d.loc[i + 6, "gap_before_s"] = "60"
            return d
        f = self.broken(e)
        self.assertNotIn("timestamps", f)
        self.assertNotIn("stel_formula", f)
        self.assertNotIn("twa_formula", f)

    def test_gap_announced_with_wrong_length_fails(self):
        i = self.quiet_row()

        def e(d):
            d = d.drop(index=range(i, i + 6))
            d.loc[i + 6, "gap_before_s"] = "50"
            return d
        self.assertIn("timestamps", self.broken(e))

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

    def test_stel_wrong(self):
        i = self.quiet_row()

        def e(d):
            d.loc[i, "co_stel_ppm"] = str(int(d.loc[i, "co_stel_ppm"]) + 3)
        self.assertIn("stel_formula", self.broken(e))

    def test_twa_wrong(self):
        i = self.quiet_row()

        def e(d):
            d.loc[i, "h2s_twa_ppm"] = f"{float(d.loc[i, 'h2s_twa_ppm']) + 0.3:.1f}"
        self.assertIn("twa_formula", self.broken(e))

    def test_bump_not_simultaneous(self):
        s = int(np.where(self.files["blackline_g7c"][1]["device_mode"] == "bump_test")[0][0])

        def e(d):
            d.loc[s, "co_ppm"] = d.loc[s - 1, "co_ppm"]            # CO starts one sample late
        self.assertIn("bump_simultaneous", self.broken(e))

    def test_alarm_without_cause(self):
        i = int(np.where(self.files["blackline_g7c"][1]["lel_alarm_low"] == 1)[0][0])
        self.assertIn("alarm_cause", self.broken(lambda d: d.__setitem__("event", d["event"].where(d.index != i, "none"))))

    def test_battery_wrong(self):
        i = self.quiet_row()

        def e(d):
            d.loc[i, "battery_pct"] = str(int(d.loc[i, "battery_pct"]) + 1)
        self.assertIn("battery", self.broken(e))

    def test_pump_alarm_inconsistent(self):
        i = self.quiet_row("msa_altair_io6")

        def e(d):
            d.loc[i, "pump_alarm"] = "1"
        self.assertIn("pump", self.broken(e, "msa_altair_io6"))


if __name__ == "__main__":
    unittest.main()
