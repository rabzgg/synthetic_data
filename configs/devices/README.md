# configs/devices: products built from parts

A device is what writes one CSV: a product such as a Blackline G7c gas detector or a fridge logger.
It is made of parts (`configs/parts/`), a logging interval, and logic: the extra columns the
device computes itself, such as alarms, STEL and TWA, battery level, signal strength, or fall
detection.

A device never contains measurement numbers itself. Those are in its parts. The device only says
which parts it has, how often it logs, and what it computes from the readings.

Devices are used by scenarios (`configs/scenarios/`), by "Build a device" in the app, and by
`python3 cli/generate.py --devices <name>`. "Save this device" in the app writes a new file here.

## The files

| file | name | parts | logic | interval |
|---|---|---|---|---|
| `blackline_g7c.yaml` | Blackline G7c | Blackline LEL, O2, CO, H2S cells + Bosch BMA280 (not written) | STEL, TWA, bump test mode, battery, signal, gas alarms, fall and no-motion detection | 10 s |
| `blackline_g7x_bridge.yaml` | Blackline G7x Bridge | Blackline LEL, O2, CO, H2S cells | bridge id and link (cellular or satellite), STEL, TWA, bump test mode, battery, signal, gas alarms | 10 s |
| `blackline_g8.yaml` | Blackline G8 | Blackline G8 LEL-MPS, O2, CO, H2S cells | STEL, TWA, bump test mode, SOS state, battery, signal, gas alarms | 10 s |
| `msa_altair_io4.yaml` | MSA ALTAIR io4 | MSA LEL, O2, CO, H2S cells | STEL, TWA, bump test mode, battery, signal, gas alarms | 10 s |
| `msa_altair_io6.yaml` | MSA ALTAIR io6 | MSA LEL, O2, CO, H2S cells + PID (VOC) | as io4, plus sampling pump state and pump alarm | 10 s |
| `bme280_sensor_board.yaml` | BME280 Sensor Board | Bosch BME280 | none | 1 s |
| `fridge_logger.yaml` | Fridge Logger | Maxim DS18B20 + generic current clamp | signal, high temperature alarm | 60 s |
| `fridge_logger_us.yaml` | Fridge Logger US | as Fridge Logger | as Fridge Logger, written in °F and mA with the vendor's column names | 60 s |
| `rack_monitor.yaml` | Rack Monitor | Maxim DS18B20 | temperature rate of change, rising fast alarm, high temperature alarm | 30 s |
| `pump_vibration_sensor.yaml` | Pump Vibration Sensor | generic vibration transmitter | vibration alarm | 10 s |
| `water_tank_monitor.yaml` | Water Tank Monitor | generic level transmitter + generic current clamp | signal, low level alarm | 60 s |
| `soil_moisture_probe.yaml` | Soil Moisture Probe | generic soil moisture probe | battery, signal, dry soil alarm | 15 min |

The gas detector files were rebuilt from `configs/gas/<device>/spec.json` and are written in the
long YAML form. The others use the short `{value, unit, source}` form. Both mean the same.

## What one file looks like

`fridge_logger.yaml`, complete:

```yaml
name: Fridge Logger
device_id_prefix: FRIDGELOG
description: "Temperature inside a fridge (DS18B20 probe) and the fridge's current (clamp), logged every minute, with a high-temperature alarm."
created: "2026-10-22"
version: 1
preset: true
parts:
  - part: maxim_ds18b20
  - part: generic_current_clamp_5a
features:
  sample_interval_s: {value: 60, unit: s, source: "ASSUMPTION: one reading a minute, usual for cold-chain loggers"}
  connectivity: {value: wifi, unit: "-", source: "ASSUMPTION: Wi-Fi logger"}
logic:
  - block: signal
    output: signal_strength_dbm
    range_dbm: {value: [-115, -55], unit: dBm, source: "ASSUMPTION: as the gas detectors"}
    start_dbm: {value: [-90, -70], unit: dBm, source: "ASSUMPTION: as the gas detectors"}
    step_sd_db: {value: 1.0, unit: dB, source: "ASSUMPTION: as the gas detectors"}
  - block: threshold_alarm
    input: air.temperature_c
    output: temperature_alarm_high
    level: {value: 8, unit: "°C", source: "ASSUMPTION: the 2-8 °C cold-chain band"}
    when: above
    hysteresis: {value: 0.5, unit: "°C", source: "ASSUMPTION: clears half a degree below the limit"}
```

