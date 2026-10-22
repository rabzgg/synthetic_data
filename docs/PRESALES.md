# Pre-sales: guess a client's dataset before the CSV arrives

A prospective client says "we measure A and B in situation C, with sensor X", but has not sent a CSV
yet. The goal is a believable synthetic version of their data and a first idea of how well it
compresses. The app follows the order in which information arrives:

| what we know | when | in the app |
|---|---|---|
| what is measured and the situation | always, first | **Start from columns**: pick the columns, then a situation (a world that provides all of them) |
| the sensor's name | sometimes | per column, a named part instead of **Generic** |
| the datasheet | later | a part file from it (`docs/HOW_TO_ADD_A_SENSOR.md`, `docs/prompts/DATASHEET_TO_PART.md`); it then shows up per column |
| the real CSV | last | calibration (see **Next**, not done yet) |

## The flow in the UI

1. **Columns.** Grouped by domain (air, body, electrical, …), each with its unit.
2. **Situation.** Only the worlds that provide every chosen column (`configs/worlds/`).
3. **Sensor per column.** "Generic (default): <class>" or a part from a datasheet that measures it.
   One part chosen for several columns is one part (a BME280 for temperature and humidity); what it
   also measures but nobody chose is not logged and not simulated ("also measures X (not logged)").
4. **Sampling.** Sample interval, and per column resolution and noise, shown and editable; a change
   is written as "ASSUMPTION: user tweak". A box writes the readings as **raw counts**: the integer
   register or ADC code, round(reading / resolution), signed where the range goes below zero.
5. **Name, events, generate.** Events the device can see in that situation, then plots, the gate,
   the labels, the **data profile**, a ZIP, and "Save" (a device file in `configs/devices/`).

The same in Python:

```python
from core.devices import device_from_columns
dev = device_from_columns({"temperature_c": "bosch_bme280", "co2_ppm": "generic"}, name="Office sensor",
                          sample_interval_s=60, raw_counts=False)
```

## Generic parts

Every quantity in `configs/quantities/` has exactly one generic part (`generic_for: <quantity>`,
`class: <sensor class>`); `tests/test_generic_parts.py` checks that, that every value is an
ASSUMPTION with what it was anchored on, that range, resolution, noise, t90 and ODR are given, and
that a generic part is **no better** (resolution, noise, error bound, t90) than the best datasheet
part in this repo for the same quantity. Generic columns are marked "(generic)" in the plot and in
the manifest (`device.generic_columns`, `parts[].generic`).

