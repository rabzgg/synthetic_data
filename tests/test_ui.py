"""
The Streamlit UI (ui/app.py) runs both ways in: a scenario, and a device built from parts and named
by the user, with only the worlds and events it can use; both end with files that pass the gate.
Skipped when streamlit is not installed.
"""
import os
import sys
import unittest

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
        self.assertEqual(at.sidebar.radio[0].value, "Build a device")                  # the default
        at.sidebar.radio[0].set_value("A scenario (in progress)").run()
        at.sidebar.selectbox[0].set_value("fridge_compressor_failure").run()
        at.sidebar.button[0].click().run()
        self.assertEqual(at.exception, [])
        self.assertIn("fridge_logger: gate PASSED", [h.value for h in at.subheader])

    def test_build_a_device(self):
        at = AppTest.from_file(APP, default_timeout=300).run()
        at.sidebar.radio[0].set_value("Build a device").run()
        at.sidebar.multiselect[0].set_value(["bosch_bme280", "blackline_h2s_cell"]).run()
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

    def test_no_world_for_these_parts(self):
        at = AppTest.from_file(APP, default_timeout=300).run()
        at.sidebar.radio[0].set_value("Build a device").run()
        at.sidebar.multiselect[0].set_value(["generic_soil_moisture_probe", "generic_level_transmitter"]).run()
        self.assertTrue(any("No world provides" in e.value for e in at.error))


if __name__ == "__main__":
    unittest.main()
