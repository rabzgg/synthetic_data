# Gas detector data (datasheet-based)

**What this is:** synthetic data that **obeys the datasheets** (range, resolution) and is **consistent by rule** (alarms, STEL/TWA, simultaneous bump test, timestamps).

**What this is not:** it is **not** made to look like field data. No real recording of these devices was available, so nothing here was compared with, or fitted to, real readings. Noise, event shapes and timings are assumptions (listed below), not measurements.

- Generator: `core/gas_detector.py` (`python3 cli/generate_gas.py --all`), one 8-h shift per device, seed 42.
- Rule gate: `validation/gas_gate.py` (`python3 validation/gas_gate.py --all --json data/gas/gate_report.json --readme data/gas/README.md`). The gate recomputes every rule from the CSV; it shares no code with the generator.
- Specs: `configs/gas/<device>/spec.json`: only datasheet values, each with `{value, unit, source}`.
- Assumptions: `configs/gas/assumptions.json`: everything else, each marked `ASSUMPTION` with a reason.

## Summary

- Rule gate: **5 of 5 devices pass every check.**
- What these shifts do not exercise (the checks still run and confirm there is no false alarm): STEL alarms 0, TWA alarms 0, over-range samples 0; the Bridge link stays on cellular. Unit tests (`tests/test_gas.py`) force an over-range exposure and a STEL alarm and check that the gate still passes, and corrupt files one rule at a time to check that it fails.

## Files

| file | device | rows | gate |
|---|---|---|---|
| `blackline_g7c_shift_seed42.csv` | Blackline G7c | 2880 | PASS |
| `blackline_g7x_bridge_shift_seed42.csv` | Blackline G7x with G7 Bridge | 2880 | PASS |
| `blackline_g8_shift_seed42.csv` | Blackline G8 | 2880 | PASS |
| `msa_altair_io4_shift_seed42.csv` | MSA ALTAIR io4 | 2880 | PASS |
| `msa_altair_io6_shift_seed42.csv` | MSA ALTAIR io6 | 2880 | PASS |

Columns: `timestamp` (ISO 8601 UTC), `device_id`, gas readings with the unit in the name (`lel_pct_lel`, `o2_pct_vol`, `co_ppm`, `h2s_ppm`, `voc_ppm`), `co_/h2s_stel_ppm` and `_twa_ppm`, state columns (`device_mode`, `pump_state`, `sos_state`, `bridge_id`, `link`), alarm flags (`<gas>_alarm_low/high/stel/twa`, `<gas>_over_range`; 0/1), and `event`, a ground-truth label written by the generator, not a device field.

## Blackline G7c (`blackline_g7c`)

Source: Blackline G7c datasheet R28. Events: bump_test, exposure_lel, exposure_lel, exposure_lel.

