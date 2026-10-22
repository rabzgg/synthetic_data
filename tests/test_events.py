"""
Events: each changes the world (and the related quantities follow) or one device; compatibility with
the devices of a run is checked and an event no device can see is refused with the reason; scenarios
load, are reproducible and keep their spacing; labels give the order of a collapse and the expected
fall and no-motion alerts.
"""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.devices import Device
from core.events import EVENTS, ScenarioError, compatibility, list_scenarios, load_scenario, prepare
from core.events.doc import DOC, markdown
from core.world import physics as P


def sc(events, devices=("blackline_g7c",), world="indoor_worker_walking", duration="2h", **kw):
    return dict({"name": "t", "world": world, "duration": duration, "seed": 1,
                 "devices": [d if isinstance(d, dict) else {"device": d, "mount": "body"} for d in devices],
                 "events": events}, **kw)


class TestWorldEvents(unittest.TestCase):
    def test_gas_release_and_oxygen(self):
        p = prepare(sc([{"gas_release": {"at": "00:30:00", "gas": "lel", "level": 40, "duration_min": 10, "ramp_s": 60}}]))
        w = p.world
        t = np.arange(0, 7200)
        lel = w.at("air.lel_pct", t)
        self.assertEqual(lel[1800 + 60 + 300], 40)                 # on the plateau
        self.assertEqual(lel[1700], 0)
        self.assertAlmostEqual(lel[1830], 20, places=6)            # half way up the ramp
        o2 = w.at("air.o2_pct", t)
        co2x = np.maximum(w.at("air.co2_ppm", t) - 420, 0) * 1e-6
        np.testing.assert_allclose(o2, 20.9 * (1 - lel / 100 * 0.05 - co2x))
        self.assertAlmostEqual(o2[1800 + 360], 20.9 * (1 - 0.02 - co2x[2160]))

    def test_temperature_change_moves_rh(self):
        board = ["bme280_sensor_board"]
        base = prepare(sc([], devices=board)).world
        p = prepare(sc([{"temperature_change": {"at": "00:20:00", "delta_c": 5, "ramp_s": 300, "duration_min": 30}}],
                       devices=board))
        t = np.array([1000.0, 1200 + 300 + 900])
        dT = p.world.at("air.temperature_c", t) - base.at("air.temperature_c", t)
        np.testing.assert_allclose(dT, [0, 5], atol=1e-9)
        self.assertLess(p.world.at("air.humidity_rh", t)[1], base.at("air.humidity_rh", t)[1] - 10)

    def test_door_open_mixes_towards_outside(self):
        board = [{"device": "bme280_sensor_board", "mount": "fixed"}]
        base = prepare(sc([], devices=board)).world
        p = prepare(sc([{"door_open": {"at": "00:30:00", "duration_min": 5, "outside_temperature_c": 0}}], devices=board))
        t_end, t_late = 1800 + 299, 1800 + 300 + 3 * 900
        T0, T1 = base.at("air.temperature_c", [t_end, t_late]), p.world.at("air.temperature_c", [t_end, t_late])
        self.assertLess(T1[0], T0[0] - 10)                         # cold air in
        self.assertLess(abs(T1[1] - T0[1]), 0.1 * abs(T1[0] - T0[0]))   # recovering after the door closes
        self.assertGreater(p.world.at("light.lux", 1900)[0], base.at("light.lux", 1900)[0] + 1000)

    def test_fall_and_no_motion_in_the_motion(self):
        p = prepare(sc([{"fall": {"at": "00:20:00", "lying_s": 40}}, {"no_motion": {"at": "01:00:00", "duration_s": 200}}]))
        w = p.world
        self.assertEqual(w.state_at(1200.5)[0], "fall")
        self.assertEqual(w.state_at(1220)[0], "lying")
        self.assertEqual(w.state_at(1243)[0], "rise")
        self.assertEqual(w.state_at(3700)[0], "motionless")
        g = w.at("body.gyro_dps", np.arange(3601, 3799, 0.04))
        np.testing.assert_allclose(g, 0, atol=1e-9)                 # truly no movement

    def test_collapse_order_and_gaps(self):
        p = prepare(sc([{"collapse": {"at": "00:30:00", "gas": "h2s", "level": 80, "fall_after_s": 90,
                                      "no_motion_after_s": 40, "no_motion_s": 300}}]))
        lb = {l.event: l for l in p.labels["blackline_g7c"]}
        fall, stir, still, rescue = (lb[f"collapse:{k}"] for k in ("fall", "stir", "no_motion", "rescue"))
        self.assertEqual(fall.start, 1800 + 90)
        self.assertEqual(stir.start, fall.end)
        self.assertEqual(still.start - stir.start, 40)
        self.assertEqual(still.end - still.start, 300)
        self.assertEqual(rescue.start, still.end)
        self.assertEqual(p.world.state_at(stir.start + 20)[0], "stir")
        self.assertEqual(p.world.at("air.h2s_ppm", fall.start)[0], 80)

    def test_world_event_needs_a_device_that_sees_it(self):
        with self.assertRaises(ScenarioError) as e:
            prepare(sc([{"gas_release": {"at": "00:10:00", "gas": "voc", "level": 50}}]))
        self.assertIn("below the sensor resolution", str(e.exception))
        with self.assertRaises(ScenarioError) as e:
            prepare(sc([{"fall": {"at": "00:10:00"}}], devices=[{"device": "blackline_g7c", "mount": "fixed"}]))
        self.assertIn("the device is fixed", str(e.exception))


