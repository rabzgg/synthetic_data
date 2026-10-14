# Gas detector data (datasheet-based)

**What this is:** synthetic data that **obeys the datasheets** (range, resolution, battery runtime) and is **consistent by rule** (alarms, STEL/TWA, simultaneous bump test, announced connection gaps, timestamps).

**What this is not:** it is **not** made to look like field data. No real recording of these devices was available, so nothing here was compared with, or fitted to, real readings. Noise, event shapes, timings, battery drain, signal strength and gaps are assumptions (listed below), not measurements.

- Generator: `core/gas_detector.py` (`python3 cli/generate_gas.py --all`): one 8-h shift per device and seed, seeds 42, 43, 44, 45, 46.
- Rule gate: `validation/gas_gate.py` (`python3 validation/gas_gate.py --all --json data/gas/gate_report.json --readme data/gas/README.md`). It recomputes every rule from the CSV and shares no code with the generator.
- Plots: `plots/<device>_shift_seed<seed>.png` (`python3 cli/plot_gas.py --all`): readings, setpoints, STEL/TWA, alarms, bump test, connection gaps and device state; every label is read from the CSV.
- Specs: `configs/gas/<device>/spec.json`: datasheet values, each with `{value, unit, source}`.
- Assumptions: `configs/gas/assumptions.json`: everything else, each marked `ASSUMPTION` with a reason.

## Gate result per device and seed

**25 of 25 files pass every check.** Full detail per check: `gate_report.json`.

| device | seed 42 | seed 43 | seed 44 | seed 45 | seed 46 |
|---|---|---|---|---|---|
| blackline_g7c | PASS | PASS | PASS | PASS | PASS |
| blackline_g7x_bridge | PASS | PASS | PASS | PASS | PASS |
| blackline_g8 | PASS | PASS | PASS | PASS | PASS |
| msa_altair_io4 | PASS | PASS | PASS | PASS | PASS |
| msa_altair_io6 | PASS | PASS | PASS | PASS | PASS |

Checks on every file: columns, timestamps (steps of 10 s, or an announced gap), connection_gaps, resolution, range, alarm_setpoints, over_range, stel_formula, twa_formula, stel_twa_alarms, bump_simultaneous, alarm_cause, battery, signal, state_values, scenario_content (incl. the coverage-plan items of that seed); pump (io6) and bridge_link (G7x).

## Events per seed

Read from the data by the gate (`inventory`). STEL / TWA / over-range: number of samples with that flag.

| device | seed | bump | exposures (gas) | STEL alarm | TWA alarm | over-range | VOC exp. | pump fault | SOS | gaps | satellite | battery end % |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| blackline_g7c | 42 | 1 | lel, lel, lel | 0 | 0 | 0 | 0 | — | — | 2 | — | 55 |
| blackline_g7c | 43 | 1 | h2s, h2s | 83 | 0 | 0 | 0 | — | — | 1 | — | 55 |
| blackline_g7c | 44 | 1 | co, h2s | 0 | 1575 | 0 | 0 | — | — | 1 | — | 55 |
| blackline_g7c | 45 | 1 | lel, h2s, h2s | 0 | 0 | 9 | 0 | — | — | 3 | — | 55 |
| blackline_g7c | 46 | 1 | lel, h2s, co | 0 | 0 | 0 | 0 | — | — | 3 | — | 55 |
| blackline_g7x_bridge | 42 | 1 | lel | 0 | 0 | 0 | 0 | — | — | 2 | 2 | 55 |
| blackline_g7x_bridge | 43 | 1 | h2s, co, h2s | 84 | 0 | 0 | 0 | — | — | 1 | 2 | 55 |
| blackline_g7x_bridge | 44 | 1 | lel, co, lel | 0 | 1187 | 0 | 0 | — | — | 1 | 1 | 55 |
| blackline_g7x_bridge | 45 | 1 | lel, h2s, lel | 0 | 0 | 10 | 0 | — | — | 2 | 1 | 55 |
| blackline_g7x_bridge | 46 | 1 | h2s, co, h2s | 0 | 0 | 0 | 0 | — | — | 2 | 2 | 55 |
| blackline_g8 | 42 | 1 | h2s | 0 | 0 | 0 | 0 | — | 1 | 3 | — | 55 |
| blackline_g8 | 43 | 1 | lel, h2s | 125 | 0 | 0 | 0 | — | 1 | 1 | — | 55 |
| blackline_g8 | 44 | 1 | co, lel | 0 | 1390 | 0 | 0 | — | 1 | 1 | — | 55 |
| blackline_g8 | 45 | 1 | lel | 0 | 0 | 16 | 0 | — | 1 | 1 | — | 55 |
| blackline_g8 | 46 | 1 | co | 0 | 0 | 0 | 0 | — | 1 | 1 | — | 55 |
| msa_altair_io4 | 42 | 1 | co, co | 0 | 0 | 0 | 0 | — | — | 1 | — | 52 |
| msa_altair_io4 | 43 | 1 | h2s | 120 | 0 | 0 | 0 | — | — | 1 | — | 52 |
| msa_altair_io4 | 44 | 1 | h2s, co | 0 | 1365 | 0 | 0 | — | — | 1 | — | 52 |
| msa_altair_io4 | 45 | 1 | co, co, lel | 0 | 0 | 15 | 0 | — | — | 1 | — | 52 |
| msa_altair_io4 | 46 | 1 | h2s, lel | 0 | 0 | 0 | 0 | — | — | 2 | — | 52 |
| msa_altair_io6 | 42 | 1 | lel, h2s | 112 | 0 | 0 | 0 | 0 | — | 1 | — | 52 |
| msa_altair_io6 | 43 | 1 | co | 0 | 1496 | 0 | 0 | 0 | — | 3 | — | 52 |
| msa_altair_io6 | 44 | 1 | co, lel, voc | 0 | 0 | 16 | 1 | 0 | — | 2 | — | 52 |
| msa_altair_io6 | 45 | 1 | h2s, voc, co | 0 | 0 | 0 | 1 | 0 | — | 3 | — | 52 |
| msa_altair_io6 | 46 | 1 | voc, co, h2s | 0 | 0 | 0 | 1 | 1 | — | 1 | — | 52 |

