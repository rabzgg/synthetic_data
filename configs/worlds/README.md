# configs/worlds: environments (the true values over time)

A world is the physical truth of one place over time: what the air temperature, the gas levels, the
tank level or the light really are, second by second, before any sensor looks at them. Every
sensor of a run reads the same world, so two devices in one room agree with each other.

In the app a world is called an **environment** (step 2, "Where is the sensor?"). The app only
offers the environments that provide every column picked in step 1.

## The files

| file | on screen | setting | provides | named signals |
|---|---|---|---|---|
| `aquarium.yaml` | Aquarium | indoor | air and water temperature, pH, current, light, vibration | `lamp`, `pump` |
| `field_day.yaml` | Field | outdoor | air (temperature, RH, pressure, all gases), light (partly cloudy sky), soil moisture | `irrigation`, `evaporation` |
| `fridge.yaml` | Fridge | indoor | air temperature, RH, current, light | `compressor` |
| `indoor_worker_walking.yaml` | Indoor workplace | indoor | air (temperature, RH, pressure, all gases), light. A person walking and standing. | none |
| `outdoor_day.yaml` | Outdoors | outdoor | air (temperature, RH, pressure, all gases), light (partly cloudy sky). A device at rest. | none |
| `pump_room.yaml` | Pump room | indoor | air temperature, RH, current, energy, vibration | `running`, `pump_vibration` |
| `server_room.yaml` | Server room | indoor | air temperature, RH, current | `ac` |
| `static_shelf.yaml` | Shelf indoors | indoor | air (temperature, RH, pressure, all gases), light. A device at rest. | none |
| `water_tank.yaml` | Water tank | outdoor | water level, pump current | `pump`, `fill`, `use`, `leak` |

Every world also provides acceleration, angular rate and magnetic field (a device at rest, unless
the world has a `motion` section). "All gases" means O2, CO, H2S, LEL, VOC and CO2.

Named signals are the parts an event can hit on its own. `compressor_failure` sets `compressor`
to 0, and the fridge's temperature and current both follow.

## What one file looks like

`fridge.yaml`, shortened (`...` stands for `{value, unit, source}` entries):

```yaml
title: "Fridge"
realism: ASSUMPTION
setting: indoor
description: "The compressor runs about 40 % of the time in cycles of about half an hour. ..."
signals:                                   # helpers, not written to any CSV
  compressor:
    duty_cycle: {period_s: ..., duty: ..., on_value: ..., off_value: ..., transition_s: ..., jitter: ...}
drivers:                                   # one per quantity
  air.temperature_c:
    sum:
      - constant: {value: 21, unit: "°C", source: "ASSUMPTION: kitchen temperature"}
      - product:
          - constant: {value: -40, unit: "°C", source: "ASSUMPTION: cooling at full duty"}
          - lowpass: {of: {ref: compressor}, tau_s: ..., start: ...}
  air.vapour_pressure_hpa:
    vapour_from_rh: {rh_pct: ..., temperature_c: ...}
  electrical.current_a:
    sum:
      - constant: {value: 0.08, unit: A, source: "ASSUMPTION: electronics and fan"}
      - product: [{constant: {value: 0.9, unit: A, source: "ASSUMPTION: compressor current"}}, {ref: compressor}]
  light.lux: {constant: {value: 0, unit: lx, source: "ASSUMPTION: dark with the door closed"}}
```

Read it as: the compressor switches on and off. The inside temperature is the kitchen temperature
minus cooling that follows the compressor slowly (thermal mass). The current is a small base plus
0.9 A whenever the compressor runs. RH is not given directly: it follows from the water vapour and
the temperature.

| key | required | meaning |
|---|---|---|
| `title` | no | the name shown in the app (default: the file name). Give one. |
| `realism` | yes | `ASSUMPTION` (made up from knowledge) or `recorded` (from a real recording). Never left to a default. |
| `setting` | no | `indoor` or `outdoor`. Events that only happen indoors (Door open, AC failure) are refused outdoors, with a sentence saying why. |
| `description` | no | plain sentences, shown in the app |
| `name` | no | defaults to the file name |
| `signals` | no | named helper signals that drivers and events refer to |
| `drivers` | in practice | one entry per quantity id (from `configs/quantities/`) or relation input (below) |
| `clean_air` | no | for gases: the normal O2 and CO2, and which gas `%LEL` refers to (methane by default) |
| `motion` | no | how the body carrying a worn device moves (below). Default: at rest. |
| `grid` | no | `air_dt_s` (default 1 s) and `body_dt_s` (default 0.04 s = 25 Hz) |
| `time` | no | `start_utc` (default 2026-01-05 06:00) and `utc_offset_h` (default 0). Daily cycles and schedules use local time. |
| `earth_field_ut` | no | the Earth's magnetic field (default: mid-latitude, about 49 µT) |

Every default is an ASSUMPTION and is listed in each run's manifest.

## Building blocks for signals and drivers

A signal or driver is a small formula made of primitives. The full list with every parameter is at
the top of `core/world/primitives.py`.

