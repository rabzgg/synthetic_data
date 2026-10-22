# Architecture (one page)

**In one sentence:** a *world* holds the physical truth over time, *events* change that world or a
device, every *device* measures the world with sensors described by their datasheets, its *logic*
turns readings into alarms and states, and a *gate* checks the result against the spec. Adding a
sensor, quantity, world, event or scenario is a YAML file; Python is only needed for a new kind of
physics.

```
 configs/quantities  configs/units.yaml          what can be measured, in which unit
          │
 configs/parts ──► configs/devices ◄── logic blocks       a sensor from its datasheet; a device = parts + logic
          │               │
 configs/worlds ──► World ◄── configs/events ◄── configs/scenarios      truth over time; what happens; a run
          │               │
          └──────► measurement ──► logic ──► logging ──► CSV + labels + manifest ──► gate
```

## The six blocks

| block | what it is | where (data) | where (code) |
|---|---|---|---|
| A quantities | id, unit, physical bounds, CSV column; unit spellings and conversions | `configs/quantities/*.yaml`, `configs/units.yaml` | `core/quantities/catalog.py`, `units.py` |
| B parts | one sensor from its datasheet: per quantity range, resolution, accuracy (typical or max), noise, t90, drift, … each with its source | `configs/parts/*.yaml` | `core/quantities/measurement.py` (one generic measurement model), `normalize.py` (datasheet wording → parameters) |
| C devices | parts + logging interval + logic blocks, named by the user, versioned | `configs/devices/*.yaml` | `core/devices/` |
| D worlds | signals and drivers built from primitives; relations (RH, O2, pressure, body motion) derived | `configs/worlds/*.yaml` | `core/world/` (`primitives.py`, `physics.py`, `motion.py`, `world.py`) |
| E events | effects on world nodes, the body's motion or a device; composites | `configs/events/*.yaml`, `configs/scenarios/*.yaml` | `core/events/` (`library.py` is the one engine) |
| F output | device logic, logging, files, gate | blocks listed in the device file | `core/logic/`, `core/output/run.py`, `validation/auto_gate.py` |

## A run, step by step

1. **World.** Every signal and driver of the world file is evaluated on a time grid (air: 1 s, body:
   25 Hz). Event effects are applied to their target node right after it is computed, so everything
   that refers to it follows (a compressor that stops cools nothing and draws no current).
2. **Relations.** RH from temperature and water vapour, O2 from the gases, pressure from altitude,
   acceleration and rotation from one description of the body's motion. A relation is only computed
   when its inputs exist in the world.
3. **Measurement.** Each part measures the world at the device's mount (worn on the body or fixed),
   through the same chain of stages for every quantity: frame → cross-sensitivity → response (t90) →
   bandwidth → bias and drift (drawn once per unit) → noise → hysteresis → deadband → resolution →
   range. Details: `docs/PARAMETER_MAPPING.md`.
4. **Logic.** Blocks such as `threshold_alarm`, `rolling_mean` (STEL), `cumulative_dose` (TWA),
   `stillness_timer` (no motion), `spike_then_still` (fall), `battery`, `signal` write the other
   columns. The motion blocks also run on the world's truth to give the *expected* labels.
5. **Logging.** One row every `sample_interval_s`; no rows during a connection loss.
6. **Files and gate.** `<device>_<scenario>_seed<n>.csv` (clean), `_labels.csv` (ground truth),
   `_manifest.json` (every parameter with its source, the world's defaults, the events, the code
   version), `_gate.json`. The gate is derived from the spec in the manifest and recomputes what it
   can from the CSV.

## Rules the code keeps

- Every number in a config is `{value, unit, source}`; the source starts with `datasheet` or
  `ASSUMPTION`. Unverified values carry `[USER TO VERIFY]`.
- Events never write a CSV column; they change the world or a device, and the columns follow.
- An event that no device in a run can see (it changes nothing a device measures by at least that
  sensor's resolution) is refused with the reason.
- The gate never borrows the generator's code paths; it reads the spec and the CSV.

## Commands

```bash
pip install -r requirements.txt
python3 cli/generate.py --scenario worker_collapse --seed 42 --out out/collapse     # one run, all files
python3 validation/run_all_scenarios.py                                            # every scenario, 5 seeds
python3 cli/plot_world.py --preset water_tank --hours 24                           # look at a world
python3 cli/events_doc.py && python3 cli/parameter_mapping.py                      # regenerate the docs
python3 -m unittest discover -s tests
```

## What still needs Python

A new relation between quantities (e.g. dew point from water temperature), a new kind of body
motion (e.g. running), a new primitive or effect operation, a new logic block. Everything else is a
file: see `HOW_TO_ADD_A_SENSOR.md`, `HOW_TO_ADD_A_WORLD.md`, `HOW_TO_ADD_AN_EVENT.md`.
