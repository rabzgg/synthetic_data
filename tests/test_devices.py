"""
Parts and devices: every part file loads with a source on every value; the gas presets carry the
same numbers as configs/gas (spec.json + assumptions.json) and give the same columns as the old CSVs
(minus gap_before_s and event, which move to the labels file); devices a user assembles are named,
versioned and never overwritten; bad assemblies are refused with a clear message.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

import pandas as pd
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.devices import DEVICES_DIR, Device, Part, list_devices, list_parts, save_device, slugify
from core.quantities.measurement import ParamError

GAS = ["blackline_g7c", "blackline_g7x_bridge", "blackline_g8", "msa_altair_io4", "msa_altair_io6"]
Q = {"lel": "air.lel_pct", "o2": "air.o2_pct", "co": "air.co_ppm", "h2s": "air.h2s_ppm", "voc": "air.voc_ppm"}
with open(os.path.join(ROOT, "configs", "gas", "assumptions.json")) as fh:
    A = json.load(fh)


def v(x):
    return x["value"] if isinstance(x, dict) else x


class TestParts(unittest.TestCase):
    def test_every_part_loads_with_sources(self):
        for slug in list_parts():
            with self.subTest(slug):
                p = Part.load(slug)
                for q, params in p.measures.items():
                    for k, prm in params.items():
                        self.assertTrue(prm["source"].startswith(("datasheet", "ASSUMPTION")), f"{q}.{k}")
                p.models()

    def test_parts_without_datasheet_are_flagged(self):
        for slug in ("maxim_max44009",):
            for params in Part.load(slug).measures.values():
                for k, prm in params.items():
                    self.assertIn("[USER TO VERIFY]", prm["source"], f"{slug}.{k}")

    def test_datasheet_wording_is_normalised(self):
        m = Part.load("bosch_bme280").models()["air.humidity_rh"]
        self.assertEqual(m.hysteresis, 2)                       # ±1 %RH -> band of width 2
        self.assertAlmostEqual(m.t90_s, 2.302585, places=5)    # tau63 1 s
        self.assertAlmostEqual(m.drift_per_hour, 0.5 / 8760)
        mag = Part.load("bosch_bmm150").models()["body.mag_ut"]
        self.assertEqual(mag.range[2], (-2000.0, 2000.0))
        self.assertEqual(mag.bandwidth_hz, 5.0)
        self.assertTrue(mag.sources["bandwidth_hz"].startswith("ASSUMPTION"))


class TestGasPresets(unittest.TestCase):
    """Same numbers as configs/gas and the same columns as the old engine's CSV."""

    def test_columns_match_old_csv(self):
        for d in GAS:
            with self.subTest(d):
                old = pd.read_csv(os.path.join(ROOT, "data", "gas", f"{d}_shift_seed42.csv"), nrows=1)
                expect = [c for c in old.columns if c not in ("gap_before_s", "event")]
                dev = Device.load(d)
                new = ["fall_state", "no_motion_state"] if d == "blackline_g7c" else []     # added later, at the end
                self.assertEqual(dev.columns(), expect + new)
                self.assertEqual(dev.device_id(), old["device_id"].iloc[0])

    def test_numbers_match_spec_and_assumptions(self):
        sp, lim = v(A["alarm_setpoints"]), v(A["exposure_limits"])
        t90, rf, sd = v(A["t90_s"]), v(A["recovery_factor"]), v(A["measurement_noise_sd"])
        for d in GAS:
            with open(os.path.join(ROOT, "configs", "gas", d, "spec.json")) as fh:
                spec = json.load(fh)
            dev = Device.load(d)
            models = {q: m for _, q, m in dev.models()}
            self.assertEqual(set(models) - {"body.accel_g"}, {Q[g] for g in spec["channels"]})
            for g, ch in spec["channels"].items():
                with self.subTest(f"{d}.{g}"):
                    m = models[Q[g]]
                    self.assertEqual(m.range, (v(ch["range_min"]), v(ch["range_max"])))
                    self.assertEqual(m.resolution, v(ch["resolution"]))
                    self.assertEqual(m.noise_sd, sd[g])
                    rise, fall = (m.t90(False), m.t90(True)) if g == "o2" else (m.t90(True), m.t90(False))
                    self.assertEqual((rise, fall), (t90[g], t90[g] * rf))
                    blk = {b["output"]: b for b in dev.logic}
                    low, high = blk[f"{g}_alarm_low"], blk[f"{g}_alarm_high"]
                    self.assertEqual((v(low["level"]), v(high["level"])), (sp[g]["low"], sp[g]["high"]))
                    self.assertEqual(low["when"], "below" if g == "o2" else "above")
                    self.assertEqual((blk[f"{g}_over_range"]["level"], blk[f"{g}_over_range"]["input"]), ("range_max", Q[g]))
                    if g in lim:
                        self.assertEqual((v(blk[f"{g}_alarm_stel"]["level"]), v(blk[f"{g}_alarm_twa"]["level"])),
                                         (lim[g]["stel"], lim[g]["twa"]))
                        self.assertEqual(v(blk[f"{g}_stel_ppm"]["window_s"]), v(A["stel_rule"])["window_s"])
                        self.assertEqual(v(blk[f"{g}_twa_ppm"]["period_s"]), v(A["twa_rule"])["period_s"])
            self.assertEqual(dev.feature("sample_interval_s"), v(A["logging_interval_s"]))
            bat = next(b for b in dev.logic if b["block"] == "battery")
            self.assertEqual(v(bat["runtime_h"]), v(spec["battery_runtime_h"]))

    def test_g7c_motion_alerts(self):
        dev = Device.load("blackline_g7c")
        accel = [u for u in dev.parts if "body.accel_g" in u.part.quantities()][0]
        self.assertFalse(accel.logged("body.accel_g"))
        self.assertTrue(accel.note.startswith("ASSUMPTION"))
        self.assertEqual(dev.columns()[-2:], ["fall_state", "no_motion_state"])
        self.assertEqual({"motion_alerts.fall", "motion_alerts.no_motion"} & dev.capabilities(),
                         {"motion_alerts.fall", "motion_alerts.no_motion"})
        bad = {"name": "No Accel", "parts": [{"part": "blackline_h2s_cell"}],
               "logic": [b for b in dev.logic if b["block"] == "stillness_timer"]}
        with self.assertRaises(ParamError):
            Device.from_dict(bad)

    def test_io6_assumptions_carried(self):
        dev = Device.load("msa_altair_io6")
        notes = [u.note for u in dev.parts]
        self.assertTrue(all(n.startswith("ASSUMPTION") for n in notes))
        voc = Part.load("msa_altair_pid_voc").measures["air.voc_ppm"]
        self.assertTrue(voc["range"]["source"].startswith("ASSUMPTION: borrowed from Blackline PID"))


