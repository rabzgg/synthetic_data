# configs/quantities: what can be measured

A quantity is a physical thing a world can hold and a sensor can measure: air temperature, H2S,
acceleration, water level. It says nothing about any sensor. A sensor's range and accuracy belong in
its part file (`configs/parts/`), not here.

In the app, step 1 ("What does the sensor log?") lists every quantity here, grouped by domain. Each
file is one domain, and a new file is a new group.

## The files

| file | domain (group in the app) | quantities: id, unit, CSV column |
|---|---|---|
| `air.yaml` | Air (climate and gas) | `air.temperature_c` °C `temperature_c`, `air.humidity_rh` %RH `humidity_rh`, `air.pressure_hpa` hPa `pressure_hpa`, `air.o2_pct` %vol `o2_pct_vol`, `air.co_ppm` ppm `co_ppm`, `air.h2s_ppm` ppm `h2s_ppm`, `air.lel_pct` %LEL `lel_pct_lel`, `air.voc_ppm` ppm `voc_ppm`, `air.co2_ppm` ppm `co2_ppm` |
| `body.yaml` | IMU (motion) | `body.accel_g` g `accel_x,y,z_g`, `body.gyro_dps` °/s `gyro_x,y,z_dps`, `body.mag_ut` µT `mag_x,y,z_ut` (3 axes each) |
| `electrical.yaml` | Electrical | `electrical.current_a` A `current_a`, `electrical.energy_kwh` kWh `energy_kwh` |
| `light.yaml` | Light | `light.lux` lx `light_lux` |
| `machine.yaml` | Machine | `machine.vibration_mm_s` mm/s `vibration_mm_s` (RMS velocity) |
| `soil.yaml` | Soil | `soil.moisture_pct` %VWC `soil_moisture_pct_vwc` |
| `water.yaml` | Water | `water.temperature_c` °C `water_temperature_c`, `water.ph` pH `water_ph`, `water.level_pct` % `water_level_pct` |

## What one file looks like

```yaml
domain: air
quantities:
  - {id: air.humidity_rh, name: Relative humidity, unit: "%RH", column: humidity_rh, lower: 0, upper: 100,
     note: "Relative to saturation at the current air temperature."}
  - {id: air.h2s_ppm, name: Hydrogen sulfide, unit: ppm, column: h2s_ppm, lower: 0, upper: 1000000, alias: h2s}
```

| key | required | meaning |
|---|---|---|
| `domain` | yes | the group name. The app shows it capitalised ("Radiation"). Air and body have their own labels in `ui/app.py`. |
| `id` | yes | `<domain>.<name>_<unit>`, unique. Every other file refers to the quantity by this id. |
| `name` | yes | plain English name, shown in the app |
| `unit` | yes | the quantity's own (canonical) unit. Every value in a part, world or event is converted to it. Other spellings and scales go in `configs/units.yaml`. |
| `column` | yes | the CSV column name. For a 3-axis quantity it contains `{axis}` (`accel_{axis}_g` gives `accel_x_g`, `accel_y_g`, `accel_z_g`). |
| `lower`, `upper` | yes | hard limits of nature (RH cannot pass 100 %, a concentration cannot be negative). `null` means no limit. The world never goes past them. |
| `axes` | no | `[x, y, z]` for a vector quantity (the IMU). Leave out for a single value. |
| `alias` | no | a short name used in events and scenarios (`gas: h2s`). Must be unique. |
| `note` | no | one sentence of explanation |

## Not in this folder

Some values in the worlds are inputs to relations, not quantities, so no sensor reads them
directly: `air.vapour_pressure_hpa` (the world turns it into RH), `air.sea_level_pressure_hpa` and
`floor_altitude_m` (the world turns them into the pressure at the device). These relations are in
`core/world/physics.py`.

## Adding a quantity

Example: a gamma dose rate for a radioactivity measurement.

```yaml
# configs/quantities/radiation.yaml
domain: radiation
quantities:
  - {id: radiation.dose_rate_usv_h, name: Gamma dose rate, unit: "µSv/h", column: dose_rate_usv_h, lower: 0, upper: null,
     note: "Ambient dose equivalent rate. Natural background is about 0.05 to 0.3 µSv/h."}
```

A new quantity is not usable until these also exist (the tests fail until they do):

1. its generic part in `configs/parts/` (`generic_for: <id>`), see `configs/parts/README.md`
2. a driver for it in at least one world in `configs/worlds/`, see `configs/worlds/README.md`
3. a row in the generic table of `docs/PRESALES.md`
4. a fixture line in `FIXTURES` at the top of `tests/test_quantities.py`
5. `python3 cli/parameter_mapping.py` to regenerate `docs/PARAMETER_MAPPING.md`

The full walk-through is in `configs/README.md` ("add a new measurement").

Before adding one, check that it is really new. The same physical thing in another unit or under
another column name is not a new quantity: add the unit to `configs/units.yaml`, and rename the
column in the device with `output_format` (see `configs/devices/README.md`).