## Coverage of the 5-seed set

Each item has to appear at least once for every device it applies to. It is placed by the coverage plan (`coverage_plan` in `assumptions.json`), not left to chance; random exposures are always short.

| item | applies to | seeds where it appears |
|---|---|---|
| STEL alarm | all devices | blackline_g7c: 43; blackline_g7x_bridge: 43; blackline_g8: 43; msa_altair_io4: 43; msa_altair_io6: 42 |
| TWA alarm | all devices | blackline_g7c: 44; blackline_g7x_bridge: 44; blackline_g8: 44; msa_altair_io4: 44; msa_altair_io6: 43 |
| over-range | all devices | blackline_g7c: 45; blackline_g7x_bridge: 45; blackline_g8: 45; msa_altair_io4: 45; msa_altair_io6: 44 |
| VOC exposure | msa_altair_io6 | msa_altair_io6: 44, 45, 46 |
| pump fault | msa_altair_io6 | msa_altair_io6: 46 |
| SOS | blackline_g8 | blackline_g8: 42, 43, 44, 45, 46 |

## Columns

`timestamp` (ISO 8601 UTC), `device_id`, `bridge_id`/`bridge_link` (G7x), `gap_before_s` (seconds without rows before this row; 0 normally), gas readings with the unit in the name (`lel_pct_lel`, `o2_pct_vol`, `co_ppm`, `h2s_ppm`, `voc_ppm`), `co_/h2s_stel_ppm` and `_twa_ppm`, `device_mode`, `pump_state`/`pump_alarm` (io6), `sos_state` (G8), `battery_pct`, `signal_strength_dbm`, alarm flags (`<gas>_alarm_low/high/stel/twa`, `<gas>_over_range`; 0/1), and `event`, a ground-truth label written by the generator, not a device field.

## Datasheet sources

| device | source | battery runtime |
|---|---|---|
| Blackline G7c (`blackline_g7c`) | Blackline G7c datasheet R28 | 18 h (Blackline G7c datasheet R28) |
| Blackline G7x with G7 Bridge (`blackline_g7x_bridge`) | Blackline G7x datasheet R21 | 18 h (Blackline G7x datasheet R21) |
| Blackline G8 (`blackline_g8`) | Blackline G8 spec sheet R1 | 18 h (Blackline G8 spec sheet R1) |
| MSA ALTAIR io4 (`msa_altair_io4`) | MSA spec sheet 1708-056 | 17 h (MSA spec sheet 1708-056) |
| MSA ALTAIR io6 (`msa_altair_io6`) | MSA spec sheet 1708-056 (ALTAIR io4 spec sheet) | 17 h (ASSUMPTION: same battery as io4 (io6 battery table not found)) |

