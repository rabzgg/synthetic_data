# Synthetic Sensor Data Generator

Generates synthetic sensor data for **any domain** (gas detectors and workers, fridges, pumps, tanks,
fields, …) from what is known about the sensors: their datasheets. A *world* holds the physical truth,
*events* change it, *devices* built from datasheet *parts* measure it, their *logic* raises alarms,
and a *gate* derived from the spec checks every file. Sensors, quantities, worlds, events and
scenarios are YAML files; adding one needs no Python.

## Handover checklist

- [ ] **Install:** `python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt` (Python ≥ 3.10).
- [ ] **Check:** `python3 -m unittest discover -s tests` (about 2 min, all pass).
- [ ] **Generate (one command):** `python3 cli/generate.py --scenario worker_collapse --seed 42 --out out/collapse`
      → CSV, labels, manifest, gate and summary per device; `--list` shows the scenarios.
- [ ] **All scenarios + gate summary:** `python3 validation/run_all_scenarios.py` → `docs/GATE_RESULTS.md`.
- [ ] **UI:** `streamlit run ui/app.py --server.address 127.0.0.1` (`docs/UI.md`).
- [ ] **Pre-sales (columns first, sensor later, CSV last):** `docs/PRESALES.md`: picture a client's
      dataset before their CSV exists; one generic part per quantity, a device from the client's
      columns, raw counts, noise that follows the sample rate, and a data summary.
- [ ] **Add a sensor:** a part file from the datasheet, then a device file → `docs/HOW_TO_ADD_A_SENSOR.md`
      (first draft with an LLM: `docs/prompts/DATASHEET_TO_PART.md`; check every page it cites).
- [ ] **Add a world:** signals and drivers from primitives → `docs/HOW_TO_ADD_A_WORLD.md`.
- [ ] **Add an event or scenario:** effects on world nodes, the body or a device → `docs/HOW_TO_ADD_AN_EVENT.md`.
- [ ] **Overview:** `docs/ARCHITECTURE.md` (one page).
- [ ] **Open decisions (owner):** merging `feature/lego-generator` into `main`; what happens to the XDK
      data and code (kept unchanged until then).
- [ ] **Part still `[USER TO VERIFY]`:** `configs/parts/maxim_max44009.yaml` was written without its
      datasheet (search snippets and distributor listings only). It needs the datasheet PDF and a pass with
      `docs/prompts/DATASHEET_TO_PART.md`, then a check of every cited page. No preset device uses it.

## Install
```bash
pip install -r requirements.txt        # Python >= 3.10
```

## Generate
```bash
python3 cli/generate.py --list                                              # the scenarios
python3 cli/generate.py --scenario worker_collapse --seed 42 --out out/collapse
python3 validation/run_all_scenarios.py                                     # all scenarios, 5 seeds, gate summary
python3 -m unittest discover -s tests
```
Per device: `<device>_<scenario>_seed<n>.csv` (clean), `_labels.csv` (what happened and what the
device should do), `_manifest.json` (every parameter with its datasheet page or ASSUMPTION),
`_gate.json`, `_summary.json` (per column: rows, sample rate, bits, min, max, noise / resolution, ODR,
generic or not). Current gate results: `docs/GATE_RESULTS.md`.

All worlds are labelled `realism: ASSUMPTION`: no real recording was used to build them. The data obey
the datasheets and the stated rules; they are not fitted to field data.

## UI
```bash
streamlit run ui/app.py --server.address 127.0.0.1
```
Pick a scenario, or build a device from parts, name it, choose a world and the events it can see,
generate, look at plots and the gate, download a ZIP. See `docs/UI.md`.

## Docs
- `docs/ARCHITECTURE.md`: the six blocks and a run, on one page
- `docs/HOW_TO_ADD_A_SENSOR.md`, `docs/HOW_TO_ADD_A_WORLD.md`, `docs/HOW_TO_ADD_AN_EVENT.md`
- `docs/prompts/DATASHEET_TO_PART.md`: LLM prompt for a first draft of a part file (with page numbers)
- `docs/prompts/EXTEND.md`: Claude Code prompt to add a missing column, sensor, environment or event (form + NO2 example)
- `docs/PARAMETER_MAPPING.md`, `docs/EVENTS.md`: generated references
- `configs/gas/`, `core/gas_detector.py`, `validation/gas_gate.py`: the earlier gas detector engine, kept for parity checks

## Legacy: Bosch XDK robot arm (joint template)

Obsolete since 2026-10; kept as it was. It generates XDK CSVs that reproduce real robot-arm
recordings by replaying real arm cycles, checked by a physics gate. Sensor → arm-link mapping:
**[USER TO VERIFY]**.

### Generate (one sensor, 60 min, seed 42)
```bash
python3 cli/main.py --config configs/robot_arm_6/sensor_1_joint.json \
    --output out/sensor_1_seed42.csv --duration 3600 --seed 42 --no-physics-gate
```
Use the same `--seed` and `--duration` for every sensor so that they share one cycle schedule.

### Run the physics gate
```bash
cli/run_robot_arm_joint.sh 42 3600 out/arm6 configs/robot_arm_6     # all six sensors + full gate
python3 validation/regression_arm.py --config-dir configs/robot_arm_6 --seeds 42 43 44 45 46
python3 -m unittest discover -s tests
```
The gate reads the real recordings from the path stored in the bank (`ppt/arm_robot/`); copies
are in `data/arm6/original/`.

### Validation status (2026-10-13)
| bank | gate (blocking checks) | notes |
|---|---|---|
| six sensors, `configs/robot_arm_6` | **12/15 seeds pass** (3/5 + 9/10 held-out) | all 3 failures: omega p99 of sensor_6 (40.77–40.85 vs ≥ 40.89 °/s). 7a passes with a 0.02 margin **set post hoc**; without it 4–7 pairs per seed are below the statistical bound |
| three sensors, `configs/robot_arm` | 15/15 seeds pass (5 + 10 held-out) | |
| both | C2ST is reported, not blocking | a classifier still separates synthetic from real (0.54–0.71), mainly by accel and mag |

Details: `results/joint_template/arm6/README.md` (six sensors), `results/joint_template/`.

### Layout and docs (legacy)
`core/` engine · `cli/` generate and build · `validation/` physics gate and thresholds ·
`experiments/` ablations and evaluation · `configs/` configs, banks, thresholds ·
`data/arm6/` real + synthetic CSVs (`.csv.gz`) and plots · `results/` final gate outputs.

- `docs/PHYSICS_REPORT.md`: physics validation and its history
- `docs/USAGE.md`: full usage (config fitting, anomalies, all options)
- `docs/ENGINES.md`, `docs/ENGINE_MAP.md`: engines per column
- `docs/EVAL.md`: statistical evaluation
- `docs/CHANGELOG.md`: repo cleanup, list of files removed from the tree