| check | channel | result | value | required | detail |
|---|---|---|---|---|---|
| columns | all | pass | 0 | = 0 missing columns | 28 columns |
| timestamps | all | pass | 0 | = 0 steps != 10 s; ISO 8601 UTC | 2880 rows, steps [10.0] |
| resolution | lel | pass | 0 | = 0 values off the 1 grid | lel_pct_lel: 0 |
| range | lel | pass | 0 | = 0 values outside [0, 100] | min 0, max 50 |
| alarm_setpoints | lel | pass | 0 | = 0 mismatches (low >= 10, high >= 20) | low alarms 104, high alarms 81 |
| over_range | lel | pass | 0 | = 0 mismatches (value >= 100) | over-range samples 0 |
| alarm_cause | lel | pass | 0 | = 0 alarm samples without an event on this gas | alarm samples 104 |
| resolution | o2 | pass | 0 | = 0 values off the 0.1 grid | o2_pct_vol: 0 |
| range | o2 | pass | 0 | = 0 values outside [0, 25] | min 18, max 21 |
| alarm_setpoints | o2 | pass | 0 | = 0 mismatches (low <= 19.5, high >= 23.5) | low alarms 7, high alarms 0 |
| over_range | o2 | pass | 0 | = 0 mismatches (value >= 25) | over-range samples 0 |
| alarm_cause | o2 | pass | 0 | = 0 alarm samples without an event on this gas | alarm samples 7 |
| resolution | co | pass | 0 | = 0 values off the 1 grid | co_ppm: 0, co_stel_ppm: 0, co_twa_ppm: 0 |
| range | co | pass | 0 | = 0 values outside [0, 500] | min 0, max 99 |
| alarm_setpoints | co | pass | 0 | = 0 mismatches (low >= 25, high >= 100) | low alarms 11, high alarms 0 |
| over_range | co | pass | 0 | = 0 mismatches (value >= 500) | over-range samples 0 |
| stel_formula | co | pass | 0.5 | max |STEL - 15-min mean| <= 0.5 | peak STEL 10 |
| twa_formula | co | pass | 0.3542 | max |TWA - dose/8 h| <= 0.5 | end-of-shift TWA 0 |
| stel_twa_alarms | co | pass | 0 | = 0 mismatches (STEL >= 200, TWA >= 25) |  |
| alarm_cause | co | pass | 0 | = 0 alarm samples without an event on this gas | alarm samples 11 |
| resolution | h2s | pass | 0 | = 0 values off the 0.1 grid | h2s_ppm: 0, h2s_stel_ppm: 0, h2s_twa_ppm: 0 |
| range | h2s | pass | 0 | = 0 values outside [0, 100] | min 0, max 24.8 |
| alarm_setpoints | h2s | pass | 0 | = 0 mismatches (low >= 10, high >= 15) | low alarms 9, high alarms 6 |
| over_range | h2s | pass | 0 | = 0 mismatches (value >= 100) | over-range samples 0 |
| stel_formula | h2s | pass | 0.04889 | max |STEL - 15-min mean| <= 0.05 | peak STEL 2.4 |
| twa_formula | h2s | pass | 0.04865 | max |TWA - dose/8 h| <= 0.05 | end-of-shift TWA 0.1 |
| stel_twa_alarms | h2s | pass | 0 | = 0 mismatches (STEL >= 15, TWA >= 10) |  |
| alarm_cause | h2s | pass | 0 | = 0 alarm samples without an event on this gas | alarm samples 9 |
| bump_simultaneous | all | pass | 1 | every bump: all mix gases change first at its first sample | bump at row 12: first change lel@12, h2s@12, co@12, o2@12 |
| state_values | all | pass | 0 | = 0 columns with values outside the allowed set; ids constant | 17 columns checked |
| scenario_content | all | pass | 3 | bump in first 15 min, 1-3 exposures | first bump at 120.0 s; exposures 3 |

## Blackline G7x with G7 Bridge (`blackline_g7x_bridge`)

Source: Blackline G7x datasheet R21. Events: bump_test, exposure_lel.

