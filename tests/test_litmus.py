"""
Litmus: three domains added with data files only (configs/, commit "Add fridge, pump vibration and
soil moisture examples as data files only"). A fridge logger sees a compressor failure, a pump
vibration sensor sees bearing wear on a shift schedule, a soil probe sees irrigation.
"""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.devices import Device
from core.events import ScenarioError, prepare


class TestFridge(unittest.TestCase):
    def test_compressor_failure(self):
        p = prepare("fridge_compressor_failure")
        t = np.arange(0, 24 * 3600 + 1)
        T, I = p.world.at("air.temperature_c", t), p.world.at("electrical.current_a", t)
        self.assertTrue(2.5 < T[:6 * 3600].min() and T[:6 * 3600].max() < 7)
        self.assertGreater(T[12 * 3600 - 1], 15)                        # warms without the compressor
        self.assertLess(I[6 * 3600 + 10:12 * 3600].max(), 0.2)           # its current is gone
        self.assertLess(T[20 * 3600], 8)                                 # cools again after the restart
        self.assertTrue(any(lb.event == "compressor_failure" for lb in p.labels["fridge_logger"]))
        self.assertEqual(Device.load("fridge_logger").columns(),
                         ["timestamp", "device_id", "temperature_c", "current_a", "signal_strength_dbm"])


class TestPump(unittest.TestCase):
    def test_bearing_wear_on_schedule(self):
        p = prepare("pump_bearing_wear")
        v = p.world.at("machine.vibration_mm_s", np.arange(0, 96 * 3600 + 1))
        healthy = v[0:3600].mean() - 0.1
        day = lambda d: v[(d * 24 + 6) * 3600:(d * 24 + 16) * 3600].mean() - 0.1
        self.assertAlmostEqual(day(3) / healthy, 2.5, delta=0.3)
        self.assertLess(day(0), day(1))
        self.assertLess(day(1), day(3))
        for d in range(3):                                               # off at night: background only
            self.assertLess(v[(d * 24 + 18) * 3600:(d * 24 + 23) * 3600].max(), 0.1001)


class TestField(unittest.TestCase):
    def test_irrigation(self):
        p = prepare("field_irrigation")
        m = p.world.at("soil.moisture_pct", np.arange(0, 72 * 3600 + 1))
        a = 23 * 3600
        self.assertLess(m[a - 1], m[0] - 1)                              # drying
        self.assertTrue(9 < m[a + 1800] - m[a - 1] < 12.5)               # watering
        self.assertLess(m[a + 1800 + 86400], m[a + 1800] - 5)            # draining


class TestRefusals(unittest.TestCase):
    def test_event_needs_its_world_and_a_device(self):
        base = {"name": "x", "duration": "2h", "seed": 1}
        with self.assertRaises(ScenarioError) as e:
            prepare(dict(base, world="indoor_worker_walking", devices=[{"device": "blackline_g7c"}],
                         events=[{"irrigation": {"at": 600}}]))
        self.assertIn("has no 'irrigation'", str(e.exception))           # the soil's inflow signal
        with self.assertRaises(ScenarioError) as e:
            prepare(dict(base, world="fridge", devices=[{"device": "blackline_g7c", "mount": "fixed"}],
                         events=[{"compressor_failure": {"at": 600, "duration_s": 3600}}]))
        self.assertIn("no device in this run can see it", str(e.exception))


if __name__ == "__main__":
    unittest.main()