- `msa_altair_io6`: LEL/O2/CO/H2S and the pump are taken from the io4 spec sheet: **ASSUMPTION: same sensors as io4** (io6 sensor table not found). VOC (PID) 0-4000 ppm, resolution 0.1: **ASSUMPTION: borrowed from Blackline PID (G7c R28); io6 PID table not found**. Battery: **ASSUMPTION: same as io4**.
- G7x and G8 gas ranges equal the G7c values; the reviewer checked this against the G7x and G8 datasheets.

## Assumptions (not in the datasheets)

Every entry is marked `ASSUMPTION` in `configs/gas/assumptions.json`.

| assumption | value | unit | reason |
|---|---|---|---|
| `logging_interval_s` | `10` | s | Datasheets give no logging interval; 10 s as set in the task brief. |
| `shift.start_utc` | `"2026-01-05T06:00:00Z"` | ISO 8601 UTC | Arbitrary shift start; no real data to anchor to. |
| `shift.duration_s` | `28800` | s | One 8-hour shift, as set in the task brief. |
| `clean_air_baseline` | `{"lel": 0, "o2": 20.9, "co": 0, "h2s": 0, "voc": 0}` | channel units | Normal air: no combustible or toxic gas, 20.9 %vol O2. Not from the datasheets. |
| `measurement_noise_sd` | `{"lel": 0.3, "o2": 0.03, "co": 0.3, "h2s": 0.05, "voc": 0.1}` | channel units | No noise specification given. Small Gaussian noise so clean air reads at or next to the baseline at the stated resolution. Not a field noise model. |
| `alarm_setpoints` | `{"lel": {"low": 10, "high": 20}, "o2": {"low": 19.5, "high": 23.5}, "co": {"low": 25, "high": 100}, "h2s": {"low": 10, "high": 15}, "voc": {"low": 50, "high": 100}}` | channel units | Not in the provided datasheets. Placeholder of a typical order of magnitude; replace with the setpoint configured on the real device. |
| `alarm_rule` | `{"default": "alarm when value >= setpoint", "o2_low": "alarm when value <= setpoint (oxygen deficiency)", "over_range": "over_range when value >= range_max", "latching": false}` | - | Brief: alarm = value >= threshold. For O2 the low alarm is a deficiency alarm, so it triggers at or below the setpoint. Alarms are modelled as non-latching (they clear when the value does). |
| `exposure_limits` | `{"co": {"stel": 200, "twa": 25}, "h2s": {"stel": 15, "twa": 10}}` | ppm | Not in the provided datasheets. Placeholder of a typical order of magnitude; replace with the setpoint configured on the real device. STEL/TWA are only computed for CO and H2S. |
| `stel_rule` | `{"window_s": 900, "pre_shift": "samples before the shift start count as 0 (window always divided by its full length)", "rounding": "rounded to the channel resolution"}` | - | Brief: STEL = rolling 15-min mean. How the first 15 min are handled is not specified; zero-fill chosen. |
| `twa_rule` | `{"period_s": 28800, "formula": "sum(value * logging_interval) from shift start / 28800 s", "rounding": "rounded to the channel resolution"}` | - | Brief: TWA = 8-h average. Computed as the accumulated dose divided by 8 h (the 8-h TWA of the shift so far), not as a mean over the elapsed time. |
| `t90_s` | `{"lel": 20, "o2": 15, "co": 30, "h2s": 30, "voc": 15}` | s | No response times given. Sensor response is modelled as first order with time constant T90 / ln(10). |
| `recovery_factor` | `3.0` | x rise time constant | Brief: the value falls more slowly than it rises. Fall time constant = 3 x rise time constant. |
| `bump_test.gas_mix` | `{"lel": 50, "h2s": 25, "co": 100, "o2": 18}` | %LEL / ppm / ppm / %vol | Example mix from the task brief. VOC is not in the mix, so it stays at baseline during the bump test. |
| `bump_test.start_after_s` | `120` | s | Bump test at the start of the shift, 2 min after power-on. |
| `bump_test.gas_applied_s` | `60` | s | Test gas applied for 60 s, then removed. |
| `exposure.count_per_shift` | `[1, 3]` | events (min, max) | Brief: 1-3 exposures per shift. Drawn uniformly. |
| `exposure.gases` | `["lel", "co", "h2s", "voc"]` | - | Combustible and toxic gases (VOC on io6 only); O2 deficiency events are not modelled. |
| `exposure.peak` | `{"lel": [5, 25], "co": [20, 150], "h2s": [3, 20], "voc": [20, 200]}` | channel units (min, max) | Peak levels drawn uniformly; ranges chosen so that some exposures cross the alarm setpoints. |
| `exposure.plateau_s` | `[120, 600]` | s (min, max) | Duration at the peak level, drawn uniformly. |
| `exposure.types` | `{"short": {"gas": "any exposure gas", "peak": "exposure.peak", "plateau_s": "exposure.plateau_s"}, "sustained_stel": {"gas": "h2s", "peak": [20, 30], "plateau_s": [900, 1500]}, "prolonged_twa": {"gas": "co", "peak": [55, 70], "plateau_s": [14400, 18000]}, "over_range": {"gas": "lel", "peak": [110, 130], "plateau_s": [60, 180]}, "voc": {"gas": "voc", "peak": "exposure.peak.voc", "plateau_s": "exposure.plateau_s"}}` | ppm / %LEL, s | Random exposures are always 'short'. The other types are placed only by the coverage plan: a sustained H2S exposure that crosses the 15-ppm STEL, a long CO exposure whose 8-h TWA crosses 25 ppm, and an LEL peak above the 100 %LEL range. |
| `sos.count_per_shift` | `1` | events | Brief: one SOS on the G8 in every shift. Independent of the gas readings. |
| `sos.duration_s` | `[60, 300]` | s (min, max) | SOS active time, drawn uniformly. |
| `state_values` | `{"device_mode": ["normal", "bump_test"], "pump_state": ["on", "fault"], "sos_state": [0, 1]}` | - | No state logging format given. pump_state is 'on' except during a pump fault; sos_state is 0/1. |
| `identifiers` | `{"device_id": "<DEVICE>-0001", "bridge_id": "BRIDGE-0001"}` | - | Synthetic identifiers. |
| `event_label` | `"event column: none \| bump_test \| exposure_<gas>"` | - | Ground-truth label written by the generator, not a device field. The gate uses it to check that every alarm has a cause. |
| `battery` | `{"start_pct": 100, "model": "linear drain over the datasheet runtime", "rounding": "floor to 1 %"}` | % | Datasheets give runtime only. Battery starts full and drains linearly: pct = floor(100 - 100 * t / runtime). Over an 8-h shift that is 47 % (17 h) or 44 % (18 h). |
| `signal_strength` | `{"range_dbm": [-115, -55], "start_dbm": [-90, -70], "step_sd_db": 1.0, "rounding": "integer dBm"}` | dBm | No signal specification given. Bounded random walk, one step per logging interval. Reported by every device. |
| `bridge_link` | `{"satellite_periods_per_shift": [1, 2], "satellite_duration_s": [600, 2400]}` | - | The G7x datasheet allows cellular and satellite links; how often a Bridge switches is not given. The link is cellular, with 1-2 satellite periods per shift. |
| `connection_gaps` | `{"count_per_shift": [1, 3], "duration_s": [30, 300], "not_before_s": 600, "marker": "gap_before_s on the first row after a gap = seconds without rows (0 elsewhere)", "data_during_gap": "lost (not buffered); the device keeps measuring, so STEL/TWA still include the gap"}` | - | Periods without rows, as from a lost connection. Each gap is announced on the next row so that the gate can tell an intended gap from a row lost to a bug. No gap during the bump test. |
| `pump_fault` | `{"duration_s": [120, 600], "readings": "unchanged (flag only)", "alarm": "pump_alarm = 1 while pump_state is fault"}` | - | No pump fault behaviour given. A fault sets pump_state to 'fault' and raises pump_alarm; the gas readings are not altered. |
| `coverage_plan` | `{"seeds": [42, 43, 44, 45, 46], "items": {"default": ["sustained_stel", "prolonged_twa", "over_range"], "msa_altair_io6": ["sustained_stel", "prolonged_twa", "over_range", "voc", "pump_fault"]}, "rule": "item k goes to seed seeds[k + 1] (io6: seeds[k]); it replaces one random exposure (pump_fault is added on top). SOS is in every G8 shift."}` | - | The review asks that the 5-seed set contains each of: STEL alarm, TWA alarm, over-range, VOC exposure (io6), pump fault (io6), SOS (G8). Random draws do not guarantee that, so each item is placed on one seed. Seed 42 stays a plain random shift on every device except io6, which needs all five seeds. |