class TestHiddenChannels(unittest.TestCase):
    def test_measured_but_not_logged_feeds_derived(self):
        imu = {"name": "IMU Logger", "parts": [{"part": "bosch_bma280"}, {"part": "bosch_bmg160", "log": False},
                                               {"part": "bosch_bmm150"}],
               "logic": [{"block": "orientation_quat", "output": "orientation", "params": {
                   "write_w": {"value": False, "unit": "-", "source": "ASSUMPTION: test"}}}]}
        dev = Device.from_dict(imu)
        cols = dev.columns()
        self.assertIn("body.gyro_dps", dev.measured())
        self.assertFalse(any(c.startswith("gyro") for c in cols))
        self.assertEqual(cols[-3:], ["orientation_x", "orientation_y", "orientation_z"])


    def test_no_xdk_preset(self):
        self.assertNotIn("bosch_xdk", list_devices())


TANK = {"name": "Tank Monitor v1", "device_id_prefix": "TANKMON",
        "description": "Monitor udara tangki, dirakit dari BME280 + sel H2S",
        "parts": [{"part": "bosch_bme280"}, {"part": "blackline_h2s_cell", "overrides": {"t90_s": {"value": 25}}}],
        "features": {"sample_interval_s": {"value": 10, "unit": "s", "source": "ASSUMPTION: user choice"},
                     "connectivity": {"value": "cellular", "unit": "-", "source": "ASSUMPTION: user choice"}},
        "logic": [
            {"block": "rolling_mean", "input": "air.h2s_ppm", "output": "h2s_stel_ppm",
             "window_s": {"value": 900, "unit": "s", "source": "ASSUMPTION: user choice"}},
            {"block": "cumulative_dose", "input": "air.h2s_ppm", "output": "h2s_twa_ppm",
             "period_s": {"value": 28800, "unit": "s", "source": "ASSUMPTION: user choice"}},
            {"block": "battery", "output": "battery_pct", "runtime_h": {"value": 18, "unit": "h", "source": "ASSUMPTION: user choice"},
             "start_pct": {"value": 100, "unit": "%", "source": "ASSUMPTION: user choice"}},
            {"block": "signal", "output": "signal_strength_dbm",
             "range_dbm": {"value": [-115, -55], "unit": "dBm", "source": "ASSUMPTION: user choice"},
             "start_dbm": {"value": [-90, -70], "unit": "dBm", "source": "ASSUMPTION: user choice"},
             "step_sd_db": {"value": 1, "unit": "dB", "source": "ASSUMPTION: user choice"}},
            {"block": "threshold_alarm", "input": "air.h2s_ppm", "output": "h2s_alarm_low", "when": "above",
             "level": {"value": 10, "unit": "ppm", "source": "ASSUMPTION: user choice"}},
            {"block": "threshold_alarm", "input": "air.h2s_ppm", "output": "h2s_alarm_high", "when": "above",
             "level": {"value": 15, "unit": "ppm", "source": "ASSUMPTION: user choice"}},
            {"block": "threshold_alarm", "input": "h2s_stel_ppm", "output": "h2s_alarm_stel", "when": "above",
             "level": {"value": 15, "unit": "ppm", "source": "ASSUMPTION: user choice"}},
            {"block": "threshold_alarm", "input": "h2s_twa_ppm", "output": "h2s_alarm_twa", "when": "above",
             "level": {"value": 10, "unit": "ppm", "source": "ASSUMPTION: user choice"}}]}