| quantity | column | part | class | range | resolution | noise sd | t90 | ODR | accuracy | anchored on |
|---|---|---|---|---|---|---|---|---|---|---|
| `air.temperature_c` | `temperature_c` | `generic_air_temperature` | digital ambient temperature IC on a logger board, ±1 °C | -40 … 85 °C | 0.1 °C | 0.05 °C | 60 s | 1 Hz | ±1 °C | not better than `bosch_bme280`, `maxim_ds18b20` |
| `air.humidity_rh` | `humidity_rh` | `generic_humidity` | capacitive RH sensor IC behind a filter cap, ±3 %RH | 0 … 100 %RH | 0.1 %RH | 0.05 %RH | 10 s | 1 Hz | ±3 %RH (1σ) | not better than `bosch_bme280` |
| `air.pressure_hpa` | `pressure_hpa` | `generic_pressure` | MEMS barometric pressure sensor, 300-1100 hPa, ±1 hPa | 300 … 1100 hPa | 0.01 hPa | 0.03 hPa | 1 s | 1 Hz | ±1 hPa (1σ) | not better than `bosch_bme280` |
| `air.o2_pct` | `o2_pct_vol` | `generic_o2_cell` | electrochemical O2 cell of a portable gas detector, 0-25 %vol | 0 … 25 %vol | 0.1 %vol | 0.05 %vol | 15 s (up 45) | 1 Hz | ±0.3 %vol | not better than `blackline_o2_cell`, `msa_altair_o2_cell` |
| `air.co_ppm` | `co_ppm` | `generic_co_cell` | electrochemical CO cell of a portable gas detector, 0-500 ppm | 0 … 500 ppm | 1 ppm | 0.5 ppm | 30 s (down 90) | 1 Hz | ±5 % of reading | not better than `blackline_co_cell`, `msa_altair_co_cell` |
| `air.h2s_ppm` | `h2s_ppm` | `generic_h2s_cell` | electrochemical H2S cell of a portable gas detector, 0-100 ppm | 0 … 100 ppm | 0.1 ppm | 0.1 ppm | 30 s (down 90) | 1 Hz | ±5 % of reading | not better than `blackline_h2s_cell`, `msa_altair_h2s_cell` |
| `air.lel_pct` | `lel_pct_lel` | `generic_lel_sensor` | catalytic bead LEL sensor of a portable gas detector, 0-100 %LEL | 0 … 100 %LEL | 1 %LEL | 0.5 %LEL | 20 s (down 60) | 1 Hz | ±5 % of reading | not better than `blackline_g7_lel`, `blackline_g8_lel_mps`, `msa_altair_lel` |
| `air.voc_ppm` | `voc_ppm` | `generic_voc_pid` | photoionisation (PID) VOC sensor, 0-1000 ppm isobutylene | 0 … 1000 ppm | 0.1 ppm | 0.2 ppm | 15 s (down 45) | 1 Hz | ±10 % of reading | not better than `msa_altair_pid_voc` |
| `air.co2_ppm` | `co2_ppm` | `generic_co2_ndir` | low-cost NDIR CO2 module, 0-5000 ppm, ±(50 ppm + 3 %) | 0 … 5000 ppm | 1 ppm | 10 ppm | 120 s | 0.5 Hz | ±50 ppm + ±3 % of reading | class typical (no datasheet part in the repo) |
| `body.accel_g` | `accel_{x,y,z}_g` | `generic_accelerometer` | consumer MEMS accelerometer ±8 g, 12 bit | -8 … 8 g | 0.003906 g | 0.004 g | 0 s | 100 Hz | ±0.06 g (1σ) | not better than `bosch_bma280` |
| `body.gyro_dps` | `gyro_{x,y,z}_dps` | `generic_gyroscope` | consumer MEMS gyroscope ±2000 °/s | -2000 … 2000 °/s | 0.1 °/s | 0.1 °/s | 0 s | 100 Hz | ±1 °/s (1σ) | not better than `bosch_bmg160` (itself `[USER TO VERIFY]`) |
| `body.mag_ut` | `mag_{x,y,z}_ut` | `generic_magnetometer` | consumer 3-axis magnetometer ±1200 µT, uncalibrated | -1200 … 1200 µT | 0.3 µT | 0.8 µT | 0 s | 10 Hz | ±40 µT (1σ) + ±5 % of reading | not better than `bosch_bmm150` |
| `electrical.current_a` | `current_a` | `generic_current_clamp_5a` | split-core current clamp 0-5 A on a logger input | 0 … 5 A | 0.01 A | 0.005 A | 2 s | 1 Hz | ±0.02 A + ±2 % of reading | class typical (no datasheet part in the repo) |
| `electrical.energy_kwh` | `energy_kwh` | `generic_energy_meter` | kWh meter with a pulse or Modbus output, accuracy class 1 | 0 … 999999 kWh | 0.01 kWh | 0 kWh | 0 s | 1 Hz | ±1 % of reading | class typical (no datasheet part in the repo) |
| `light.lux` | `light_lux` | `generic_light_sensor` | digital ambient light sensor, 0-100 000 lx, 1 lx step | 0 … 100000 lx | 1 lx | 1 lx | 0.1 s | 1 Hz | ±20 % of reading | not better than `maxim_max44009` (itself `[USER TO VERIFY]`) |
| `machine.vibration_mm_s` | `vibration_mm_s` | `generic_vibration_transmitter` | RMS velocity vibration transmitter 0-25 mm/s (ISO 10816 style) | 0 … 25 mm/s | 0.01 mm/s | 0.02 mm/s | 5 s | 1 Hz | ±5 % of reading | class typical (no datasheet part in the repo) |
| `soil.moisture_pct` | `soil_moisture_pct_vwc` | `generic_soil_moisture_probe` | capacitive soil moisture probe (VWC), ±3 %VWC | 0 … 60 %VWC | 0.1 %VWC | 0.1 %VWC | 60 s | 1 Hz | ±3 %VWC | class typical (no datasheet part in the repo) |
| `water.temperature_c` | `water_temperature_c` | `generic_water_temperature` | waterproof stainless-steel digital temperature probe, ±0.5 °C | -10 … 85 °C | 0.0625 °C | 0.03 °C | 30 s | 1 Hz | ±0.5 °C | class typical (no datasheet part in the repo) |
| `water.ph` | `water_ph` | `generic_ph_probe` | glass pH electrode with a transmitter, ±0.1 pH after calibration | 0 … 14 pH | 0.01 pH | 0.01 pH | 30 s | 1 Hz | ±0.1 pH | class typical (no datasheet part in the repo) |
| `water.level_pct` | `water_level_pct` | `generic_level_transmitter` | hydrostatic level transmitter (4-20 mA), 0-100 % | 0 … 100 % | 0.1 % | 0.1 % | 5 s | 1 Hz | ±0.5 % | class typical (no datasheet part in the repo) |