| check | channel | result | value | required | detail |
|---|---|---|---|---|---|
| columns | all | pass | 0 | = 0 missing columns | 30 columns |
| timestamps | all | pass | 0 | = 0 steps != 10 s; ISO 8601 UTC | 2880 rows, steps [10.0] |
| resolution | lel | pass | 0 | = 0 values off the 1 grid | lel_pct_lel: 0 |
| range | lel | pass | 0 | = 0 values outside [0, 100] | min 0, max 50 |
| alarm_setpoints | lel | pass | 0 | = 0 mismatches (low >= 10, high >= 20) | low alarms 70, high alarms 8 |
| over_range | lel | pass | 0 | = 0 mismatches (value >= 100) | over-range samples 0 |
| alarm_cause | lel | pass | 0 | = 0 alarm samples without an event on this gas | alarm samples 70 |
| resolution | o2 | pass | 0 | = 0 values off the 0.1 grid | o2_pct_vol: 0 |
| range | o2 | pass | 0 | = 0 values outside [0, 25] | min 18, max 21 |
| alarm_setpoints | o2 | pass | 0 | = 0 mismatches (low <= 19.5, high >= 23.5) | low alarms 7, high alarms 0 |
| over_range | o2 | pass | 0 | = 0 mismatches (value >= 25) | over-range samples 0 |
| alarm_cause | o2 | pass | 0 | = 0 alarm samples without an event on this gas | alarm samples 7 |
| resolution | co | pass | 0 | = 0 values off the 1 grid | co_ppm: 0, co_stel_ppm: 0, co_twa_ppm: 0 |
| range | co | pass | 0 | = 0 values outside [0, 500] | min 0, max 99 |
| alarm_setpoints | co | pass | 0 | = 0 mismatches (low >= 25, high >= 100) | low alarms 11, high alarms 0 |
| over_range | co | pass | 0 | = 0 mismatches (value >= 500) | over-range samples 0 |
| stel_formula | co | pass | 0.5 | max |STEL - 15-min mean| <= 0.5 | peak STEL 10 |
| twa_formula | co | pass | 0.3476 | max |TWA - dose/8 h| <= 0.5 | end-of-shift TWA 0 |
| stel_twa_alarms | co | pass | 0 | = 0 mismatches (STEL >= 200, TWA >= 25) |  |
| alarm_cause | co | pass | 0 | = 0 alarm samples without an event on this gas | alarm samples 11 |
| resolution | h2s | pass | 0 | = 0 values off the 0.1 grid | h2s_ppm: 0, h2s_stel_ppm: 0, h2s_twa_ppm: 0 |
| range | h2s | pass | 0 | = 0 values outside [0, 100] | min 0, max 24.7 |
| alarm_setpoints | h2s | pass | 0 | = 0 mismatches (low >= 10, high >= 15) | low alarms 9, high alarms 6 |
| over_range | h2s | pass | 0 | = 0 mismatches (value >= 100) | over-range samples 0 |
| stel_formula | h2s | pass | 0.05 | max |STEL - 15-min mean| <= 0.05 | peak STEL 2.4 |
| twa_formula | h2s | pass | 0.04861 | max |TWA - dose/8 h| <= 0.05 | end-of-shift TWA 0.1 |
| stel_twa_alarms | h2s | pass | 0 | = 0 mismatches (STEL >= 15, TWA >= 10) |  |
| alarm_cause | h2s | pass | 0 | = 0 alarm samples without an event on this gas | alarm samples 9 |
| bump_simultaneous | all | pass | 1 | every bump: all mix gases change first at its first sample | bump at row 12: first change lel@12, h2s@12, co@12, o2@12 |
| state_values | all | pass | 0 | = 0 columns with values outside the allowed set; ids constant | 18 columns checked |
| scenario_content | all | pass | 1 | bump in first 15 min, 1-3 exposures | first bump at 120.0 s; exposures 1 |

- To verify: Gas ranges and resolutions are the G7c values (brief: same sensors as G7c); confirm in G7x datasheet R21.

## Blackline G8 (`blackline_g8`)

Source: Blackline G8 spec sheet R1. Events: bump_test, exposure_h2s, sos.

