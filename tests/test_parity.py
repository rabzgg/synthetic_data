"""
Parity: files from the new generator go through the old gas rule gate (validation/gas_gate.py,
unchanged) via the adapter; the full table is docs/GAS_PARITY.md.
"""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.output import run
from validation.legacy_gas_adapter import check, to_legacy


class TestParity(unittest.TestCase):
    def test_old_gate_on_new_files(self):
        d = tempfile.mkdtemp()
        try:
            for sc, items in (("gas_stel_alarm", ["sustained_stel"]), ("worker_collapse", [])):
                r = next(x for x in run(sc, seed=42, out_dir=d, gate=False) if x["device"] == "blackline_g7c")
                legacy = to_legacy(r["csv"], r["labels"], r["manifest"])
                self.assertIn("gap_before_s", legacy.columns)
                self.assertIn("exposure_h2s", set(legacy["event"]))
                rep = check(r["csv"], r["labels"], r["manifest"], items)
                self.assertTrue(rep.passed, [c.name for c in rep.checks if not c.passed])
        finally:
            shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
