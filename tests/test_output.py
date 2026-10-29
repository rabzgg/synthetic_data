"""
Phase 5: a scenario runs end to end into files (CSV, labels, manifest, gate) for any device; the
gate passes on what the generator writes and fails on every kind of tampering; the same seed gives
the same bytes; the command line works. The full set (11 scenarios x 5 seeds) runs in
validation/run_all_scenarios.py; here a few short ones.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.output import run
from validation.auto_gate import check_device


class TestRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.res = {r["device"]: r for sc in ("worker_collapse", "fridge_compressor_failure", "water_tank_leak")
                   for r in run(sc, seed=42, out_dir=cls.dir)}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir)

    def test_files_and_gate(self):
        self.assertEqual(set(self.res), {"blackline_g7c", "bme280_sensor_board", "fridge_logger", "water_tank_monitor"})
        for slug, r in self.res.items():
            with self.subTest(slug):
                for k in ("csv", "labels", "manifest", "gate"):
                    self.assertTrue(os.path.exists(r[k]))
                self.assertTrue(r["passed"], json.load(open(r["gate"]))["failed"])
                df = pd.read_csv(r["csv"])
                self.assertFalse({"event", "gap_before_s"} & set(df.columns))         # clean export

    def test_manifest(self):
        m = json.load(open(self.res["fridge_logger"]["manifest"]))
        self.assertEqual(m["device"]["slug"], "fridge_logger")
        self.assertIn("generator_version", m)
        self.assertIn("motion", m["world"]["defaults_used"])                        # the short fridge world
        params = m["parts"][0]["quantities"]["air.temperature_c"]["parameters"]
        self.assertTrue(all(p["source"].startswith(("datasheet", "ASSUMPTION")) for p in params.values()))
        self.assertEqual(m["events"][0]["kind"], "compressor_failure")

    def test_collapse_in_the_csv(self):
        df = pd.read_csv(self.res["blackline_g7c"]["csv"])
        self.assertIn("alert", set(df["fall_state"]))
        self.assertIn("alert", set(df["no_motion_state"]))
        self.assertEqual(df["h2s_alarm_high"].max(), 1)
        lab = pd.read_csv(self.res["blackline_g7c"]["labels"])
        self.assertTrue({"fall_alert", "no_motion_alert", "collapse:no_motion"} <= set(lab["event"]))
        bme = pd.read_csv(self.res["bme280_sensor_board"]["csv"])
        self.assertEqual(list(bme.columns), ["timestamp", "device_id", "temperature_c", "humidity_rh", "pressure_hpa"])

    def test_gap_rows_missing(self):
        df = pd.read_csv(self.res["blackline_g7c"]["csv"])
        t = pd.to_datetime(df["timestamp"].str.replace("Z", ""))
        self.assertEqual(int((t.diff().dt.total_seconds() > 10).sum()), 1)          # the 70 s connection loss

    def tamper(self, slug, fn):
        r = self.res[slug]
        d = tempfile.mkdtemp()
        try:
            df = pd.read_csv(r["csv"])
            df = fn(df)
            p = os.path.join(d, "x.csv")
            df.to_csv(p, index=False)
            return check_device(p, r["labels"], r["manifest"])
        finally:
            shutil.rmtree(d)

    def test_gate_catches_tampering(self):
        def flip(col, row):
            def f(df):
                df.loc[row, col] = 1 - df.loc[row, col]
                return df
            return f

        def setv(col, row, val):
            def f(df):
                df[col] = df[col].astype(object)
                df.loc[row, col] = val
                return df
            return f
        cases = {
            "alarm flipped": ("blackline_g7c", flip("co_alarm_low", 500), "threshold_alarm"),
            "out of range": ("blackline_g7c", setv("co_ppm", 300, 900), "range"),
            "off the grid": ("blackline_g7c", setv("h2s_ppm", 300, 0.05), "resolution"),
            "row dropped": ("blackline_g7c", lambda df: df.drop(index=200).reset_index(drop=True), "timestamps"),
            "stel changed": ("blackline_g7c", setv("h2s_stel_ppm", 600, 9.9), "rolling_mean"),
            "twa changed": ("blackline_g7c", setv("co_twa_ppm", 600, 3), "cumulative_dose"),
            "battery changed": ("blackline_g7c", setv("battery_pct", 400, 3), "battery"),
            "bump mode missing": ("blackline_g7c", lambda df: df.assign(device_mode="normal"), "event_mode"),
            "no-motion alert hidden": ("blackline_g7c", lambda df: df.assign(no_motion_state="ok"), "stillness_timer"),
            "fall alert hidden": ("blackline_g7c", lambda df: df.assign(fall_state="ok"), "spike_then_still"),
            "signal jump": ("fridge_logger", setv("signal_strength_dbm", 100, -112), "signal"),
            "column renamed": ("fridge_logger", lambda df: df.rename(columns={"current_a": "amps"}), "columns"),
            "wrong id": ("fridge_logger", setv("device_id", 5, "OTHER-0001"), "device_id"),
            "level alarm flipped": ("water_tank_monitor", flip("level_alarm_low", 10), "threshold_alarm"),
        }
        for name, (slug, fn, check) in cases.items():
            with self.subTest(name):
                g = self.tamper(slug, fn)
                self.assertFalse(g["passed"], name)
                self.assertTrue(any(f.startswith(check + ":") for f in g["failed"]), g["failed"])

    def test_same_seed_same_bytes(self):
        d = tempfile.mkdtemp()
        try:
            r = run("fridge_compressor_failure", seed=42, out_dir=d)[0]
            self.assertEqual(open(r["csv"], "rb").read(), open(self.res["fridge_logger"]["csv"], "rb").read())
            r2 = run("fridge_compressor_failure", seed=43, out_dir=d)[0]
            self.assertNotEqual(open(r2["csv"], "rb").read(), open(r["csv"], "rb").read())
        finally:
            shutil.rmtree(d)


class TestCli(unittest.TestCase):
    def test_one_command(self):
        d = tempfile.mkdtemp()
        try:
            r = subprocess.run([sys.executable, "cli/generate.py", "--scenario", "field_irrigation", "--seed", "7",
                                "--out", d], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("gate PASSED", r.stdout)
            self.assertEqual(len(os.listdir(d)), 5)                  # csv, labels, manifest, gate, summary
        finally:
            shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