| check | channel | result | value | required | detail |
|---|---|---|---|---|---|
| columns | all | pass | 0 | = 0 missing columns | 29 columns |
| timestamps | all | pass | 0 | = 0 steps != 10 s; ISO 8601 UTC | 2880 rows, steps [10.0] |
| resolution | lel | pass | 0 | = 0 values off the 1 grid | lel_pct_lel: 0 |
| range | lel | pass | 0 | = 0 values outside [0, 100] | min 0, max 50 |
| alarm_setpoints | lel | pass | 0 | = 0 mismatches (low >= 10, high >= 20) | low alarms 10, high alarms 8 |
| over_range | lel | pass | 0 | = 0 mismatches (value >= 100) | over-range samples 0 |
| alarm_cause | lel | pass | 0 | = 0 alarm samples without an event on this gas | alarm samples 10 |
| resolution | o2 | pass | 0 | = 0 values off the 0.1 grid | o2_pct_vol: 0 |
| range | o2 | pass | 0 | = 0 values outside [0, 25] | min 18, max 21 |
| alarm_setpoints | o2 | pass | 0 | = 0 mismatches (low <= 19.5, high >= 23.5) | low alarms 7, high alarms 0 |
| over_range | o2 | pass | 0 | = 0 mismatches (value >= 25) | over-range samples 0 |
| alarm_cause | o2 | pass | 0 | = 0 alarm samples without an event on this gas | alarm samples 7 |
| resolution | co | pass | 0 | = 0 values off the 1 grid | co_ppm: 0, co_stel_ppm: 0, co_twa_ppm: 0 |
| range | co | pass | 0 | = 0 values outside [0, 500] | min 0, max 99 |
| alarm_setpoints | co | pass | 0 | = 0 mismatches (low >= 25, high >= 100) | low alarms 11, high alarms 0 |
| over_range | co | pass | 0 | = 0 mismatches (value >= 500) | over-range samples 0 |
| stel_formula | co | pass | 0.5 | max |STEL - 15-min mean| <= 0.5 | peak STEL 10 |
| twa_formula | co | pass | 0.3389 | max |TWA - dose/8 h| <= 0.5 | end-of-shift TWA 0 |
| stel_twa_alarms | co | pass | 0 | = 0 mismatches (STEL >= 200, TWA >= 25) |  |
| alarm_cause | co | pass | 0 | = 0 alarm samples without an event on this gas | alarm samples 11 |
| resolution | h2s | pass | 0 | = 0 values off the 0.1 grid | h2s_ppm: 0, h2s_stel_ppm: 0, h2s_twa_ppm: 0 |
| range | h2s | pass | 0 | = 0 values outside [0, 100] | min 0, max 24.7 |
| alarm_setpoints | h2s | pass | 0 | = 0 mismatches (low >= 10, high >= 15) | low alarms 9, high alarms 6 |
| over_range | h2s | pass | 0 | = 0 mismatches (value >= 100) | over-range samples 0 |
| stel_formula | h2s | pass | 0.05 | max |STEL - 15-min mean| <= 0.05 | peak STEL 2.6 |
| twa_formula | h2s | pass | 0.04861 | max |TWA - dose/8 h| <= 0.05 | end-of-shift TWA 0.2 |
| stel_twa_alarms | h2s | pass | 0 | = 0 mismatches (STEL >= 15, TWA >= 10) |  |
| alarm_cause | h2s | pass | 0 | = 0 alarm samples without an event on this gas | alarm samples 9 |
| bump_simultaneous | all | pass | 1 | every bump: all mix gases change first at its first sample | bump at row 12: first change lel@12, h2s@12, co@12, o2@12 |
| state_values | all | pass | 0 | = 0 columns with values outside the allowed set; ids constant | 18 columns checked |
| scenario_content | all | pass | 1 | bump in first 15 min, 1-3 exposures, SOS as configured | first bump at 120.0 s; exposures 1; SOS events 1 |

- To verify: Gas ranges and resolutions are the G7c values (brief: same sensors as G7c, LEL-MPS); confirm in G8 spec sheet R1.

## MSA ALTAIR io4 (`msa_altair_io4`)

Source: MSA spec sheet 1708-056. Events: bump_test, exposure_co, exposure_h2s.

