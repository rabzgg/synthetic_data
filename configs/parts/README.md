# configs/parts: one sensor per file

A part is one physical sensor: what it measures and how well, taken from its datasheet. The same
generic measurement model (`core/quantities/measurement.py`) turns the world's true value into a
reading for every part. Only the numbers in this file differ.

In the app, step 3 ("Which sensor?") offers, for each picked column, Generic plus every part here
that measures that quantity, sorted by file name. "Build a device" lists every part. A new file
here shows up in both without any code change.

There are two kinds of part:

- **Named parts** come from a real datasheet (Bosch BME280, Maxim DS18B20). Values cite the page.
- **Generic parts** (`generic_*.yaml`) stand for a typical sensor of a class, for when the potential
  client has not named a sensor yet. Every value is an ASSUMPTION. Each quantity has exactly one.

## The files

| file | name | measures | from |
|---|---|---|---|
| `bosch_bme280.yaml` | Bosch BME280 | air temperature, humidity, pressure | datasheet BST-BME280-DS001-23 rev 1.23 |
| `bosch_bma280.yaml` | Bosch BMA280 | acceleration (3 axes) | datasheet BST-BMA280-DS000-11 rev 1.8 |
| `bosch_bmg160.yaml` | Bosch BMG160 | angular rate (3 axes) | datasheet BST-BMG160-DS000-09 rev 1.2 |
| `bosch_bmm150.yaml` | Bosch BMM150 | magnetic field (3 axes) | datasheet BST-BMM150-DS001-05 rev 1.4 |
| `maxim_ds18b20.yaml` | Maxim DS18B20 | air temperature | datasheet 19-7487 Rev 6 |
| `maxim_max44009.yaml` | Maxim MAX44009 | light | written without the datasheet, **[USER TO VERIFY]**, used by no preset |
| `blackline_g7_lel.yaml` | Blackline G7 LEL sensor | combustible gas (LEL) | Blackline G7c datasheet R28 |
| `blackline_g8_lel_mps.yaml` | Blackline G8 LEL-MPS sensor | combustible gas (LEL) | Blackline G8 spec sheet R1 |
| `blackline_o2_cell.yaml` | Blackline oxygen cell | O2 | Blackline G7c datasheet R28 |
| `blackline_co_cell.yaml` | Blackline carbon monoxide cell | CO | Blackline G7c datasheet R28 |
| `blackline_h2s_cell.yaml` | Blackline hydrogen sulfide cell | H2S | Blackline G7c datasheet R28 |
| `msa_altair_lel.yaml` | MSA ALTAIR LEL sensor | combustible gas (LEL) | MSA spec sheet 1708-056 |
| `msa_altair_o2_cell.yaml` | MSA ALTAIR oxygen cell | O2 | MSA spec sheet 1708-056 |
| `msa_altair_co_cell.yaml` | MSA ALTAIR carbon monoxide cell | CO | MSA spec sheet 1708-056 |
| `msa_altair_h2s_cell.yaml` | MSA ALTAIR hydrogen sulfide cell | H2S | MSA spec sheet 1708-056 |
| `msa_altair_pid_voc.yaml` | MSA ALTAIR io6 PID (VOC) sensor | VOC | no table found, values assumed |
| `generic_air_temperature.yaml` | Generic air temperature sensor | air temperature | digital ambient temperature IC, ±1 °C |
| `generic_humidity.yaml` | Generic humidity sensor | humidity | capacitive RH sensor IC, ±3 %RH |
| `generic_pressure.yaml` | Generic barometric pressure sensor | pressure | MEMS barometer, 300-1100 hPa, ±1 hPa |
| `generic_o2_cell.yaml` | Generic oxygen cell | O2 | electrochemical O2 cell, 0-25 %vol |
| `generic_co_cell.yaml` | Generic carbon monoxide cell | CO | electrochemical CO cell, 0-500 ppm |
| `generic_h2s_cell.yaml` | Generic hydrogen sulfide cell | H2S | electrochemical H2S cell, 0-100 ppm |
| `generic_lel_sensor.yaml` | Generic combustible gas (LEL) sensor | combustible gas (LEL) | catalytic bead, 0-100 %LEL |
| `generic_voc_pid.yaml` | Generic VOC (PID) sensor | VOC | photoionisation, 0-1000 ppm |
| `generic_co2_ndir.yaml` | Generic CO2 sensor (NDIR) | CO2 | low-cost NDIR module, 0-5000 ppm |
| `generic_accelerometer.yaml` | Generic accelerometer | acceleration | consumer MEMS, ±8 g, 12 bit |
| `generic_gyroscope.yaml` | Generic gyroscope | angular rate | consumer MEMS, ±2000 °/s |
| `generic_magnetometer.yaml` | Generic magnetometer | magnetic field | consumer 3-axis, ±1200 µT |
| `generic_current_clamp_5a.yaml` | Generic current clamp 5 A | current | split-core clamp, 0-5 A |
| `generic_energy_meter.yaml` | Generic energy meter | energy | kWh meter, accuracy class 1 |
| `generic_light_sensor.yaml` | Generic light sensor | light | digital ambient light sensor, 0-100 000 lx |
| `generic_vibration_transmitter.yaml` | Generic vibration transmitter 25 mm/s | vibration | RMS velocity transmitter, 0-25 mm/s |
| `generic_soil_moisture_probe.yaml` | Generic capacitive soil moisture probe | soil moisture | capacitive probe, ±3 %VWC |
| `generic_water_temperature.yaml` | Generic water temperature probe | water temperature | stainless-steel digital probe, ±0.5 °C |
| `generic_ph_probe.yaml` | Generic pH probe | pH | glass electrode with transmitter, ±0.1 pH |
| `generic_level_transmitter.yaml` | Generic level transmitter | water level | hydrostatic, 4-20 mA, 0-100 % |

