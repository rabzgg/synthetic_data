"""
The Streamlit UI (ui/app.py) runs every way in: columns (pre-sales, the default), a device built from
parts and named by the user, and a scenario; each offers only the worlds and events it can use and
ends with files that pass the gate, with a data summary. Skipped when streamlit is not installed.
"""
import os
import sys
import unittest

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    from streamlit.testing.v1 import AppTest
except ImportError:                                     # the UI is optional
    AppTest = None

APP = os.path.join(ROOT, "ui", "app.py")


@unittest.skipIf(AppTest is None, "streamlit not installed")
class TestUi(unittest.TestCase):
    def test_scenario(self):
        at = AppTest.from_file(APP, default_timeout=300).run()
        self.assertEqual(at.sidebar.radio[0].value, "Start from columns")              # the default
        hint = next(c.value for c in at.caption if "EXTEND.md" in c.value)          # how to add a missing column
        self.assertTrue(os.path.exists(os.path.join(ROOT, hint.split("See ")[1].split(" in")[0])))
        at.sidebar.radio[0].set_value("A scenario (in progress)").run()
        at.sidebar.selectbox[0].set_value("fridge_compressor_failure").run()
        at.sidebar.button[0].click().run()
        self.assertEqual(at.exception, [])
        self.assertIn("fridge_logger: gate PASSED", [h.value for h in at.subheader])

    def test_build_a_device(self):
        at = AppTest.from_file(APP, default_timeout=300).run()
        at.sidebar.radio[0].set_value("Build a device").run()
        at.multiselect[0].set_value(["bosch_bme280", "blackline_h2s_cell"]).run()
        self.assertNotIn("Aquarium (aquarium)", at.sidebar.selectbox[0].options)     # no H2S there
        at.sidebar.text_input[0].set_value("Tank Monitor v1").run()
        at.sidebar.number_input[1].set_value(2).run()                                  # 2 h
        at.number_input(key="blackline_h2s_cell/air.h2s_ppm/t90_s").set_value(25.0).run()
        self.assertTrue(any("user tweak" in c.value for c in at.caption))
        labels = [c.label for c in at.checkbox]
        self.assertIn("gas_release (h2s)", labels)
        self.assertNotIn("pump_fault", labels)                                         # it has no pump
        next(c for c in at.checkbox if c.label == "gas_release (h2s)").check().run()
        at.button[-1].click().run()
        self.assertEqual(at.exception, [])
        self.assertIn("tank_monitor_v1: gate PASSED", [h.value for h in at.subheader])

    def test_columns_generic_motion_with_a_fall(self):
        at = AppTest.from_file(APP, default_timeout=600).run()
        at.multiselect(key="cols/body").set_value(["body.accel_g", "body.gyro_dps"]).run()
        at.selectbox(key="world_choice").set_value("indoor_worker_walking").run()
        self.assertEqual(at.selectbox(key="part/body.accel_g").value, "generic")      # the default
        self.assertEqual(at.number_input(key="hours").value, 1)
        next(c for c in at.checkbox if c.label == "fall").check().run()
        at.button(key="generate").click().run()
        self.assertEqual(at.exception, [])
        self.assertIn("client_device: gate PASSED", [h.value for h in at.subheader])
        self.assertTrue(any(m.value.startswith("**Data summary**") for m in at.markdown))
        path = at.session_state["results"][0]["summary"]
        self.assertTrue(path.endswith("_summary.json") and os.path.exists(path))

    def test_columns_temperature_via_bme280_as_raw_counts(self):
        at = AppTest.from_file(APP, default_timeout=600).run()
        at.multiselect(key="cols/air").set_value(["air.temperature_c"]).run()
        at.selectbox(key="world_choice").set_value("fridge").run()
        part = at.selectbox(key="part/air.temperature_c")
        self.assertIn("Bosch BME280 (also measures humidity_rh, pressure_hpa (not logged))", part.options)
        part.set_value("bosch_bme280").run()
        at.checkbox(key="raw").check().run()
        at.number_input(key="hours").set_value(2).run()
        at.button(key="generate").click().run()
        self.assertEqual(at.exception, [])
        self.assertIn("client_device: gate PASSED", [h.value for h in at.subheader])
        d = pd.read_csv(at.session_state["results"][0]["csv"])
        self.assertEqual(list(d.columns), ["timestamp", "device_id", "temperature_c_counts"])
        self.assertTrue(pd.api.types.is_integer_dtype(d["temperature_c_counts"]))

    def test_no_world_for_these_parts(self):
        at = AppTest.from_file(APP, default_timeout=300).run()
        at.sidebar.radio[0].set_value("Build a device").run()
        at.multiselect[0].set_value(["generic_soil_moisture_probe", "generic_level_transmitter"]).run()
        self.assertTrue(any("No world provides" in e.value for e in at.error))


if __name__ == "__main__":
    unittest.main()