| primitive | gives | typical use |
|---|---|---|
| `constant` | a fixed level | room temperature, clean air (0 ppm) |
| `step` | a switch at a time | a setpoint change |
| `ramp` | a straight change from one value to another | slow warming |
| `pulse` | 0, up to a level, hold, back to 0 (a trapezoid) | a gas cloud passing |
| `exp_rise_decay` | builds up, then dies away | heat after a machine starts |
| `periodic` | a sine | a slow oscillation |
| `duty_cycle` | on and off with a period, duty and jitter | compressor, pump, AC |
| `daily_cycle` | a cosine over 24 h with a peak hour | outdoor temperature |
| `schedule` | a value per hour of the day | working hours, lights |
| `solar` | daylight from the sun's height, under a `sky` (`clear`, `partly_cloudy`, `overcast`) | outdoor light |
| `random_walk` | slow natural variation around a mean | weather, room air |
| `integrate` | a stock filled and emptied by flows, held between bounds | tank level, soil water, energy |
| `vapour_from_rh` | water vapour for a given RH and temperature | humidity |
| `levels_on_walk` | a new level each time the person starts walking | room lights |
| `floors_on_walk` | floor changes during walks | pressure changing with height |

Operators that combine them:

| operator | does |
|---|---|
| `sum: [a, b, ...]` | adds |
| `product: [a, b, ...]` | multiplies (a level times an on/off signal) |
| `lowpass: {of, tau_s, start}` | a lag (thermal mass, inertia) |
| `smooth: {of, window_s}` | a moving average |
| `clip: {of, min, max}` | bounds |
| `ref: <name>` | another signal or driver of this world |

## What the world works out by itself

| if the world has | it also provides |
|---|---|
| `air.temperature_c` and `air.vapour_pressure_hpa` | `air.humidity_rh` (never above 100 %) |
| a `clean_air` section and gas drivers | `air.o2_pct` (gases push oxygen out) |
| `air.sea_level_pressure_hpa` (and `floor_altitude_m`) | `air.pressure_hpa` at the device's height |
| a `motion` section (or none) | acceleration, angular rate, magnetic field and orientation |

Give the input or the result, not both (vapour or RH, not the two). These relations are in
`core/world/physics.py`.

## `motion`: a person or a thing that moves

Only needed for worn devices. `indoor_worker_walking.yaml` shows every key:

| key | meaning |
|---|---|
| `model` | `still` (at rest, the default) or `walk_still` (walking and standing bouts) |
| `walk_bout_s`, `still_bout_s` | how long each walk and each stop lasts (range) |
| `speed_m_s`, `surge_m_s`, `step_hz`, `bob_m`, `sway_deg` | walking speed, its variation, step rate, up and down per step, trunk sway |
| `turn_rate_sd_dps`, `turn_tau_s` | turning while walking |
| `device_height_m`, `lying_height_m` | height of the device standing and lying |
| `impact_s` | how long the impact of a fall lasts |
| `fidget_deg`, `fidget_tau_s` | small movements while standing (nobody is perfectly still) |
| `stir_deg` | movement while lying after a fall |
| `heading_deg` | facing direction at the start |

Events add falls, lying still and getting up on top of this (`configs/events/`).

## Adding a world

1. Copy the closest file. Pick a clear file name (`cold_store.yaml`).
2. Set `title`, `realism: ASSUMPTION`, `setting` and a plain `description`.
3. Give a driver for every quantity a device should be able to measure there. A quantity without a
   driver does not exist in that world, so the app will not offer this world for it.
4. Name the parts an event should hit on its own as `signals` (a compressor, a pump, a leak flow),
   and refer to them with `ref`.
5. For a stock (a tank, soil water, a battery), use `integrate` with named inflow and outflow
   signals. An event then changes a flow, and the level follows and stops at its bounds.
6. Look at it: `python3 cli/plot_world.py --preset <name> --hours 24`
7. `python3 -m pytest -q`

The smallest world that works:

```yaml
title: "Aquarium pH"
realism: ASSUMPTION
drivers:
  water.ph: {constant: {value: 7.1, unit: pH, source: "ASSUMPTION: neutral tank"}}
```

## Adding a new quantity to existing worlds

After a new quantity is added in `configs/quantities/` (for example a gamma dose rate), give it a
driver in every world where it should exist:

```yaml
drivers:
  radiation.dose_rate_usv_h:
    sum:
      - constant: {value: 0.1, unit: "µSv/h", source: "ASSUMPTION: natural background outdoors"}
      - random_walk: {mean: {value: 0, unit: "µSv/h", source: "ASSUMPTION: around the level"},
                      sd: {value: 0.01, unit: "µSv/h", source: "ASSUMPTION: small natural variation"},
                      tau_s: {value: 600, unit: s, source: "ASSUMPTION: changes over minutes"}}
```

Only a new kind of relation between quantities, or a new primitive, needs Python
(`core/world/physics.py`, `core/world/primitives.py`). Ask before writing it.

Longer guide: `docs/HOW_TO_ADD_A_WORLD.md`.
