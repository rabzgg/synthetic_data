"""
The handover docs stay true: their YAML examples load and run, and the files they point to exist.
"""
import os
import re
import sys
import unittest

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.events import EventDef, prepare
from core.world import World


def blocks(doc):
    with open(os.path.join(ROOT, "docs", doc)) as fh:
        return re.findall(r"```yaml\n(.*?)```", fh.read(), re.S)


class TestDocs(unittest.TestCase):
    def test_smallest_world_runs(self):
        w = yaml.safe_load(blocks("HOW_TO_ADD_A_WORLD.md")[0])
        world = World(dict(w, name="doc_example"), 3600, 1)
        self.assertAlmostEqual(world.tracks["water.ph"].values.mean(), 7.1)

    def test_event_and_scenario_examples(self):
        b = blocks("HOW_TO_ADD_AN_EVENT.md")
        ev = EventDef(yaml.safe_load(b[0]))
        self.assertEqual((ev.kind, ev.scope), ("leak", "world"))
        sc = yaml.safe_load(b[-1])
        p = prepare(dict(sc, duration="24h"))
        self.assertEqual([e.kind for e in p.events], ["leak"])

    def test_referenced_files_exist(self):
        for doc in ("ARCHITECTURE.md", "HOW_TO_ADD_A_SENSOR.md", "HOW_TO_ADD_A_WORLD.md", "HOW_TO_ADD_AN_EVENT.md",
                    "PRESALES.md", "UI.md"):
            with open(os.path.join(ROOT, "docs", doc)) as fh:
                text = fh.read()
            for path in set(re.findall(r"`((?:configs|core|validation|cli|docs)/[\w./-]+\.(?:py|yaml|md))`", text)):
                with self.subTest(doc=doc, path=path):
                    self.assertTrue(os.path.exists(os.path.join(ROOT, path)), path)


if __name__ == "__main__":
    unittest.main()
