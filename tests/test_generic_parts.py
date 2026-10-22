"""
Pre-sales path: one generic part per quantity, a device from the columns a client logs, raw counts
and the data profile.
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
from core.devices import Part, columns_spec, device_from_columns, generic_parts, parts_measuring  # noqa: E402
from core.output import profile_range, run  # noqa: E402
from core.quantities import CATALOG  # noqa: E402
from core.quantities.measurement import ParamError  # noqa: E402

REQUIRED = ("range", "resolution", "noise_sd", "t90_s", "odr_hz")


class TestGenericParts(unittest.TestCase):
    def test_one_generic_per_quantity(self):
        g = generic_parts()
        self.assertEqual(sorted(g), sorted(CATALOG))
        for q, slugs in g.items():
            self.assertEqual(len(slugs), 1, f"{q}: {slugs}")

    def test_generic_parts_are_valid_assumptions(self):
        for q, (slug,) in generic_parts().items():
            with self.subTest(slug):
                p = Part.load(slug)
                self.assertEqual(p.quantities(), [q])
                self.assertTrue(p.cls)
                m = p.models()[q]
                params = p.measures[q]
                for k in REQUIRED:
                    self.assertTrue(k in params or (k == "range" and m.range) or (k == "resolution" and m.resolution),
                                    f"{slug}: {k} missing")
                self.assertIsNotNone(m.odr_hz, slug)
                for k, prm in params.items():
                    self.assertTrue(prm["source"].startswith("ASSUMPTION"), f"{slug}.{k}")

    def test_generic_is_not_better_than_a_datasheet_part(self):
        """Resolution, noise, error bound and t90 of a generic part are no better than the best
        datasheet part in this repo for the same quantity."""
        for q, (slug,) in generic_parts().items():
            others = parts_measuring(q)
            if not others:
                continue
            g = Part.load(slug).models()[q]
            ms = [Part.load(s).models()[q] for s in others]
            with self.subTest(q):
                self.assertGreaterEqual(g.resolution, min(m.resolution for m in ms) - 1e-12)
                self.assertGreaterEqual(g.noise_sd, min(m.noise_sd for m in ms) - 1e-12)
                for rising in (True, False):
                    self.assertGreaterEqual(g.t90(rising), min(m.t90(rising) for m in ms))
                lo = max(float(np.max(m.bounds[0])) for m in ms + [g])
                hi = min(float(np.min(m.bounds[1])) for m in ms + [g])
                x = np.linspace(lo, hi, 11)
                best = np.min([m.error_bound(x) for m in ms], axis=0)
                self.assertTrue((g.error_bound(x) >= best - 1e-9).all())

    def test_every_generic_part_is_in_the_presales_table(self):
        with open(os.path.join(ROOT, "docs", "PRESALES.md")) as fh:
            text = fh.read()
        for q, (slug,) in generic_parts().items():
            self.assertIn(f"| `{q}` | ", text)
            self.assertIn(f"`{slug}`", text)

    def test_a_generic_part_has_no_datasheet_values(self):
        d = {"name": "x", "datasheet": "none", "generic_for": "air.co2_ppm", "class": "x",
             "measures": [{"quantity": "air.co2_ppm", "params": {
                 "range": {"value": [0, 5000], "unit": "ppm", "source": "datasheet X p.1"},
                 "resolution": {"value": 1, "unit": "ppm", "source": "ASSUMPTION: x"}}}]}
        with self.assertRaises(ParamError):
            Part.from_dict("x", d)


class TestDeviceFromColumns(unittest.TestCase):
    def test_one_part_for_several_columns_and_unchosen_columns_are_not_logged(self):
        spec = columns_spec({"temperature_c": "bosch_bme280", "air.humidity_rh": "bosch_bme280", "co2": "generic"})
        self.assertEqual([p["part"] for p in spec["parts"]], ["bosch_bme280", "generic_co2_ndir"])
        self.assertEqual(spec["parts"][0]["log"], ["air.temperature_c", "air.humidity_rh"])
        self.assertNotIn("log", spec["parts"][1])

    def test_temperature_via_bme280_only(self):
        dev = device_from_columns({"air.temperature_c": "bosch_bme280"}, name="Temp only", sample_interval_s=60)
        self.assertEqual(dev.columns(), ["timestamp", "device_id", "temperature_c"])
        self.assertEqual(dev.used(), {"air.temperature_c"})
        with tempfile.TemporaryDirectory() as tmp:          # the fridge has no pressure: not needed, not measured
            r = run({"name": "t", "world": "fridge", "duration": "2h", "seed": 1, "events": [],
                     "devices": [{"device": dev, "mount": "fixed"}]}, out_dir=tmp)[0]
            self.assertTrue(r["passed"])
            self.assertEqual(list(pd.read_csv(r["csv"]).columns), ["timestamp", "device_id", "temperature_c"])

    def test_a_part_that_does_not_measure_the_column(self):
        with self.assertRaises(ParamError):
            columns_spec({"co2_ppm": "bosch_bme280"})


class TestRawCounts(unittest.TestCase):
    def test_raw_counts_are_integers_and_the_gate_converts_back(self):
        dev = device_from_columns({"air.temperature_c": "bosch_bme280", "body.accel_g": "generic"}, name="Raw",
                                  sample_interval_s=1, raw_counts=True)
        self.assertEqual(dev.output_columns()[2:], ["temperature_c_counts", "accel_x_g_counts", "accel_y_g_counts",
                                                    "accel_z_g_counts"])
        self.assertEqual(dev.column_bits()["temperature_c_counts"], 14)      # (85 + 40) / 0.01 + 1 codes
        self.assertEqual(dev.column_bits()["accel_x_g_counts"], 13)          # 12 bit over ±8 g, both ends included
        with tempfile.TemporaryDirectory() as tmp:
            r = run({"name": "t", "world": "static_shelf", "duration": "1h", "seed": 3, "events": [],
                     "devices": [{"device": dev, "mount": "fixed"}]}, out_dir=tmp)[0]
            d = pd.read_csv(r["csv"])
            for c in dev.output_columns()[2:]:
                self.assertTrue(pd.api.types.is_integer_dtype(d[c]), c)
            self.assertLess(d[["accel_x_g_counts", "accel_y_g_counts"]].min().min(), 0)   # signed, no offset
            self.assertTrue(r["passed"])
            man = json.load(open(r["manifest"]))
            self.assertEqual(man["device"]["reading_columns"]["temperature_c_counts"]["bits"], 14)
            self.assertTrue(man["device"]["reading_columns"]["accel_x_g_counts"]["generic"])
            self.assertEqual(man["device"]["generic_columns"], ["accel_x_g_counts", "accel_y_g_counts", "accel_z_g_counts"])


class TestProfile(unittest.TestCase):
    def test_profile_and_range(self):
        dev = device_from_columns({"air.temperature_c": "generic", "air.co2_ppm": "generic"}, name="Room",
                                  sample_interval_s=10)
        profs = []
        with tempfile.TemporaryDirectory() as tmp:
            for seed in (1, 2):
                r = run({"name": "t", "world": "static_shelf", "duration": "2h", "seed": seed, "events": [],
                         "devices": [{"device": dev, "mount": "fixed"}]}, out_dir=tmp)[0]
                profs.append(json.load(open(r["profile"])))
        p = profs[0]
        self.assertIn("NOT the Bitteiler algorithm", p["note"])
        t = p["columns"]["temperature_c"]
        self.assertEqual(t["bits"], 11)                                      # 125 °C / 0.1 + 1 codes
        self.assertAlmostEqual(t["noise_over_resolution"], 0.5)
        self.assertTrue(0 <= t["repeat_fraction"] <= 1)
        self.assertGreater(t["csv_ratio"], 1)
        self.assertEqual(t["bin_type"], "int16")
        rng = profile_range(profs)
        self.assertEqual(rng["seeds"], [1, 2])
        lo, hi = rng["columns"]["co2_ppm"]["csv_ratio"]
        self.assertLessEqual(lo, hi)


if __name__ == "__main__":
    unittest.main()