The gas parts were rebuilt from `configs/gas/<device>/spec.json` (the older gas engine), and
`tests/test_devices.py` checks the numbers still match.

## What one file looks like

A named part (excerpt of `bosch_bme280.yaml`):

```yaml
name: Bosch BME280
datasheet: "BST-BME280-DS001-23, revision 1.23"
measures:
  - quantity: air.humidity_rh
    params:                                   # parameters of the model, written directly
      range: {value: [0, 100], unit: "%RH", source: "datasheet BST-BME280-DS001-23 p.9 (operating range)"}
      resolution: {value: 0.008, unit: "%RH", source: "datasheet BST-BME280-DS001-23 p.9"}
    from_datasheet:                           # or in the datasheet's own words (rules below)
      - {rule: accuracy_typical, value: 3, unit: "%RH", source: "datasheet BST-BME280-DS001-23 p.9 (typical)"}
      - {rule: hysteresis_pm, value: 1, unit: "%RH", source: "datasheet BST-BME280-DS001-23 p.9"}
      - {rule: t63, value: 1, unit: "s", source: "datasheet BST-BME280-DS001-23 p.9 (τ63)"}
  - quantity: air.temperature_c
    params: {...}
notes:
  - "Not modelled: self-heating of the temperature reading (p.12, note 7)."
```

| key | required | meaning |
|---|---|---|
| `name` | yes | shown in the app ("Bosch BME280") |
| `datasheet` | yes | document number and revision. A generic part writes `"none: ..."` here. |
| `datasheet_url` | no | link to the PDF |
| `description` | no | one sentence |
| `measures` | yes | one entry per quantity the sensor measures. A sensor that measures three things has three entries, and the app shows it for all three columns. |
| `measures[].quantity` | yes | a quantity id from `configs/quantities/` |
| `measures[].params` | one of the two | model parameters, written directly (table below) |
| `measures[].from_datasheet` | one of the two | values in the datasheet's wording, converted by a rule (table below). Both can be used together. |
| `notes` | no | what was left out and why, how to read the datasheet's columns |
| `generic_for` | generic only | the quantity this generic part stands in for |
| `class` | generic only | the sensor class, shown in the app as "Generic (<class>)" |

The file name is the part's id (`bosch_bme280`). Devices refer to the part by it. Use
`<vendor>_<model>.yaml` in lower case.

## Model parameters (`params`)

