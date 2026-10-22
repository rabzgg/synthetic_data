# How to add a sensor

**Short version:** write one part file from the datasheet (`configs/parts/<slug>.yaml`), put it in a
device file (`configs/devices/<slug>.yaml`) with a logging interval and, if wanted, logic blocks,
then run a scenario. No Python. If the sensor measures something new (say dissolved oxygen), first
add the quantity (step 0).

## 0. Is the quantity in the catalog?

Look in `configs/quantities/*.yaml`. If it is missing, add an entry to the right domain file (or a
new file):

```yaml
  - {id: water.dissolved_o2_mg_l, name: Dissolved oxygen, unit: mg/L, column: dissolved_o2_mg_l, lower: 0, upper: 20,
     note: "Oxygen dissolved in water; saturation at 20 °C is about 9 mg/L."}
```

`id` is `<domain>.<name>_<unit>`; `unit` is the canonical unit every parameter is converted to; a
unit the datasheet writes differently (e.g. `ppm` for mg/L) goes into `configs/units.yaml` (aliases
for spellings, factors for scales). A world must also provide the quantity (see
`HOW_TO_ADD_A_WORLD.md`), otherwise a run says which world lacks it.

## 1. Read the datasheet

Find, for each quantity the sensor measures, with the **page number**:

| look for | becomes | note |
|---|---|---|
| measurement / operating range | `range` | per axis for 3-axis sensors if they differ |
| resolution, LSB, sensitivity (LSB/unit), N bits over a span | `resolution` | rules `resolution`, `sensitivity_lsb`, `bits` |
| accuracy, tolerance, offset, gain error (absolute, % of reading, % FS) | `accuracy`, `accuracy_pct_reading` | **typical** column → `kind: typical` (normal spread, sd = value); **min/max** column → `kind: max` (hard bound) |
| noise (RMS, peak-to-peak, density) | `noise_sd` | p-p ÷ 6.6; density × √bandwidth |
| response time T90 / T63 / τ / T50, recovery time | `t90_s`, `t90_down_s` | the rules convert T63 and T50 |
| bandwidth, ODR | `bandwidth_hz`, `odr_hz` | without a bandwidth: ODR / 2 (ASSUMPTION) |
| selectable data rates | `odr_choices_hz` | a device that logs the quantity runs at the first one at or above its sample rate (see `docs/PRESALES.md`) |
| hysteresis (±X or full width) | `hysteresis` | ±X → band 2X |
| long-term stability / drift per year | `drift_per_hour` | via the unit `…/year` |
| cross-sensitivity, temperature coefficient | `cross_sensitivity` | |
| cross-axis, alignment error | `cross_axis_pct`, `misalignment_deg` | vector quantities |

The full list of parameters and datasheet wordings is in `docs/PARAMETER_MAPPING.md` (generated
from the code). An LLM can do the first pass: `docs/prompts/DATASHEET_TO_PART.md`; check its output
against the pages it cites.

## 2. Write the part file

`configs/parts/bosch_bme280.yaml` is a complete, checked example (excerpt):

```yaml
name: Bosch BME280
datasheet: "BST-BME280-DS001-23, revision 1.23"
measures:
  - quantity: air.humidity_rh
    params:                                   # model parameters directly
      range: {value: [0, 100], unit: "%RH", source: "datasheet BST-BME280-DS001-23 p.9 (operating range)"}
      resolution: {value: 0.008, unit: "%RH", source: "datasheet BST-BME280-DS001-23 p.9"}
    from_datasheet:                           # or in the datasheet's own words
      - {rule: accuracy_typical, value: 3, unit: "%RH", source: "datasheet BST-BME280-DS001-23 p.9 (typical)"}
      - {rule: hysteresis_pm, value: 1, unit: "%RH", source: "datasheet BST-BME280-DS001-23 p.9"}
      - {rule: t63, value: 1, unit: "s", source: "datasheet BST-BME280-DS001-23 p.9 (τ63)"}
      - {rule: drift, value: 0.5, unit: "%RH/year", kind: typical, source: "datasheet BST-BME280-DS001-23 p.9"}
notes:
  - "Not modelled: ... (say what you left out and why)"
```

Rules for every value:

- `source` starts with `datasheet <document> p.<page>` or `ASSUMPTION: <reason>`. Never invent a
  page; if you could not check it, write `(page not recorded)` and `[USER TO VERIFY]`.