class TestDeviceEvents(unittest.TestCase):
    def test_bump_test_only_measured_gases(self):
        p = prepare(sc([{"bump_test": {"at": "00:02:00"}}], devices=["msa_altair_io6"]))
        ov = {o[0]: o for o in p.view("msa_altair_io6").overrides}
        self.assertEqual(set(ov), {"air.lel_pct", "air.h2s_ppm", "air.co_ppm", "air.o2_pct"})   # no VOC in the mix
        self.assertEqual(ov["air.o2_pct"][1:], (120.0, 180.0, "value", 18.0))

    def test_device_events_land_on_the_view(self):
        p = prepare(sc([{"connection_loss": {"at": 600, "duration_s": 70}}, {"pump_fault": {"at": 900}},
                        {"sensor_fault": {"at": 1200, "quantity": "air.co_ppm", "mode": "offset", "offset": 5}},
                        {"battery_drain": {"at": 1500}}], devices=["msa_altair_io6"]))
        v = p.view("msa_altair_io6")
        self.assertEqual(v.gaps, [(600.0, 670.0)])
        self.assertEqual(v.states["pump"], [(900.0, 1200.0)])
        self.assertIn(("air.co_ppm", 1200.0, 1800.0, "offset", 5.0), v.overrides)
        self.assertEqual(v.battery, [(1500.0, 5100.0, 10.0)])

    def test_unsupported_device_event_refused_with_reason(self):
        with self.assertRaises(ScenarioError) as e:
            prepare(sc([{"pump_fault": {"at": 900, "devices": ["blackline_g7c"]}}]))
        self.assertIn("states.pump", str(e.exception))
        with self.assertRaises(ScenarioError):                      # nobody in the run supports it
            prepare(sc([{"pump_fault": {"at": 900}}]))
        p = prepare(sc([{"pump_fault": {"at": 900, "optional": True}}]))
        self.assertTrue(any("skipped (optional)" in n for n in p.notes))

    def test_multi_device_targets(self):
        p = prepare(sc([{"pump_fault": {"at": 900}}], devices=["blackline_g7c", "msa_altair_io6"]))
        self.assertEqual(p.view("msa_altair_io6").states["pump"], [(900.0, 1200.0)])
        self.assertNotIn("pump", p.view("blackline_g7c").states)
        self.assertTrue(any("not given to blackline_g7c" in n for n in p.notes))

    def test_bad_input(self):
        for ev in ({"teleport": {}}, {"gas_release": {"at": 10, "colour": "red"}}, {"gas_release": {"at": "7:59:00"}}):
            with self.subTest(ev), self.assertRaises(ScenarioError):
                prepare(sc([ev], duration="8h"))


