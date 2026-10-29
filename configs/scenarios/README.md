# configs/scenarios: ready-made runs

A scenario puts the pieces together for one run: an environment (`configs/worlds/`), the devices in
it and where they sit (`configs/devices/`), and the events with their times and values
(`configs/events/`). It also fixes the duration and the random seed, so the same scenario and seed
always give the same files.

Scenarios are what `python3 cli/generate.py --scenario <name>` runs, what the app shows under
"Example scenarios", and what `validation/run_all_scenarios.py` checks on five seeds. The other two
ways into the app ("Start from columns", "Build a device") build the same thing from a form, without
a file.

## The files

| file | title | environment | length | devices | events |
|---|---|---|---|---|---|
| `fridge_compressor_failure.yaml` | Fridge compressor failure | fridge | 24 h | fridge_logger | compressor failure |
| `server_room_ac_failure.yaml` | Server room AC failure | server_room | 24 h | rack_monitor | AC failure for 45 min |
| `pump_bearing_wear.yaml` | Pump bearing wear | pump_room | 96 h | pump_vibration_sensor | bearing wear |
| `water_tank_leak.yaml` | Water tank leak | water_tank | 48 h | water_tank_monitor | leak |
| `field_irrigation.yaml` | Field irrigation | field_day | 72 h | soil_moisture_probe | irrigation |
| `worker_collapse.yaml` | Worker collapse in H2S | indoor_worker_walking | 2 h | blackline_g7c (worn), bme280_sensor_board (fixed) | bump test, collapse, connection loss |
| `gas_normal_shift.yaml` | Normal shift | indoor_worker_walking | 8 h | blackline_g7c | bump test, 1 to 3 gas releases, connection gaps, SOS |
| `gas_stel_alarm.yaml` | Test: STEL alarm (H2S) | indoor_worker_walking | 8 h | blackline_g7c | as normal shift, plus an H2S exposure long enough for the STEL alarm |
| `gas_twa_alarm.yaml` | Test: TWA alarm (CO) | indoor_worker_walking | 8 h | blackline_g7c | as normal shift, plus a long CO exposure for the TWA alarm |
| `gas_over_range.yaml` | Test: LEL over-range | indoor_worker_walking | 8 h | blackline_g7c | as normal shift, plus LEL above the sensor's range |
| `gas_voc_exposure.yaml` | Test: VOC exposure | indoor_worker_walking | 8 h | msa_altair_io6 | as normal shift, plus a VOC exposure |
| `gas_pump_fault.yaml` | Test: pump fault | indoor_worker_walking | 8 h | msa_altair_io6 | as normal shift, plus a sampling pump fault |

The `gas_*` scenarios were rewritten from the older gas detector engine (`configs/gas/assumptions.json`).

## What one file looks like

`worker_collapse.yaml`:

```yaml
name: worker_collapse
title: "Worker collapse in H2S"
description: "H2S rises to 100 ppm and the worker falls after a minute. ..."
realism: ASSUMPTION
world: indoor_worker_walking
duration: 2h
seed: 42
devices:
  - {device: blackline_g7c, mount: body}
  - {device: bme280_sensor_board, mount: fixed, height_m: 1.0}
events:
  - bump_test: {at: "00:02:00"}
  - collapse: {at: "00:40:00", gas: h2s, level: 100, ramp_s: 30, duration_min: 30, fall_after_s: 60, no_motion_after_s: 20, no_motion_min: 10}
  - connection_loss: {at: "01:20:00", duration_s: 70}
```

| key | required | meaning |
|---|---|---|
| `name` | yes | equal to the file name |
| `title`, `description` | no | shown in the app |
| `realism` | yes | `ASSUMPTION` or `recorded` |
| `world` | yes | a file name from `configs/worlds/` |
| `duration` | yes | `2h`, `24h`, `90min`, or seconds |
| `seed` | yes | the random seed (`run_all_scenarios.py` also runs 43 to 46) |
| `devices` | yes | the devices and how they are mounted (below) |
| `events` | no | what happens, in any order (below) |

