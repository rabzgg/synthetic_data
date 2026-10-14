# Adding a sensor to the UI

The UI (`ui/app.py`) knows nothing about any sensor. It lists the profiles in
`core/profiles/registry.py` and calls a small interface on them. To add a sensor family, for
example one specified only by a datasheet, write one profile class and register it.

## 1. The interface (`core/profiles/base.py`)

| method | returns | notes |
|---|---|---|
| `scenarios()` | list of scenario ids | what the user can pick, e.g. `"robot_arm_6"` |
| `scenario_label(scenario)` | str | shown in the dropdown (default: the id) |
| `max_duration_s(scenario)` | seconds or `None` | longest output the data supports, e.g. the recording length. The UI allows more, with a warning. `None` = no limit known. |
| `min_duration_s(scenario)` | seconds | default 60 |
| `default_duration_s(scenario)` | seconds | default: 60 min, capped at the maximum |
| `max_attempts(scenario)` | int | > 1 makes the gate a filter: seeds `seed`, `seed+1`, … until one passes (default 1) |
| `generate(scenario, duration_s, seed, out_dir, progress)` | list of CSV paths | write one CSV per sensor into `out_dir`. Call `progress(fraction, text)` if given. |
| `validate(scenario, csv_paths)` | `GateReport` | one `GateCheck` per check: name, sensor, value, threshold, passed, note, informational |
| `limitations(scenario, duration_s)` | list of str | written to the UI and to the ZIP README |
| `plot(scenario, csv_paths, seed, duration_s, out_dir)` | list of PNG paths | optional (default: none) |

`generate_validated`, `readme` and `bundle` (the ZIP) are implemented in the base class. They use
only the methods above.

### `GateReport.status`

| status | meaning | UI |
|---|---|---|
| `passed` / `failed` | a real gate ran | green / red |
| `partial` | only checks that need no real recording ran | blue if they pass, red if not |
| `not_validated` | no gate exists for this scenario | yellow warning |
| `error` | the gate could not run (e.g. real data missing) | red, with the message |

A check with `informational=True` is shown with ⚠️ and does not decide the result.

Never return `passed` for an output nothing has checked. Use `not_validated` instead.

Two real examples: `core/profiles/xdk.py` (recorded data, physics gate, gate as filter) and
`core/profiles/gas.py` (datasheet-only gas detectors, rule gate, one profile per device; scenarios map
to the generator's `forced` events).

## 2. A minimal profile

```python
# core/profiles/my_sensor.py
import os
from .base import NOT_VALIDATED, GateReport, SensorProfile

class MySensorProfile(SensorProfile):
    name = "my_sensor"            # short id, also used in file names
    label = "My sensor (datasheet)"

    def scenarios(self):
        return ["idle", "vibration"]

    def max_duration_s(self, scenario):
        return None                # no recording behind it -> no length limit

    def generate(self, scenario, duration_s, seed, out_dir, progress=None):
        path = os.path.join(out_dir, f"my_sensor_seed{seed}.csv")
        ...                        # call your generator; write the CSV
        return [path]

    def validate(self, scenario, csv_paths):
        # Datasheet-only sensor: check what the datasheet guarantees (range, resolution, rate).
        # Without such checks, say so:
        return GateReport(NOT_VALIDATED, message="No gate for this sensor yet.")

    def limitations(self, scenario, duration_s):
        return ["Generated from datasheet values only; not compared with a real recording."]
```

Register it in `core/profiles/registry.py`:

```python
from .my_sensor import MySensorProfile
PROFILES = {p.name: p for p in (XDKProfile(), MySensorProfile())}
```

## 3. Rules that keep the UI honest

- **Wrap, do not re-implement.** A profile calls the existing generator and gate. The XDK profile
  runs `cli/main.py` in a subprocess with the CLI's arguments, so its files are byte-identical to
  CLI output. Its gate is `validation.physics_gate.check_physics_gate`.
- **Add a test that pins the profile to the CLI path.** See `tests/test_profiles.py`: the same
  inputs through the profile and through the CLI must give identical CSVs and an identical gate
  report.
- **Gate-as-filter needs a gate worth trusting.** Only set `max_attempts > 1` when the gate checks
  physics against real data. The ZIP README states that the output was selected. Passing after
  selection says nothing about how often the generator passes.
- **Put known limitations in `limitations()`**: calibration span, post-hoc margins, unverified
  assumptions (for the arm: sensor → link mapping **[USER TO VERIFY]**). They go into the UI and
  into every ZIP.
- **Real data paths.** If the gate needs a real recording, look for it where the tooling expects it
  first. Then fall back to a copy shipped in `data/` (the XDK profile uses
  `data/arm6/original/*.csv.gz`). If neither exists, return status `error`; do not skip the check.