class TestExpectedAlerts(unittest.TestCase):
    def alerts(self, events):
        p = prepare(sc(events))
        return [l for l in p.labels["blackline_g7c"] if l.scope == "expected"]

    def test_collapse_sequence(self):
        lb = self.alerts([{"collapse": {"at": "00:30:00", "gas": "h2s", "level": 80, "no_motion_after_s": 20,
                                        "no_motion_s": 600}}])
        ev = {l.event: l for l in lb}
        t_rest = 1800 + 60 + 1.5
        self.assertEqual(ev["fall_pre_alarm"].start, t_rest)
        self.assertEqual(ev["fall_alert"].start, t_rest + 30)
        self.assertEqual(ev["no_motion_pre_alarm"].start, t_rest + 20 + 120)
        self.assertEqual(ev["no_motion_alert"].start, t_rest + 20 + 150)
        self.assertEqual(ev["no_motion_alert"].end, t_rest + 20 + 600)
        self.assertEqual(ev["fall_alert"].end, t_rest + 20 + 600)            # until rescued

    def test_getting_up_cancels_the_fall_alert(self):
        short = self.alerts([{"fall": {"at": "00:20:00", "lying_s": 10}}])
        self.assertEqual([l.event for l in short], ["fall_pre_alarm"])
        long = self.alerts([{"fall": {"at": "00:20:00", "lying_s": 90}}])
        self.assertEqual([l.event for l in long], ["fall_pre_alarm", "fall_alert"])

    def test_short_stillness_no_alarm(self):
        self.assertEqual(self.alerts([{"no_motion": {"at": "00:20:00", "duration_s": 100}}]), [])
        self.assertEqual(self.alerts([]), [])                       # a working day without events: none


class TestScenarios(unittest.TestCase):
    def test_all_scenarios_prepare_on_five_seeds(self):
        for name in list_scenarios():
            for seed in (42, 43, 44, 45, 46):
                with self.subTest(name=name, seed=seed):
                    p = prepare(name, seed=seed)
                    self.assertEqual(p.world.realism, "ASSUMPTION")
                    gas = sorted((e for e in p.events if e.kind == "gas_release"), key=lambda e: e.at)
                    for a, b in zip(gas, gas[1:]):
                        self.assertGreaterEqual(b.at, a.end + 1800)       # spacing kept

    def test_forced_exposures_present(self):
        want = {"gas_stel_alarm": ("h2s", 20, 900), "gas_twa_alarm": ("co", 55, 14400),
                "gas_over_range": ("lel", 110, 60), "gas_voc_exposure": ("voc", 20, 120)}
        for name, (gas, level, dur) in want.items():
            p = prepare(name, seed=7)
            self.assertTrue(any(e.kind == "gas_release" and e.p("gas") == gas and e.p("level") >= level and
                                e.p("duration_s") >= dur for e in p.events), name)
        self.assertTrue(any(e.kind == "pump_fault" for e in prepare("gas_pump_fault", seed=7).events))

    def test_reproducible(self):
        a, b, c = prepare("gas_normal_shift", seed=3), prepare("gas_normal_shift", seed=3), prepare("gas_normal_shift", seed=4)
        row = lambda p: [l.row() for l in p.labels["blackline_g7c"]]
        self.assertEqual(row(a), row(b))
        self.assertNotEqual(row(a), row(c))

    def test_sources_on_scenario_values(self):
        p = prepare("gas_stel_alarm", seed=1)
        for e in p.events:
            for k, prm in e.params.items():
                self.assertTrue(prm["source"].startswith(("ASSUMPTION", "datasheet")), f"{e.kind}.{k}")


class TestCompatibility(unittest.TestCase):
    def test_table(self):
        rows = dict(compatibility())
        self.assertTrue(rows["pump_fault"]["msa_altair_io6"][0])
        self.assertFalse(rows["pump_fault"]["blackline_g7c"][0])
        self.assertTrue(rows["no_motion"]["blackline_g7c"][0])      # the G7c has an accelerometer now
        self.assertFalse(rows["no_motion"]["blackline_g8"][0])
        self.assertTrue(rows["fall"]["bme280_sensor_board"][0])     # worn, a fall shows in its pressure
        fixed = dict(compatibility(mount="fixed"))
        self.assertFalse(fixed["fall"]["bme280_sensor_board"][0])
        self.assertTrue(fixed["collapse (h2s)"]["msa_altair_io4"][0])     # the gas part still reaches it

    def test_doc_is_generated(self):
        with open(DOC) as fh:
            self.assertEqual(fh.read(), markdown(), "run: python3 cli/events_doc.py")


if __name__ == "__main__":
    unittest.main()