## `devices`

| key | meaning |
|---|---|
| `device` | a file name from `configs/devices/` |
| `mount` | `body` (worn by the person, moves with them, sees falls) or `fixed` (on a wall, shelf or machine) |
| `height_m` | height above the floor for a fixed device (pressure depends on it). Default 1 m. |
| `heading_deg` | which way a fixed device faces (for the magnetometer). Default 0, north. |

`python3 cli/generate.py --scenario <name> --devices <device>:fixed` replaces the scenario's
devices for one run, to try a new device without writing a scenario.

## `events`

Each entry is `<event kind>: {parameters}`. Parameters left out take the defaults from the event
file.

| key | meaning |
|---|---|
| `at` | when it starts: seconds, `"HH:MM:SS"` from the start of the run, or `"20min"` |
| any parameter of the event | for example `level`, `gas`, `duration_s`. A parameter written `_min` or `_h` (`duration_min: 30`) is read as the `_s` one. |
| `count` | how many of this event (can be random) |
| `spacing_s` | the smallest gap between two events of this kind |
| `devices` | for a device event: which devices it goes to (default: all that can show it) |
| `optional` | `true`: skip it, with a note, on devices that cannot show it (a scenario written for several device types) |

Random values, drawn from the seed:

| write | gives |
|---|---|
| `{random: [lo, hi]}` | a number between lo and hi (also times: `["00:10:00", "07:55:00"]`) |
| `{random_int: [lo, hi]}` | a whole number |
| `{choice: [a, b, c]}` | one of the list |
| `{choice_measured: [lel, co, h2s]}` | one of the list that some device of the run measures |
| `{by_gas: {h2s: ..., co: ...}}` | a value that depends on the chosen gas |

Each can carry its own `source`. Example from `gas_normal_shift.yaml`:

```yaml
events:
  - gas_release:
      count: {random_int: [1, 3], source: "ASSUMPTION: 1 to 3 exposures per shift"}
      at: {random: ["00:17:00", "07:15:00"], source: "ASSUMPTION: after the bump test"}
      spacing_s: 1800
      gas: {choice_measured: [lel, co, h2s, voc], source: "ASSUMPTION: combustible and toxic gases"}
      level:
        by_gas: {lel: {random: [5, 25]}, co: {random: [20, 150]}, h2s: {random: [3, 20]}, voc: {random: [20, 200]}}
        source: "ASSUMPTION: some exposures cross the alarm setpoints"
      duration_s: {random: [120, 600], source: "ASSUMPTION: time at the peak level"}
```

An event that no device of the run can see is refused with the reason ("changes nothing this device
measures", "the device is fixed, the event moves the body").

## What a run writes

Per device, in the output folder:

| file | holds |
|---|---|
| `<device>_<scenario>_seed<n>.csv` | the data |
| `..._labels.csv` | every event with start, end and detail, and what the device should have done (expected alarms) |
| `..._manifest.json` | every parameter that went into the run, with its source |
| `..._gate.json` | every check, its value and its limit |
| `..._summary.json` | per column: rows, rate, unit, min, max, bits, noise, ODR |

The app also draws one figure per device from these files (`core/output/plot.py`).

## Adding a scenario

1. Pick the world, the devices and the events. The world must provide what the devices measure.
2. Write `configs/scenarios/<name>.yaml` with `name` equal to the file name.
3. Run it: `python3 cli/generate.py --scenario <name> --out out/<name>` and read
   `_gate.json` (every check passed?) and the CSV. The app shows the plot.
4. It appears in the app under "Example scenarios" by itself.
5. To include it in the five-seed check, add its name to the `SCENARIOS` list at the top of
   `validation/run_all_scenarios.py`, then run that script. It rewrites `docs/GATE_RESULTS.md`.
6. `python3 cli/events_doc.py` (the scenario list in `docs/EVENTS.md`), then `python3 -m pytest -q`.