Its CSV has the columns `timestamp, device_id, temperature_c, current_a, signal_strength_dbm,
temperature_alarm_high`.

| key | required | meaning |
|---|---|---|
| `name` | yes | the device's name. The file name is made from it (`Fridge Logger` gives `fridge_logger.yaml`). |
| `slug` | no | if given, it must equal the name made into a file name |
| `device_id_prefix` | no | the `device_id` column is `<prefix>-0001`. Default: the file name in capitals. |
| `description` | no | one sentence, shown in the app |
| `created`, `version` | no | written by "Save this device". Saving under a name that exists writes `<name>.v2.yaml` and so on. An older file is never overwritten. |
| `preset` | no | `true` for the files that ship with the repo |
| `datasheet` | no | the product datasheet, when there is one |
| `notes` | no | free text |
| `parts` | yes | the sensors inside (below) |
| `features` | no | logging interval and how the device reports (below) |
| `logic` | no | the computed columns (below) |
| `output_format` | no | the vendor's column names and units (below) |

## `parts`

```yaml
parts:
  - part: bosch_bme280                          # a file name from configs/parts/
  - part: blackline_h2s_cell
    overrides: {t90_s: {value: 25, unit: s, source: "ASSUMPTION: faster cell in this model"}}
  - part: bosch_bma280
    log: false                                  # measured for the logic, not written to the CSV
    note: "ASSUMPTION: the datasheet does not name its accelerometer, the BMA280 stands in."
```

| key | meaning |
|---|---|
| `part` | the part's file name |
| `overrides` | change some of the part's parameters for this device only. A value without a source becomes "ASSUMPTION: user tweak". The app writes the changes made in step 4 here. |
| `log` | `true` (default) writes every quantity the part measures. `false` measures but does not write (the G7c's accelerometer is only used for fall detection). A list of quantity ids writes only those (a BME280 used only for temperature). |
| `as` | a column suffix when two parts measure the same quantity (`temperature_c_inside`, `temperature_c_outside`) |
| `note` | why this part is here |

A logged reading uses the quantity's column name from `configs/quantities/` (`temperature_c`,
`accel_x_g`). The order of the columns follows the order of the parts.

## `features`

| key | meaning |
|---|---|
| `sample_interval_s` | the logging interval. Default 1 s (ASSUMPTION). A part whose rate can be set follows it, and so does its noise. |
| `connectivity` | how it reports (cellular, wifi, satellite). Recorded in the manifest. |

## `logic`: what the device computes itself

A real device does more than pass readings through. A gas detector averages H2S over 15 minutes
(STEL), raises an alarm above a setpoint, counts down its battery, and notices when its wearer
falls. In this generator each of those is a **logic block**: a small, generic building block that
reads one input and writes one output column.

```yaml
logic:
  - block: threshold_alarm        # which building block
    input: air.h2s_ppm            # what it reads: a quantity the device measures, or an earlier block's output
    output: h2s_alarm_low         # the CSV column it writes
    level: {value: 10, unit: ppm, source: "ASSUMPTION: typical low alarm setpoint"}
    when: above
```

Rules:

- Blocks run in the order written. A block can read the output of a block above it (an alarm on
  the STEL column).
- Every number is `{value, unit, source}`. Words (`above`, `min`, a state name) need no source.
- An unknown key or a missing number is refused with the device and column name.
- The same blocks also run on the world's true values, without sensor errors. That gives the
  "expected" event labels the checks compare the device with.
