"""
docs/examples/radiation/: the files of a new measurement, copied as its README says into a temporary
copy of the repo (configs/ here is not touched). There the generated docs are rewritten, the tests that
load every config file pass without any edit in tests/, and the example scenario passes its gate.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import pandas as pd
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, "docs", "examples", "radiation")
COPY = ("core", "cli", "configs", "validation", "tests", "docs", "pytest.ini", "data/gas")     # data/gas: old gas CSVs for test_devices
TESTS = ("tests/test_quantities.py", "tests/test_generic_parts.py", "tests/test_devices.py", "tests/test_world.py",
         "tests/test_docs.py")


def paste_drivers(world_path: str, snippet_path: str):
    """What the README asks: the snippet's lines under "drivers:" go right under the world's "drivers:"."""
    with open(snippet_path) as fh:
        lines = fh.read().split("\n")
    body = "\n".join(lines[lines.index("drivers:") + 1:]).rstrip("\n") + "\n"
    with open(world_path) as fh:
        text = fh.read()
    assert "\ndrivers:\n" in text
    with open(world_path, "w") as fh:
        fh.write(text.replace("\ndrivers:\n", "\ndrivers:\n" + body, 1))


class TestRadiationExample(unittest.TestCase):
    def test_files_say_where_they_go(self):
        for folder in ("quantities", "parts", "events", "devices", "scenarios"):
            for f in os.listdir(os.path.join(EXAMPLE, folder)):
                with self.subTest(f):
                    with open(os.path.join(EXAMPLE, folder, f)) as fh:
                        self.assertTrue(fh.readline().startswith("# Example:"))
                        yaml.safe_load(fh)

    def test_copied_into_a_repo_copy_it_loads_and_passes_the_gate(self):
        before = sorted(os.listdir(os.path.join(ROOT, "configs", "quantities")))
        tmp = tempfile.mkdtemp(prefix="example_radiation_")
        try:
            for name in COPY:
                src, dst = os.path.join(ROOT, name), os.path.join(tmp, name)
                if os.path.isdir(src):
                    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "* 2.*"))
                else:
                    shutil.copy(src, dst)
            for folder in ("quantities", "parts", "events", "devices", "scenarios"):
                for f in os.listdir(os.path.join(EXAMPLE, folder)):
                    shutil.copy(os.path.join(EXAMPLE, folder, f), os.path.join(tmp, "configs", folder, f))
            paste_drivers(os.path.join(tmp, "configs", "worlds", "outdoor_day.yaml"),
                          os.path.join(EXAMPLE, "worlds", "outdoor_day_driver.yaml"))

            def run(*args):
                r = subprocess.run([sys.executable, *args], cwd=tmp, capture_output=True, text=True, timeout=900)
                self.assertEqual(r.returncode, 0, f"{' '.join(args)}\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}")
                return r.stdout

            run("cli/update_docs.py")
            with open(os.path.join(tmp, "docs", "PRESALES.md")) as fh:
                self.assertIn("| `radiation.dose_rate_usv_h` | `dose_rate_usv_h` | `generic_dose_rate_meter` |", fh.read())
            run("-m", "pytest", "-q", "-p", "no:cacheprovider", *TESTS)
            out = run("cli/generate.py", "--scenario", "radiation_check", "--out", os.path.join(tmp, "out"))
            self.assertIn("gate PASSED", out)
            d = pd.read_csv(os.path.join(tmp, "out", "dose_rate_logger_radiation_check_seed42.csv"))
            self.assertEqual(list(d.columns), ["timestamp", "device_id", "dose_rate_usv_h", "dose_rate_alarm"])
            self.assertLess(d["dose_rate_usv_h"].iloc[:100].median(), 0.3)            # natural background
            self.assertGreater(d["dose_rate_usv_h"].max(), 4)                         # the source
            self.assertGreater(d["dose_rate_alarm"].sum(), 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(sorted(os.listdir(os.path.join(ROOT, "configs", "quantities"))), before)


if __name__ == "__main__":
    unittest.main()