| parameter | meaning | default |
|---|---|---|
| `range` | lowest and highest value the sensor can report. A reading outside is clipped. | required |
| `resolution` | smallest step of the output | required |
| `accuracy` | error of one unit, in the quantity's unit. A `max` bound or a `typical` 1σ (see `kind`). | 0 |
| `accuracy_pct_reading` | error of one unit in % of the reading | 0 |
| `accuracy_combine` | `sum` gives ±(a + b % of reading), `max` gives whichever is greater | sum |
| `bias_distribution` | how one unit's error is drawn inside a max bound: `uniform`, or `normal` when the datasheet says its limits are 3σ | uniform |
| `noise_sd` | white noise per sample (RMS) | 0 |
| `noise_density` | noise per √Hz. The noise then follows the bandwidth, so a faster logging interval gives more noise. | none |
| `bandwidth_hz` | low-pass cutoff of the signal | ODR / 2 |
| `odr_hz` | output data rate when no device sets it | none |
| `odr_choices_hz` | the ODR settings the sensor offers. The device picks the first one at or above its sampling rate. | none |
| `odr_settings_hz` | `[[ODR, bandwidth], ...]` pairs from the datasheet's filter table | none |
| `odr_range_hz` | `[low, high]`: any ODR in between (generic parts) | none |
| `t90_s` | time to reach 90 % of a step. 0 means instant. | 0 |
| `t90_up_s`, `t90_down_s` | different times for a rising and a falling input (a gas cell clears slowly) | `t90_s` |
| `hysteresis` | full width of the hysteresis band | 0 |
| `drift_per_hour` | slow drift of one unit (write it per year, it is converted) | 0 |
| `deadband`, `deadband_center` | values close to the centre read as the centre (a toxic gas cell shows 0 in clean air) | 0 |
| `cross_sensitivity` | another quantity that leaks into the reading: `{quantity: {factor, ref}}` | none |
| `mounting_orientation` | 3-axis sensors: how the chip sits on the board, quaternion `[w, x, y, z]` | aligned |
| `cross_axis_pct`, `misalignment_deg` | 3-axis sensors: axis errors of one unit | 0 |

A parameter that is not given is 0 or off (no noise, instant response). Leaving a value out is a
statement too, so give an ASSUMPTION when the datasheet is silent but the effect is real.

`kind` on `accuracy`, `accuracy_pct_reading`, `drift_per_hour`, `cross_axis_pct` and
`misalignment_deg`: `max` (default) is a hard bound, `typical` is a spread with sd = the value. Use
`typical` for a value from the datasheet's Typ column.

## Datasheet wordings (`from_datasheet`)

Each entry is `{rule, value, unit, source}` (plus `kind` where it applies). The rule converts the
datasheet's wording into model parameters.

| rule | datasheet says | becomes |
|---|---|---|
| `range` | Measurement range 0 to R, or lo to hi | `range` |
| `range_symmetric` | Full scale ±R (for example ±16 g) | `range` |
| `resolution` | Resolution X, LSB size X | `resolution` |
| `sensitivity_lsb` | Sensitivity S LSB per unit | `resolution` |
| `bits` | N-bit output over a span | `resolution` |
| `accuracy` | Accuracy, tolerance, max error ±X | `accuracy` |
| `accuracy_pct_reading` | ±Y % of reading | `accuracy_pct_reading` |
| `accuracy_pct_fs` | ±Y % of full scale | `accuracy` |
| `accuracy_sum` | ±(X + Y % of reading) | both, combined as sum |
| `accuracy_max` | ±X or ±Y % of reading, whichever is greater | both, combined as max |
| `accuracy_typical` | Typical accuracy ±X (Typ column) | `accuracy`, kind typical |
| `noise_rms` | Noise X RMS, 1σ | `noise_sd` |
| `noise_pp` | Noise X peak-to-peak | `noise_sd` (divided by 6.6) |
| `noise_density` | Noise density D per √Hz | `noise_density` and `bandwidth_hz` |
| `repeatability` | Repeatability ±X | `noise_sd` |
| `t90`, `t63`, `t50` | Response time T90, time constant T63, T50 | `t90_s` |
| `recovery_t90` | Recovery or fall time T90 | `t90_down_s` |
| `drift` | Long-term stability ±X per year (month, day) | `drift_per_hour` |
| `hysteresis_pm` | Hysteresis ±X | `hysteresis` (2X) |
| `hysteresis` | Hysteresis X (full difference) | `hysteresis` |
| `bandwidth` | Bandwidth, −3 dB cutoff | `bandwidth_hz` |
| `odr` | Output data rate | `odr_hz` |
| `cross_axis` | Cross-axis sensitivity ±X % | `cross_axis_pct` |
| `misalignment` | Axis alignment error ±X° | `misalignment_deg` |
| `mounting_euler` | Mounting as roll, pitch, yaw in degrees | `mounting_orientation` |
| `deadband` | Zero deadband or zero suppression X | `deadband` |
| `temperature_coefficient` | Temperature coefficient X per °C | `cross_sensitivity` to air temperature |
| `cross_gas` | C of gas G reads as R | `cross_sensitivity` to that gas |