- Outputs go after the readings in the CSV, in this order. `position: first` puts a column right
  after `device_id` (the G7x Bridge's `bridge_id`).

### The blocks

| block | writes | parameters |
|---|---|---|
| `threshold_alarm` | 1 while the input is at or past a level, else 0 | `input`, `level` (a value, or `range_min` / `range_max` of the input's sensor, for over-range), `when` (`above` or `below`), optional `hysteresis` (clears only that far back), `latching` (stays on once set), `on_value` / `off_value` (default 1 / 0) |
| `rolling_mean` | the mean of the input over the last window (a STEL). Samples before the start count as 0. | `input`, `window_s`, optional `quantize` (round to the sensor's resolution, default true) |
| `cumulative_dose` | the dose since the start divided by a period (an 8 h TWA) | `input`, `period_s`, optional `quantize` |
| `rate_of_change` | the change of the input over a window, per s, min or h | `input`, `window_s`, `per` (`s`, `min`, `h`) |
| `battery` | battery %, draining in a straight line over the runtime, rounded down. A `battery_drain` event drains it faster. | `runtime_h`, `start_pct` |
| `signal` | signal strength in whole dBm, a slow random walk inside a range | `range_dbm`, `start_dbm` (range of the first value), `step_sd_db` |
| `event_mode` | a mode column: one value during an event, the default otherwise (`bump_test` while test gas is on) | `event`, `value`, `default`, optional `until_back` (quantities that must be back to their level before the mode ends) |
| `state_flag` | on while a device state is set by an event (the sampling pump fault, SOS) | `state`, optional `on_value` / `off_value` |
| `constant` | the same value in every row (a gateway id) | `value` |
| `random_state` | a value that sometimes switches to another one (the Bridge's satellite link) | `values`, `default`, `periods` (how many times, range), `duration_s` (how long, range) |
| `stillness_timer` | no-motion detection from an accelerometer: `ok`, `pre_alarm` after `detect_s` without movement, `alert` after `pre_alarm_s` more. Any movement resets it. | `input` (an accelerometer), `window_s`, `threshold_g`, `detect_s`, `pre_alarm_s` |
| `spike_then_still` | fall detection: an impact above `spike_g`, then within `within_s` a tilt of at least `tilt_deg` from upright gives `pre_alarm`. Back upright within `pre_alarm_s` cancels it, otherwise `alert`. | `input` (an accelerometer), `spike_g`, `tilt_deg`, `within_s`, `pre_alarm_s`, `reference_s` (how long upright is learned at the start) |
| `orientation_quat` | orientation as a quaternion, fused from accelerometer, gyroscope and magnetometer | `params` (filter settings, `core/derived/fusion.py`), optional `prefix` |

The two motion blocks run on the sensor's own fast stream (the accelerometer at its ODR), not on the
logging interval, and report their state at each logged row.

### Logic decides which events a device can show

Some events act on the device, not the world. They only make sense when the device has the matching
block, and the app hides them otherwise ("This device has no sampling pump.").

| the device has | so it can show |
|---|---|
| `event_mode` with `event: bump_test` | Bump test |
| `signal` | Connection loss |
| `battery` | Battery drain |
| `state_flag` with `state: pump` | Pump fault |
| `state_flag` with `state: sos` | SOS |

World events (gas release, AC failure, leak) need no block. They only need the device to measure a
quantity the event changes. Body events (Fall, No motion, Collapse) need a device worn on the body
(`mount: body`) that measures motion. `spike_then_still` and `stillness_timer` then add the fall and
no-motion alert columns, and the labels say when those alerts are expected.

### Example: the logic of `blackline_g7c.yaml`, block by block

| block | input | output | what it does |
|---|---|---|---|
| `rolling_mean` | `air.co_ppm` | `co_stel_ppm` | CO averaged over the last 15 min (STEL) |
| `cumulative_dose` | `air.co_ppm` | `co_twa_ppm` | CO dose since the start of the shift divided by 8 h (TWA) |
| `rolling_mean`, `cumulative_dose` | `air.h2s_ppm` | `h2s_stel_ppm`, `h2s_twa_ppm` | the same for H2S |
| `event_mode` | | `device_mode` | `bump_test` from the start of a bump test until all four gas readings are back to their level, `normal` otherwise |
| `battery` | | `battery_pct` | 18 h runtime (datasheet), starting full |
| `signal` | | `signal_strength_dbm` | cellular signal, a random walk between −115 and −55 dBm |
| `threshold_alarm` ×2 | `air.lel_pct` | `lel_alarm_low`, `lel_alarm_high` | above 10 and 20 %LEL (placeholder setpoints, ASSUMPTION) |
| `threshold_alarm` | `air.lel_pct` | `lel_over_range` | at the top of the LEL sensor's range (`level: range_max`) |
| `threshold_alarm` ×3 | `air.o2_pct` | `o2_alarm_low`, `o2_alarm_high`, `o2_over_range` | below 19.5 %vol, above 23.5 %vol, at the range top |
| `threshold_alarm` ×5 | `air.co_ppm`, `co_stel_ppm`, `co_twa_ppm` | `co_alarm_low`, `co_alarm_high`, `co_alarm_stel`, `co_alarm_twa`, `co_over_range` | CO above 25 and 100 ppm, STEL above 200 ppm, TWA above 25 ppm, range top |
| `threshold_alarm` ×5 | `air.h2s_ppm`, `h2s_stel_ppm`, `h2s_twa_ppm` | `h2s_alarm_low`, `h2s_alarm_high`, `h2s_alarm_stel`, `h2s_alarm_twa`, `h2s_over_range` | H2S above 10 and 15 ppm, STEL above 15 ppm, TWA above 10 ppm, range top |
| `spike_then_still` | `body.accel_g` | `fall_state` | impact above 2.5 g, then lying (60° or more) within 3 s gives a pre-alarm, 30 s to cancel |
| `stillness_timer` | `body.accel_g` | `no_motion_state` | 2 min without movement gives a pre-alarm, 30 s more an alert |

The accelerometer is a part with `log: false`, so it feeds the last two blocks but has no columns
of its own. The alarm setpoints are placeholders (ASSUMPTION) until the setpoints configured on a
real device are known.

## `output_format`: the vendor's column names and units

```yaml
output_format:
  temperature_c: {value: temp_f, unit: "°F", source: "ASSUMPTION: the vendor exports Fahrenheit"}
  current_a: {value: compressor_ma, unit: mA, source: "ASSUMPTION: the vendor exports milliamperes"}
  temperature_alarm_high: {value: alarm_hi, unit: "-", source: "ASSUMPTION: the vendor's name for the alarm column"}
```

The key is the device's own column, `value` is the new name and `unit` the unit to convert to
(from `configs/units.yaml`). Logic blocks keep using the original names. The unit `counts` writes a
reading as an integer, round(reading / resolution). That is what the "Write counts (LSB)" box in
the app does. The checks convert back before they compare.

## Adding a device

1. Pick the parts from `configs/parts/`. If a sensor is missing, add its part first (see
   `configs/parts/README.md`).
2. Write `configs/devices/<name>.yaml` with `name`, `parts`, `features.sample_interval_s` and,
   if the device computes anything, `logic`. Copy the closest file in the table above.
3. Check it loads:
   `python3 -c "from core.devices import Device; print(Device.load('<name>').columns())"`
4. Try it in a scenario without writing one:
   `python3 cli/generate.py --scenario worker_collapse --devices <name>:fixed --out out/try`
   (`fixed` or `body`, see `configs/scenarios/README.md`)
5. `python3 cli/update_docs.py` to update `docs/EVENTS.md` (which events the new device can show),
   then `python3 -m pytest -q`.

The app's "Build a device" does the same with a form and saves the result here.

A device needs no code unless it computes something no block above can do. Then a new block goes
in `core/logic/blocks.py`. Ask before writing one.
