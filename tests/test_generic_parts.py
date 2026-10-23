"""
Pre-sales path: one generic part per quantity, a device from the columns a client logs, raw counts,
the data summary, and the noise that follows the sample rate.
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
from core.output import run  # noqa: E402
from core.quantities import CATALOG  # noqa: E402
from core.quantities.measurement import ParamError  # noqa: E402

REQUIRED = ("range", "resolution", "noise_density", "t90_s", "odr_hz")


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
                if all("noise_density" in Part.load(s).measures[q] for s in others):     # same bandwidth: compare densities
                    dens = lambda s: Part.load(s).models()[q].noise_sd / np.sqrt(Part.load(s).models()[q].bandwidth_hz)
                    self.assertGreaterEqual(dens(slug), min(dens(s) for s in others) - 1e-12)
                else:
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


class TestSummary(unittest.TestCase):
    def test_summary_file(self):
        dev = device_from_columns({"air.temperature_c": "generic", "air.co2_ppm": "generic"}, name="Room",
                                  sample_interval_s=10)
        with tempfile.TemporaryDirectory() as tmp:
            r = run({"name": "t", "world": "static_shelf", "duration": "2h", "seed": 1, "events": [],
                     "devices": [{"device": dev, "mount": "fixed"}]}, out_dir=tmp)[0]
            self.assertTrue(r["summary"].endswith("_summary.json"))
            p = json.load(open(r["summary"]))
            d = pd.read_csv(r["csv"])
        self.assertEqual(p["rows"], len(d))
        t = p["columns"]["temperature_c"]
        self.assertEqual(set(t), {"rows", "sample_rate_hz", "min", "max", "kind", "quantity", "unit", "part", "generic",
                                  "bits", "noise_over_resolution", "odr_hz", "bandwidth_hz"})
        self.assertEqual(t["sample_rate_hz"], 0.1)
        self.assertEqual(t["bits"], 11)                                      # 125 °C / 0.1 + 1 codes
        self.assertAlmostEqual(t["noise_over_resolution"], 0.5)
        self.assertEqual((t["min"], t["max"]), (d["temperature_c"].min(), d["temperature_c"].max()))
        self.assertTrue(t["generic"])
        self.assertEqual(t["odr_hz"], 1.0)                                   # 0.1 Hz clamped to the class's 1 Hz


class TestNoiseFollowsTheSampleRate(unittest.TestCase):
    def shelf(self, part, interval):
        dev = device_from_columns({"body.accel_g": part}, name="Shelf accel", sample_interval_s=interval)
        with tempfile.TemporaryDirectory() as tmp:
            r = run({"name": "shelf", "world": "static_shelf", "duration": "10min", "seed": 7, "events": [],
                     "devices": [{"device": dev, "mount": "fixed"}]}, out_dir=tmp)[0]
            self.assertTrue(r["passed"])
            d = pd.read_csv(r["csv"])
            man = json.load(open(r["manifest"]))
        rms = float(np.mean([d[c].std() for c in ("accel_x_g", "accel_y_g", "accel_z_g")]))
        return dev.reading_models()["accel_x_g"], rms, man["parts"][0]["quantities"]["body.accel_g"]["rate"]

    def test_generic_accelerometer_100_vs_25_hz(self):
        m100, rms100, rate100 = self.shelf("generic", 0.01)
        m25, rms25, rate25 = self.shelf("generic", 0.04)
        self.assertEqual((m100.odr_hz, m100.bandwidth_hz, m25.odr_hz, m25.bandwidth_hz), (100, 50, 25, 12.5))
        self.assertAlmostEqual(m100.noise_sd / m25.noise_sd, 2.0)
        self.assertAlmostEqual(rms100 / rms25, 2.0, delta=0.3)              # 15 %; quantisation (3.9 mg) included
        self.assertIn("follows the sample rate 25 Hz", rate25["odr_source"])
        self.assertIn("bandwidth = ODR / 2", rate25["bandwidth_source"])

    def test_datasheet_settings_and_pins(self):
        dev = device_from_columns({"body.accel_g": "bosch_bma280"}, name="A", sample_interval_s=0.04)
        self.assertEqual(dev.reading_models()["accel_x_g"].odr_hz, 31.25)       # the first setting >= 25 Hz
        pinned = device_from_columns({"body.accel_g": "generic"}, name="B", sample_interval_s=0.04,
                                     overrides={"body.accel_g": {"odr_hz": {"value": 100, "unit": "Hz"}}})
        self.assertEqual(pinned.reading_models()["accel_x_g"].odr_hz, 100)
        from core.devices import Device
        for interval, odr, bw in ((1, 100, 32), (0.04, 100, 32), (0.006, 200, 64), (0.002, 1000, 116), (0.0005, 2000, 523)):
            m = device_from_columns({"body.gyro_dps": "bosch_bmg160"}, name="G",
                                    sample_interval_s=interval).reading_models()["gyro_x_dps"]
            self.assertEqual((m.odr_hz, m.bandwidth_hz), (odr, bw))            # register 0x10, the wider bandwidth
            self.assertAlmostEqual(m.noise_sd, 0.014 * np.sqrt(bw))
        mag = device_from_columns({"body.mag_ut": "bosch_bmm150"}, name="M", sample_interval_s=0.04)
        self.assertEqual(mag.reading_models()["mag_x_ut"].odr_hz, 25)          # Table 17 p.27
        g7c = Device.load("blackline_g7c")                                     # log: false keeps its own rate
        self.assertEqual([m.odr_hz for u, q, m in g7c.models() if q == "body.accel_g"], [2000])


if __name__ == "__main__":
    unittest.main()