class TestUserDevice(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_assemble_name_save_version(self):
        dev = save_device(TANK, self.dir)
        self.assertEqual((dev.slug, dev.version), ("tank_monitor_v1", 1))
        self.assertTrue(dev.path.endswith("tank_monitor_v1.yaml"))
        self.assertEqual(dev.columns(), ["timestamp", "device_id", "temperature_c", "humidity_rh", "pressure_hpa",
                                         "h2s_ppm", "h2s_stel_ppm", "h2s_twa_ppm", "battery_pct",
                                         "signal_strength_dbm", "h2s_alarm_low", "h2s_alarm_high", "h2s_alarm_stel",
                                         "h2s_alarm_twa"])
        h2s = {q: m for _, q, m in dev.models()}["air.h2s_ppm"]
        self.assertEqual(h2s.t90_s, 25)
        self.assertEqual(h2s.sources["t90_s"], "ASSUMPTION: user tweak")
        with open(dev.path) as fh:
            first = fh.read()
        # same name again: version 2 in a new file, version 1 untouched
        dev2 = save_device(dict(TANK, description="second try"), self.dir)
        self.assertEqual(dev2.version, 2)
        self.assertTrue(dev2.path.endswith("tank_monitor_v1.v2.yaml"))
        with open(dev.path) as fh:
            self.assertEqual(fh.read(), first)
        self.assertEqual(Device.load("tank_monitor_v1", devices_dir=self.dir).version, 2)
        self.assertEqual(Device.load("tank_monitor_v1", 1, devices_dir=self.dir).description, TANK["description"])
        self.assertEqual(list_devices(self.dir), ["tank_monitor_v1"])
        # another name that makes the same file name is refused
        with self.assertRaises(ParamError):
            save_device(dict(TANK, name="tank monitor V1!"), self.dir)

    def test_presets_cannot_be_overwritten(self):
        shutil.copy(os.path.join(DEVICES_DIR, "blackline_g8.yaml"), self.dir)
        with open(os.path.join(DEVICES_DIR, "blackline_g8.yaml")) as fh:
            d = yaml.safe_load(fh)
        with self.assertRaises(ParamError):
            save_device(d, self.dir)

    def test_two_parts_same_quantity_need_aliases(self):
        two = {"name": "Two BME", "parts": [{"part": "bosch_bme280"}, {"part": "bosch_bme280"}]}
        with self.assertRaises(ParamError):
            save_device(two, self.dir)
        two["parts"][1]["as"] = "outside"
        dev = save_device(two, self.dir)
        self.assertIn("temperature_c_bosch_bme280", dev.columns())
        self.assertIn("temperature_c_outside", dev.columns())

    def test_bad_assemblies_refused(self):
        cases = {
            "alarm on unmeasured": {"logic": [{"block": "threshold_alarm", "input": "air.co_ppm", "output": "co_alarm",
                                               "when": "above", "level": {"value": 1, "unit": "ppm", "source": "ASSUMPTION: x"}}]},
            "orientation without an imu": {"logic": [{"block": "orientation_quat", "output": "orientation"}]},
            "alarm without a source": {"logic": [{"block": "threshold_alarm", "input": "air.temperature_c", "output": "t_alarm",
                                                  "when": "above", "level": 30}]},
            "unknown block": {"logic": [{"block": "teleport", "output": "x"}]},
            "old style feature": {"features": {"battery_hours": {"value": 1, "unit": "h", "source": "ASSUMPTION: x"}}},
            "unknown feature": {"features": {"teleport": {"value": 1, "unit": "-", "source": "ASSUMPTION: x"}}},
            "feature without source": {"features": {"sample_interval_s": {"value": 1, "unit": "s"}}},
            "override bad source": {"parts": [{"part": "blackline_h2s_cell",
                                               "overrides": {"t90_s": {"value": 5, "unit": "s", "source": "guess"}}}]},
            "override by param on a multi-quantity part": {"parts": [{"part": "bosch_bme280",
                                                                      "overrides": {"accuracy": {"value": 1}}}]},
        }
        for name, extra in cases.items():
            with self.subTest(name), self.assertRaises((ParamError, KeyError)):
                save_device({"name": "Bad", "parts": [{"part": "bosch_bme280"}], **extra}, self.dir)
        self.assertEqual(os.listdir(self.dir), [])

    def test_slug(self):
        self.assertEqual(slugify("Tank Monitor v1"), "tank_monitor_v1")
        self.assertEqual(slugify("  MSA ALTAIR io6 "), "msa_altair_io6")


if __name__ == "__main__":
    unittest.main()
