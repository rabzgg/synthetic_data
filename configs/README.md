# configs: everything the generator knows, as YAML

The generator's engine lives in `core/`, and it knows nothing about any particular sensor, room or
event. Every sensor, device, environment, event and scenario is a YAML file in this folder. To add
one, add a file. In most cases no Python is needed.

Each subfolder has its own README with the full list of its files and every key a file can use.

## The folders

| folder | one file is | on screen (the app) it is called | read by |
|---|---|---|---|
| `quantities/` | a group of physical quantities a sensor can measure (temperature, H2S, acceleration) | the column list in step 1 | `core/quantities/catalog.py` |
| `parts/` | one sensor, from its datasheet (Bosch BME280) or a typical sensor of a class (Generic) | the sensor list in step 3 | `core/devices/parts.py` |
| `devices/` | a product: parts plus logging interval, alarms and other logic (Blackline G7c) | the device a run writes a CSV for | `core/devices/device.py` |
| `worlds/` | an environment: what the true values do over time (a fridge, a pump room, outdoors) | environment, step 2 | `core/world/world.py` |
| `events/` | something that happens (gas release, fall, AC failure, leak) | events, step 5 | `core/events/library.py` |
| `scenarios/` | a ready-made run: one environment, its devices and a list of events | Example scenarios | `core/events/scenario.py` |
| `units.yaml` | unit spellings and conversions (Pa to hPa, °F to °C) | not shown | `core/quantities/units.py` |

Not used by the new generator (kept unchanged until the owner decides):

| folder | what it is |
|---|---|
| `gas/` | the older gas detector engine (`core/gas_detector.py`): `spec.json` per detector and `assumptions.json`. The gas parts and devices in `parts/` and `devices/` were rebuilt from these numbers, and `tests/test_devices.py` checks they still match. |
| `robot_arm/`, `robot_arm_6/` | the older XDK robot arm engine (`core/joint_template.py`): fitted joint banks and gate thresholds from real recordings. Do not edit. |

## How the pieces fit together

```
quantities   what can be measured           air.temperature_c (°C, column temperature_c)
   |
parts        how one sensor measures it      bosch_bme280: range, resolution, accuracy, noise, t90
   |
devices      parts + interval + logic        fridge_logger: DS18B20 + current clamp, every 60 s, alarm above 8 °C
   |
worlds       the true values over time       fridge: compressor cycles, inside about 5 °C
   |
events       changes to the world or device  compressor_failure: compressor off, inside warms up
   |
scenarios    world + devices + events        fridge_compressor_failure: 24 h, seed 42
```

One run goes: the world makes the true values, events change them, every part of every device
measures them with its own errors, the device logic adds alarm and state columns, and the files are
written (CSV, labels, manifest, checks, summary). The checks (`validation/auto_gate.py`) are derived
from the same files, so a new part or device gets its checks without extra work.

## The one rule for numbers

Every number is written as `{value, unit, source}`:

```yaml
resolution: {value: 0.01, unit: "°C", source: "datasheet BST-BME280-DS001-23 p.9"}
t90_s: {value: 60, unit: s, source: "ASSUMPTION: a small IC inside a vented housing in still air"}
```

- `source` starts with `datasheet` (document, revision, page) or `ASSUMPTION` (with the reason).
- A page that was not checked is never invented. Write `(page not recorded)` and `[USER TO VERIFY]`.
- A bare number (`resolution: 0.01`) is refused when the file loads.
- The unit can be any spelling in `units.yaml`. It is converted to the quantity's own unit.
- In the app, ASSUMPTION is shown as "assumed" and `[USER TO VERIFY]` as "not verified yet".

## I want to...

### ...add a sensor for something that is already measured

Example: a sensor X that measures air temperature, so that step 3 offers Generic, sensor X, Bosch
BME280 and Maxim DS18B20.

1. Write `configs/parts/<vendor>_<model>.yaml` from the datasheet (see `parts/README.md`).
2. That is all. The app lists every part that measures a quantity, so sensor X appears in step 3
   for that column and in the sensor list of "Build a device". The list is Generic first, then the
   other parts sorted by file name.
3. Optional: a device that uses it, `configs/devices/<name>.yaml` (see `devices/README.md`).
4. Run the checks below.

### ...add a new measurement (example: radioactivity)