- Everything the datasheet does not give (noise of a gas cell, t90 of a probe in still air) is an
  `ASSUMPTION` with a reason. Not giving it at all means 0 (no noise, instant response).
- `kind: typical` vs `kind: max` changes how units are drawn and how wide the gate's error bound is
  (typical counts at 3σ).

Check the file loads: `python3 -c "from core.devices import Part; print(Part.load('bosch_bme280').models())"`.

## 3. Put it in a device

```yaml
name: Fridge Logger                    # the slug (file name) is made from the name
device_id_prefix: FRIDGELOG
parts:
  - part: maxim_ds18b20
  - part: generic_current_clamp_5a
    overrides: {t90_s: {value: 1}}     # a tweak; without a source it becomes "ASSUMPTION: user tweak"
features:
  sample_interval_s: {value: 60, unit: s, source: "ASSUMPTION: one reading a minute"}
logic:                                 # optional; blocks in core/logic/blocks.py, in column order
  - block: threshold_alarm
    input: air.temperature_c
    output: temperature_alarm_high
    level: {value: 8, unit: "°C", source: "ASSUMPTION: the 2-8 °C cold-chain band"}
    when: above
```

- A part entry can set `log: false` (measured for logic, not written; e.g. the G7c accelerometer)
  and `as: <alias>` when two parts measure the same quantity.
- Logic blocks: `threshold_alarm`, `rolling_mean`, `cumulative_dose`, `rate_of_change`,
  `event_mode`, `state_flag`, `battery`, `signal`, `constant`, `random_state`, `stillness_timer`,
  `spike_then_still`, `orientation_quat`. The gas detector presets (`configs/devices/blackline_*.yaml`,
  `msa_altair_*.yaml`) use most of them.
- What a device can do for events (bump test, pump state, battery, connectivity, fall and no-motion
  detection) follows from its blocks.

## 3b. The vendor's column names and units (optional)

A device can write its columns the way a vendor's export does. `output_format` renames a column and,
if a unit is given, converts it; every entry is `{value: <new name>, unit, source}`. Example:
`configs/devices/fridge_logger_us.yaml`.

```yaml
output_format:
  temperature_c: {value: temp_f, unit: "°F", source: "ASSUMPTION: the vendor exports Fahrenheit"}
  current_a: {value: compressor_ma, unit: mA, source: "ASSUMPTION: the vendor exports milliamperes"}
  temperature_alarm_high: {value: alarm_hi, unit: "-", source: "ASSUMPTION: the vendor's name for the alarm"}
```

- The key is the device's own column name (`columns()`); logic blocks keep using those names.
- Scaled units come from `factors` in `configs/units.yaml`, units with an offset (°F, K) from
  `affine`. A rate (°C/min) is converted without the offset.
- The gate reads the vendor's names and units, converts back and checks as usual; the manifest
  lists the formats in `output_transforms`.

Raw counts: the unit `counts` writes a reading as its register / ADC code, round(reading /
resolution), a signed integer (no offset); the manifest records the bits per column
(`device.reading_columns`) and the gate converts back before it checks.

```yaml
output_format:
  temperature_c: {value: temperature_c_counts, unit: counts, source: "ASSUMPTION: the vendor exports raw codes"}
```

## 3c. A generic part (no product named yet)

For pre-sales every quantity has one generic part (`docs/PRESALES.md`): a typical sensor of its class,
every value an `ASSUMPTION` that says what it was anchored on. It adds two keys and needs `range`,
`resolution`, `noise_density` (so the noise follows the ODR), `t90_s` and `odr_hz`; a class whose rate
can be set also gives `odr_range_hz`:

```yaml
name: Generic CO2 sensor (NDIR)
generic_for: air.co2_ppm
class: "low-cost NDIR CO2 module, 0-5000 ppm, ±(50 ppm + 3 %)"
```

A new quantity needs its generic part too (`tests/test_generic_parts.py`), no better than the best
datasheet part for that quantity in `configs/parts/`.

## 4. Run it

```bash
python3 cli/generate.py --scenario fridge_compressor_failure --out out/fridge
python3 cli/generate.py --scenario worker_collapse --devices my_new_device:fixed --out out/try
```

Read `<device>_<scenario>_seed<n>_gate.json`: every check, its value and threshold. A failing check
names the column. `_summary.json` holds the data summary. The manifest lists every parameter that went into the run with its source.