The generated full list, with every wording the rules accept, is `docs/PARAMETER_MAPPING.md`.

## Adding a named sensor (for example sensor X for air temperature)

1. Get the datasheet PDF. For each quantity the sensor measures, find range, resolution, accuracy
   (Typ or Max column), noise, response time and data rates, each with its page.
2. Write `configs/parts/<vendor>_<model>.yaml`:
   ```yaml
   name: Sensirion SHT31
   datasheet: "<document number, revision>"
   measures:
     - quantity: air.temperature_c
       params:
         range: {value: [-40, 125], unit: "°C", source: "datasheet <document> p.<page>"}
         resolution: {value: 0.01, unit: "°C", source: "datasheet <document> p.<page>"}
       from_datasheet:
         - {rule: accuracy_typical, value: 0.2, unit: "°C", source: "datasheet <document> p.<page> (typical)"}
         - {rule: t63, value: 2, unit: s, source: "datasheet <document> p.<page>"}
     - quantity: air.humidity_rh
       params: {...}
   notes:
     - "Not modelled: ..."
   ```
   (The numbers above are placeholders, not checked values.)
3. Check it loads:
   `python3 -c "from core.devices import Part; print(Part.load('sensirion_sht31').models())"`
4. Run `python3 -m pytest -q`. The app now offers it for both columns, labelled "Sensirion SHT31
   (also measures humidity_rh, not written)" when only temperature is picked.

`docs/prompts/DATASHEET_TO_PART.md` is a prompt for an LLM to write the first draft from a PDF.
Check every page it cites before using the file.

Rules for every value:

- Never invent a page. If it was not checked: `(page not recorded)` and `[USER TO VERIFY]`.
- What the datasheet does not give is an `ASSUMPTION` with the reason.
- Never change an existing part to make a check pass.

## Generic parts

Every quantity in `configs/quantities/` has exactly one generic part. It is the "Generic" choice in
the app. Example, `generic_air_temperature.yaml`:

```yaml
name: Generic air temperature sensor
generic_for: air.temperature_c
class: "digital ambient temperature IC on a logger board, ±1 °C"
datasheet: "none: a generic digital temperature IC (all values ASSUMPTION)"
measures:
  - quantity: air.temperature_c
    params:
      range: {value: [-40, 85], unit: "°C", source: "ASSUMPTION: the usual industrial IC range"}
      resolution: {value: 0.1, unit: "°C", source: "ASSUMPTION: 0.1 °C output step"}
      noise_density: {value: 0.0707, unit: "°C/√Hz", source: "ASSUMPTION: about half a step at 1 Hz"}
      t90_s: {value: 60, unit: s, source: "ASSUMPTION: a small IC inside a vented housing in still air"}
      odr_hz: {value: 1, unit: Hz, source: "ASSUMPTION: default when no device sets it"}
      odr_range_hz: {value: [1, 10], unit: Hz, source: "ASSUMPTION: a digital IC converts 1 to 10 times a second"}
    from_datasheet:
      - {rule: accuracy, value: 1, unit: "°C", kind: max, source: "ASSUMPTION: ±1 °C, typical for this class"}
```

A generic part must give `range`, `resolution`, `noise_density` (so the noise follows the logging
interval), `t90_s` and `odr_hz`, and `odr_range_hz` when the class can change its rate. It must
not be better (resolution, noise, error bound, t90) than the best named part for the same quantity.
`tests/test_generic_parts.py` checks all of this. The generic table in `docs/PRESALES.md` is written
from these files by `python3 cli/update_docs.py`, and the tests check it is up to date.

Only a new quantity needs a new generic part. A new named sensor for an existing quantity does not.