| check | channel | result | value | required | detail |
|---|---|---|---|---|---|
| columns | all | pass | 0 | = 0 missing columns | 28 columns |
| timestamps | all | pass | 0 | = 0 steps != 10 s; ISO 8601 UTC | 2880 rows, steps [10.0] |
| resolution | lel | pass | 0 | = 0 values off the 1 grid | lel_pct_lel: 0 |
| range | lel | pass | 0 | = 0 values outside [0, 100] | min 0, max 50 |
| alarm_setpoints | lel | pass | 0 | = 0 mismatches (low >= 10, high >= 20) | low alarms 10, high alarms 8 |
| over_range | lel | pass | 0 | = 0 mismatches (value >= 100) | over-range samples 0 |
| alarm_cause | lel | pass | 0 | = 0 alarm samples without an event on this gas | alarm samples 10 |
| resolution | o2 | pass | 0 | = 0 values off the 0.1 grid | o2_pct_vol: 0 |
| range | o2 | pass | 0 | = 0 values outside [0, 30] | min 18, max 21 |
| alarm_setpoints | o2 | pass | 0 | = 0 mismatches (low <= 19.5, high >= 23.5) | low alarms 7, high alarms 0 |
| over_range | o2 | pass | 0 | = 0 mismatches (value >= 30) | over-range samples 0 |
| alarm_cause | o2 | pass | 0 | = 0 alarm samples without an event on this gas | alarm samples 7 |
| resolution | co | pass | 0 | = 0 values off the 1 grid | co_ppm: 0, co_stel_ppm: 0, co_twa_ppm: 0 |
| range | co | pass | 0 | = 0 values outside [0, 1999] | min 0, max 99 |
| alarm_setpoints | co | pass | 0 | = 0 mismatches (low >= 25, high >= 100) | low alarms 30, high alarms 0 |
| over_range | co | pass | 0 | = 0 mismatches (value >= 1999) | over-range samples 0 |
| stel_formula | co | pass | 0.5 | max |STEL - 15-min mean| <= 0.5 | peak STEL 12 |
| twa_formula | co | pass | 0.499 | max |TWA - dose/8 h| <= 0.5 | end-of-shift TWA 1 |
| stel_twa_alarms | co | pass | 0 | = 0 mismatches (STEL >= 200, TWA >= 25) |  |
| alarm_cause | co | pass | 0 | = 0 alarm samples without an event on this gas | alarm samples 30 |
| resolution | h2s | pass | 0 | = 0 values off the 1 grid | h2s_ppm: 0, h2s_stel_ppm: 0, h2s_twa_ppm: 0 |
| range | h2s | pass | 0 | = 0 values outside [0, 199] | min 0, max 25 |
| alarm_setpoints | h2s | pass | 0 | = 0 mismatches (low >= 10, high >= 15) | low alarms 56, high alarms 51 |
| over_range | h2s | pass | 0 | = 0 mismatches (value >= 199) | over-range samples 0 |
| stel_formula | h2s | pass | 0.5 | max |STEL - 15-min mean| <= 0.5 | peak STEL 9 |
| twa_formula | h2s | pass | 0.3594 | max |TWA - dose/8 h| <= 0.5 | end-of-shift TWA 0 |
| stel_twa_alarms | h2s | pass | 0 | = 0 mismatches (STEL >= 15, TWA >= 10) |  |
| alarm_cause | h2s | pass | 0 | = 0 alarm samples without an event on this gas | alarm samples 56 |
| bump_simultaneous | all | pass | 1 | every bump: all mix gases change first at its first sample | bump at row 12: first change lel@12, h2s@12, co@12, o2@12 |
| state_values | all | pass | 0 | = 0 columns with values outside the allowed set; ids constant | 17 columns checked |
| scenario_content | all | pass | 2 | bump in first 15 min, 1-3 exposures | first bump at 120.0 s; exposures 2 |

## MSA ALTAIR io6 (`msa_altair_io6`)

Source: MSA spec sheet 1708-056 (ALTAIR io4 spec sheet). Events: bump_test, exposure_lel, exposure_lel.

