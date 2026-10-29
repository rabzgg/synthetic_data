"""
Legacy path (core/generator.py via ui/legacy.py): real CSV -> fitted JSON -> synthetic CSV.
Text timestamps (ISO 8601) fit exactly as the same data with numeric millisecond timestamps, which is
what the fitter always read (pandas 2 and 3 both failed on text); sensor_1 runs end to end for 10 min;
text columns are left out and slow loggers are refused with a plain message.
"""
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "ui"))
import legacy  # noqa: E402
from core.generator import AutoFitter, fit_from_real_data  # noqa: E402


class TestLegacy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="legacy_test_")

    def test_text_timestamps_fit_as_numeric_milliseconds(self):
        real = pd.read_csv(legacy.EXAMPLE, nrows=3000)
        self.assertFalse(pd.api.types.is_numeric_dtype(real["timestamp"]))           # ISO text
        iso = os.path.join(self.tmp, "iso.csv")
        real.to_csv(iso, index=False)
        ms = real.copy()
        us = (pd.to_datetime(ms["timestamp"], utc=True) - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(1, "us")
        ms["timestamp"] = us.astype("int64") / 1000.0
        num = os.path.join(self.tmp, "ms.csv")
        ms.to_csv(num, index=False)
        self.assertEqual(json.dumps(fit_from_real_data(iso)), json.dumps(fit_from_real_data(num)))
        t = pd.Series([20000, 20100, 20200])
        self.assertIs(AutoFitter._timestamps_as_ms(t), t)                               # numeric: untouched

    def test_sensor_1_end_to_end_ten_minutes(self):
        with open(legacy.EXAMPLE, "rb") as fh:
            path, left_out = legacy.prepare(fh.read(), self.tmp)
        self.assertEqual(left_out, [])
        cfg = legacy.fit(path)
        self.assertEqual(cfg["frequency_hz"], 10)
        syn = legacy.generate(cfg, 10, 42)
        self.assertEqual(list(syn.columns), ["timestamp"] + list(cfg["columns"]))
        self.assertAlmostEqual(len(syn), 6000, delta=60)
        self.assertTrue(np.isfinite(syn.to_numpy(float)).all())
        t = legacy.minutes_from_start(syn["timestamp"])
        self.assertAlmostEqual(t[-1], 10, delta=0.1)
        self.assertTrue((np.diff(t) > 0).all())
        pd.testing.assert_frame_equal(syn, legacy.generate(cfg, 10, 42))                # same seed, same data
        base = legacy.base_name(legacy.EXAMPLE)
        self.assertEqual(base, "sensor_1")
        z = zipfile.ZipFile(io.BytesIO(legacy.zip_files(syn, cfg, base)))
        self.assertEqual(sorted(z.namelist()), ["sensor_1_config.json", "sensor_1_synthetic.csv"])
        self.assertEqual(legacy.base_name("Fridge log (May).CSV"), "Fridge_log_May")
        fig = legacy.plot(path, syn, list(cfg["columns"]))
        self.assertEqual(len(fig.axes), len(cfg["columns"]))
        self.assertEqual(set(legacy.engines(cfg)["engine"]) & {"constant_noise", "event_spike"}, set())  # plain names

    def test_text_columns_left_out_and_slow_loggers_refused(self):
        df = pd.DataFrame({"timestamp": pd.date_range("2026-01-05", periods=120, freq="60s").strftime("%Y-%m-%dT%H:%M:%SZ"),
                           "device_id": "FRIDGELOG-0001", "temperature_c": np.linspace(3, 7, 120)})
        path, left_out = legacy.prepare(df.to_csv(index=False).encode(), self.tmp)
        self.assertEqual(left_out, ["device_id"])
        with self.assertRaises(legacy.LegacyError) as e:
            legacy.fit(path)
        self.assertIn("one row every 60 s", str(e.exception))
        with self.assertRaises(legacy.LegacyError):
            legacy.prepare(b"a,b\n1,2\n", self.tmp)                                     # no timestamp


if __name__ == "__main__":
    unittest.main()