This is the case where the quantity does not exist yet. The steps below were tried end to end with
a gamma dose rate in µSv/h: the column appeared in the app under "Radiation", the Outdoors
environment was offered, the sensor list showed Generic and the named test part, and the run passed
its checks.

1. **The quantity.** Add a new domain file `radiation.yaml` in `configs/quantities/` (or an entry in an
   existing one):
   ```yaml
   domain: radiation
   quantities:
     - {id: radiation.dose_rate_usv_h, name: Gamma dose rate, unit: "µSv/h", column: dose_rate_usv_h, lower: 0, upper: null,
        note: "Ambient dose equivalent rate. Natural background is about 0.05 to 0.3 µSv/h."}
   ```
   A new domain becomes a new group in step 1 of the app ("Radiation").
2. **Its generic part.** Every quantity needs exactly one generic part, used when the client has
   not named a sensor: `generic_dose_rate_meter.yaml` in `configs/parts/` with `generic_for:
   radiation.dose_rate_usv_h` and a `class` (see `parts/README.md`, "Generic parts"). All values are
   ASSUMPTION, and it may not be better than the best named part for that quantity.
3. **Where it exists.** Add a driver for the quantity to every environment where it makes sense,
   for example `configs/worlds/outdoor_day.yaml` (see `worlds/README.md`):
   ```yaml
   drivers:
     radiation.dose_rate_usv_h:
       sum:
         - constant: {value: 0.1, unit: "µSv/h", source: "ASSUMPTION: natural background outdoors"}
         - random_walk: {mean: {value: 0, unit: "µSv/h", source: "ASSUMPTION: around the level"},
                         sd: {value: 0.01, unit: "µSv/h", source: "ASSUMPTION: small natural variation"},
                         tau_s: {value: 600, unit: s, source: "ASSUMPTION: changes over minutes"}}
   ```
   An environment without a driver for the quantity is not offered for it. If no environment fits,
   write a new one.
4. **Named sensors** (optional, when a datasheet exists): `configs/parts/<vendor>_<model>.yaml`.
5. **Events** (optional): for example `radiation_source.yaml` in `configs/events/`, a source brought near
   the device, as an `add` of a `pulse` on `radiation.dose_rate_usv_h` (see `events/README.md`).
6. **Three bookkeeping steps outside this folder** (the tests fail until they are done):
   - one row in the generic table of `docs/PRESALES.md` (`tests/test_generic_parts.py`)
   - one test fixture line in `FIXTURES` at the top of `tests/test_quantities.py`: a simple range,
     resolution, accuracy and noise, and a typical true value. This is test data, not engine code.
   - `python3 cli/parameter_mapping.py` to regenerate `docs/PARAMETER_MAPPING.md`
7. Run the checks below.

Only a new kind of physics needs Python: a relation between quantities (like RH from temperature
and vapour), a new primitive, a new kind of body motion or a new logic block. Ask before writing it.

### ...add a device

Write `configs/devices/<name>.yaml` with its parts, logging interval and logic (see
`devices/README.md`). A device saved in the app ("Save this device") lands here too.

### ...add an environment, an event or a scenario

See `worlds/README.md`, `events/README.md` and `scenarios/README.md`.

### ...let Claude Code do it

`docs/prompts/EXTEND.md` is a ready prompt: fill in the form (what is measured, unit, column,
interval, sensor, datasheet, environment, events) and Claude Code checks what exists, adds only what
is missing and runs the checks.

## Checks after any change

```bash
python3 -m pytest -q                         # all tests
python3 validation/run_all_scenarios.py      # every scenario on 5 seeds, writes docs/GATE_RESULTS.md
python3 cli/events_doc.py                    # after a new event, device or scenario: docs/EVENTS.md
python3 cli/parameter_mapping.py             # after a new quantity: docs/PARAMETER_MAPPING.md
streamlit run ui/app.py                      # look at it in the app
```

The tests load every file in this folder, so a missing source, an unknown key or a wrong unit is
reported with the file name.

Longer guides: `docs/HOW_TO_ADD_A_SENSOR.md`, `docs/HOW_TO_ADD_A_WORLD.md`,
`docs/HOW_TO_ADD_AN_EVENT.md`, `docs/PRESALES.md`, `docs/ARCHITECTURE.md`.
