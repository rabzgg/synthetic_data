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
        at.sidebar.radio[0].set_value("Example scenarios").run()
        at.sidebar.selectbox[0].set_value("fridge_compressor_failure").run()
        at.sidebar.button[0].click().run()
        self.assertEqual(at.exception, [])
        self.assertIn("Fridge Logger: checks passed", [h.value for h in at.subheader])

    def test_build_a_device(self):
        at = AppTest.from_file(APP, default_timeout=300).run()
        at.sidebar.radio[0].set_value("Build a device").run()
        at.multiselect[0].set_value(["bosch_bme280", "blackline_h2s_cell"]).run()
        self.assertNotIn("Aquarium", at.sidebar.selectbox[0].options)     # no H2S there
        at.sidebar.text_input[0].set_value("Tank Monitor v1").run()
        at.sidebar.number_input[1].set_value(2).run()                                  # 2 h
        at.number_input(key="blackline_h2s_cell/air.h2s_ppm/t90_s").set_value(25.0).run()
        self.assertTrue(any("saved as assumed" in c.value for c in at.caption))
        labels = [c.label for c in at.checkbox]
        self.assertIn("Gas release (H2S)", labels)
        self.assertNotIn("Pump fault", labels)                                         # it has no pump
        next(c for c in at.checkbox if c.label == "Gas release (H2S)").check().run()
        at.button[-1].click().run()
        self.assertEqual(at.exception, [])
        self.assertIn("Tank Monitor v1: checks passed", [h.value for h in at.subheader])

    def test_columns_generic_motion_with_a_fall(self):
        at = AppTest.from_file(APP, default_timeout=600).run()
        at.multiselect(key="cols/body").set_value(["body.accel_g", "body.gyro_dps"]).run()
        at.selectbox(key="world_choice").set_value("indoor_worker_walking").run()
        self.assertEqual(at.selectbox(key="part/body.accel_g").value, "generic")      # the default
        self.assertEqual(at.number_input(key="hours").value, 1)
        why = next(d.value for d in at.dataframe if "why not" in d.value.columns)
        self.assertIn("This environment has no air conditioner.", list(why["why not"]))     # plain words, no ids
        self.assertFalse(why["why not"].str.contains(r"world|\w+\.\w+_|;").any())
        self.assertIn("Fall down", [c.label for c in at.checkbox])                        # under Building blocks
        next(c for c in at.checkbox if c.label == "Fall").check().run()
        at.button(key="generate").click().run()
        self.assertEqual(at.exception, [])
        self.assertIn("Client device: checks passed", [h.value for h in at.subheader])
        self.assertTrue(any(m.value.startswith("**Data summary**") for m in at.markdown))
        path = at.session_state["results"][0]["summary"]
        self.assertTrue(path.endswith("_summary.json") and os.path.exists(path))

    def test_columns_temperature_via_bme280_as_raw_counts(self):
        at = AppTest.from_file(APP, default_timeout=600).run()
        at.multiselect(key="cols/air").set_value(["air.temperature_c"]).run()
        at.selectbox(key="world_choice").set_value("fridge").run()
        part = at.selectbox(key="part/air.temperature_c")
        self.assertIn("Bosch BME280 (also measures humidity_rh and pressure_hpa, not written)", part.options)
        part.set_value("bosch_bme280").run()
        at.checkbox(key="raw").check().run()
        at.number_input(key="hours").set_value(2).run()
        at.button(key="generate").click().run()
        self.assertEqual(at.exception, [])
        self.assertIn("Client device: checks passed", [h.value for h in at.subheader])
        d = pd.read_csv(at.session_state["results"][0]["csv"])
        self.assertEqual(list(d.columns), ["timestamp", "device_id", "temperature_c_counts"])
        self.assertTrue(pd.api.types.is_integer_dtype(d["temperature_c_counts"]))

    def test_legacy_real_csv_page(self):
        at = AppTest.from_file(APP, default_timeout=600).run()
        at.sidebar.radio[0].set_value("Start from a real CSV (legacy)").run()
        self.assertEqual([i.value.replace("  \n", " ") for i in at.info],
                         ["Legacy statistical copy. Each column is fitted on its own, so columns are not linked by "
                          "physics. For potential clients without data, use Start from columns."])
        self.assertFalse(any("Nothing is fitted" in c.value for c in at.caption))
        at.radio(key="legacy_source").set_value("Example: robot arm sensor 1 (XDK, 10 Hz)").run()
        engines = at.dataframe[0].value
        self.assertEqual(list(engines.columns), ["column", "engine", "what it means"])
        self.assertIn("accel_x", list(engines["column"]))
        self.assertFalse(engines["engine"].str.contains("_").any())                      # no code names on screen
        at.number_input(key="legacy_minutes").set_value(10).run()
        at.button(key="legacy_generate").click().run()
        self.assertEqual(at.exception, [])
        self.assertTrue(any(c.value.startswith("Generated 6") for c in at.caption))
        self.assertEqual(len(at.session_state["legacy"]["syn"]), len(at.session_state["legacy"]["syn"].dropna()))

    def test_no_world_for_these_parts(self):
        at = AppTest.from_file(APP, default_timeout=300).run()
        at.sidebar.radio[0].set_value("Build a device").run()
        at.multiselect[0].set_value(["generic_soil_moisture_probe", "generic_level_transmitter"]).run()
        self.assertTrue(any("None of the environments" in e.value for e in at.error))


if __name__ == "__main__":
    unittest.main()