"1σ" marks a typical value (normal spread, cut at 3σ); the others are hard bounds. Error bounds and
t90 follow `docs/PARAMETER_MAPPING.md`.

## Data profile (`_profile.json`, and in the UI)

Per column of every run (`core/output/profile.py`):

| field | meaning |
|---|---|
| `bits` | readings: ceil(log2(span / resolution + 1)) from the sensor's range and resolution; other columns: from the distinct values seen |
| `noise_over_resolution` | the part's noise sd / resolution; below about 0.5 a steady signal sits on one code, above 1 nearly every row differs |
| `repeat_fraction` | rows equal to the row before |
| `csv_bytes`, `csv_gzip_bytes`, `csv_ratio` | the column as CSV text, before and after gzip (ratio = before / after) |
| `bin_bytes`, `bin_gzip_bytes`, `bin_ratio` | readings as raw counts in the smallest integer type that holds the sensor's range, before and after gzip |
| `packed_bytes` | rows × bits / 8: the counts bit-packed, before any compression |

plus the same for the whole file. **This is a rough benchmark with gzip, not the Bitteiler
algorithm**; it gives an order of magnitude for synthetic data, not a promise. "Run 5 seeds" in the
UI repeats the run with five seeds and shows each ratio as min … max, so the answer is a range, not
one number. The manifest records the bits per column (`device.reading_columns`).

## What to tell a client (and what not)

- The data are synthetic: `realism: ASSUMPTION` on every world. They follow the datasheets (or, for
  generic parts, the stated class assumptions) and the world's rules; they are not fitted to field
  recordings.
- A ratio from the profile depends on the sample interval, the resolution and the noise. Those three
  are the first questions to ask a client.

## Next: calibrate with the real CSV (not done yet)

When the client's CSV arrives:

1. Compare per column: noise (sd of the differences on quiet stretches), step size (the smallest
   change seen = the real resolution), autocorrelation (how slowly the signal moves), and the
   compression ratios of the profile on their file and on ours.
2. Adjust the part (resolution, noise, t90) and the world (levels, daily cycle, events) until they
   match within a stated tolerance; record each change with its source ("fitted to client CSV
   <name>").
3. Re-run the profile on both and report the two side by side.

None of this is implemented yet; it needs a calibration script and an agreed tolerance per measure.