| check | channel | result | value | required | detail |
|---|---|---|---|---|---|
| columns | all | pass | 0 | = 0 missing columns | 33 columns |
| timestamps | all | pass | 0 | = 0 steps != 10 s; ISO 8601 UTC | 2880 rows, steps [10.0] |
| resolution | lel | pass | 0 | = 0 values off the 1 grid | lel_pct_lel: 0 |
| range | lel | pass | 0 | = 0 values outside [0, 100] | min 0, max 50 |
| alarm_setpoints | lel | pass | 0 | = 0 mismatches (low >= 10, high >= 20) | low alarms 42, high alarms 8 |
| over_range | lel | pass | 0 | = 0 mismatches (value >= 100) | over-range samples 0 |
| alarm_cause | lel | pass | 0 | = 0 alarm samples without an event on this gas | alarm samples 42 |
| resolution | o2 | pass | 0 | = 0 values off the 0.1 grid | o2_pct_vol: 0 |
| range | o2 | pass | 0 | = 0 values outside [0, 30] | min 18, max 21 |
| alarm_setpoints | o2 | pass | 0 | = 0 mismatches (low <= 19.5, high >= 23.5) | low alarms 7, high alarms 0 |
| over_range | o2 | pass | 0 | = 0 mismatches (value >= 30) | over-range samples 0 |
| alarm_cause | o2 | pass | 0 | = 0 alarm samples without an event on this gas | alarm samples 7 |
| resolution | co | pass | 0 | = 0 values off the 1 grid | co_ppm: 0, co_stel_ppm: 0, co_twa_ppm: 0 |
| range | co | pass | 0 | = 0 values outside [0, 1999] | min 0, max 99 |
| alarm_setpoints | co | pass | 0 | = 0 mismatches (low >= 25, high >= 100) | low alarms 11, high alarms 0 |
| over_range | co | pass | 0 | = 0 mismatches (value >= 1999) | over-range samples 0 |
| stel_formula | co | pass | 0.4889 | max |STEL - 15-min mean| <= 0.5 | peak STEL 9 |
| twa_formula | co | pass | 0.341 | max |TWA - dose/8 h| <= 0.5 | end-of-shift TWA 0 |
| stel_twa_alarms | co | pass | 0 | = 0 mismatches (STEL >= 200, TWA >= 25) |  |
| alarm_cause | co | pass | 0 | = 0 alarm samples without an event on this gas | alarm samples 11 |
| resolution | h2s | pass | 0 | = 0 values off the 1 grid | h2s_ppm: 0, h2s_stel_ppm: 0, h2s_twa_ppm: 0 |
| range | h2s | pass | 0 | = 0 values outside [0, 199] | min 0, max 25 |
| alarm_setpoints | h2s | pass | 0 | = 0 mismatches (low >= 10, high >= 15) | low alarms 9, high alarms 7 |
| over_range | h2s | pass | 0 | = 0 mismatches (value >= 199) | over-range samples 0 |
| stel_formula | h2s | pass | 0.4889 | max |STEL - 15-min mean| <= 0.5 | peak STEL 2 |
| twa_formula | h2s | pass | 0.07431 | max |TWA - dose/8 h| <= 0.5 | end-of-shift TWA 0 |
| stel_twa_alarms | h2s | pass | 0 | = 0 mismatches (STEL >= 15, TWA >= 10) |  |
| alarm_cause | h2s | pass | 0 | = 0 alarm samples without an event on this gas | alarm samples 9 |
| resolution | voc | pass | 0 | = 0 values off the 0.1 grid | voc_ppm: 0 |
| range | voc | pass | 0 | = 0 values outside [0, 4000] | min 0, max 0.4 |
| alarm_setpoints | voc | pass | 0 | = 0 mismatches (low >= 50, high >= 100) | low alarms 0, high alarms 0 |
| over_range | voc | pass | 0 | = 0 mismatches (value >= 4000) | over-range samples 0 |
| alarm_cause | voc | pass | 0 | = 0 alarm samples without an event on this gas | alarm samples 0 |
| bump_simultaneous | all | pass | 1 | every bump: all mix gases change first at its first sample | bump at row 12: first change lel@12, h2s@12, co@12, o2@12 |
| state_values | all | pass | 0 | = 0 columns with values outside the allowed set; ids constant | 21 columns checked |
| scenario_content | all | pass | 2 | bump in first 15 min, 1-3 exposures | first bump at 120.0 s; exposures 2 |

- To verify: The VOC (PID) range 0-4000 ppm, resolution 0.1 was given in the brief with the io4 spec sheet (MSA 1708-056) as source; the io4 has no VOC channel, so confirm where this value comes from.

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
| `sos.count_per_shift` | `1` | events | Brief: one SOS on the G8. Independent of the gas readings. |
| `sos.duration_s` | `[60, 300]` | s (min, max) | SOS active time, drawn uniformly. |
| `state_values` | `{"device_mode": ["normal", "bump_test"], "pump_state": "on for the whole shift", "link": "cellular for the whole shift"}` | - | No state logging format given. Pump runs continuously; the Bridge stays on cellular (satellite is allowed by the spec but not exercised). |
| `identifiers` | `{"device_id": "<DEVICE>-0001", "bridge_id": "BRIDGE-0001"}` | - | Synthetic identifiers. |
| `event_label` | `"event column: none \| bump_test \| exposure_<gas>"` | - | Ground-truth label written by the generator, not a device field. The gate uses it to check that every alarm has a cause. |

Device-level assumptions in the specs:

- `msa_altair_io6`: LEL/O2/CO/H2S ranges and resolutions and `pump_state` are taken from the io4 spec sheet: **ASSUMPTION: same sensors as io4** (io6 sensor table not found).
