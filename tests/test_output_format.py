"""
output_format: a device can write its columns with the vendor's names and units (°C -> °F, A -> mA,
°C/min -> °F/min without an offset); every entry is {value, unit, source}; the gate reads the
vendor's names and units, turns the values back and checks as usual.
"""
import copy
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.devices import Device
from core.output import run
from core.quantities.measurement import ParamError
from core.quantities.units import UnitError, output_transform
from validation.auto_gate import check_device

A = lambda name, unit: {"value": name, "unit": unit, "source": "ASSUMPTION: test"}


class TestTransform(unittest.TestCase):
    def test_units(self):
        self.assertEqual(output_transform("°C", "°F"), (1.8, 32.0))
        self.assertEqual(output_transform("°C", "K"), (1.0, 273.15))
        self.assertEqual(output_transform("A", "mA"), (1000.0, 0.0))
        self.assertEqual(output_transform("hPa", "Pa"), (100.0, 0.0))
        self.assertEqual(output_transform("°C/min", "°F/min"), (1.8, 0.0))       # a rate: no offset
        self.assertEqual(output_transform("°C", "°F", absolute=False), (1.8, 0.0))
        with self.assertRaises(UnitError):
            output_transform("°C", "ppm")
        with self.assertRaises(UnitError):
            output_transform("°C/min", "°F/h")


class TestDevice(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "configs", "devices", "rack_monitor.yaml")) as fh:
            self.d = yaml.safe_load(fh)

    def test_columns_renamed(self):
        dev = Device.load("fridge_logger_us")
        self.assertEqual(dev.output_columns(), ["timestamp", "device_id", "temp_f", "compressor_ma",
                                                "signal_strength_dbm", "alarm_hi"])
        self.assertEqual(dev.columns()[2], "temperature_c")                     # the logic still uses its own names

    def test_bad_formats_refused(self):
        cases = {"unknown column": {"pressure_hpa": A("p", "Pa")},
                 "no source": {"temperature_c": {"value": "t", "unit": "°F"}},
                 "impossible unit": {"temperature_c": A("t", "ppm")},
                 "duplicate name": {"temperature_c": A("device_id", "°F")}}
        for name, fmt in cases.items():
            with self.subTest(name), self.assertRaises(ParamError):
                Device.from_dict(dict(copy.deepcopy(self.d), output_format=fmt))


class TestRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        with open(os.path.join(ROOT, "configs", "devices", "rack_monitor.yaml")) as fh:
            d = yaml.safe_load(fh)
        d["name"] = "Rack Monitor US"
        d["output_format"] = {"temperature_c": A("temp_f", "°F"),
                              "temperature_rate_c_per_min": A("rate_f_per_min", "°F/min"),
                              "temperature_rising_fast": A("rising_fast", "-")}
        cls.rack = run("server_room_ac_failure", seed=44, out_dir=cls.dir,
                       devices=[{"device": Device.from_dict(d), "mount": "fixed"}])[0]
        cls.fridge = run("fridge_compressor_failure", seed=42, out_dir=cls.dir,
                         devices=[{"device": "fridge_logger_us", "mount": "fixed"}])[0]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir)

    def test_written_in_vendor_units_and_passes(self):
        for r in (self.rack, self.fridge):
            self.assertTrue(r["passed"])
        f = pd.read_csv(self.fridge["csv"])
        c = (f["temp_f"] - 32) / 1.8
        self.assertTrue(np.allclose(c / 0.0625, np.round(c / 0.0625), atol=1e-6))      # on the probe's °C grid
        self.assertTrue((f["compressor_ma"] % 10 == 0).all())                             # 10 mA = the 0.01 A step
        r = pd.read_csv(self.rack["csv"])
        self.assertIn("rate_f_per_min", r.columns)
        self.assertGreater(r["rate_f_per_min"].max(), 0.25 * 1.8)                         # the AC failure, in °F/min
        self.assertEqual(r["rising_fast"].max(), 1)

    def test_gate_checks_in_vendor_units(self):
        def tampered(fn):
            d = tempfile.mkdtemp()
            try:
                df = fn(pd.read_csv(self.fridge["csv"]))
                p = os.path.join(d, "x.csv")
                df.to_csv(p, index=False)
                return check_device(p, self.fridge["labels"], self.fridge["manifest"])
            finally:
                shutil.rmtree(d)
        g = tampered(lambda df: df.assign(temp_f=df["temp_f"] + 0.05))
        self.assertIn("resolution:temperature_c", g["failed"])
        g = tampered(lambda df: df.assign(alarm_hi=1 - df["alarm_hi"]))
        self.assertIn("threshold_alarm:temperature_alarm_high", g["failed"])
        g = tampered(lambda df: df.rename(columns={"temp_f": "temperature_c"}))
        self.assertIn("columns:*", g["failed"])


if __name__ == "__main__":
    unittest.main()
