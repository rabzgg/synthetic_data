# How to add a world

**Short version:** a world is `configs/worlds/<name>.yaml` with `realism`, named `signals` and one
`driver` per quantity, each built from primitives. A world without people or movement needs nothing
else. Look at it with `python3 cli/plot_world.py --preset <name> --hours 24`.

## The smallest world

```yaml
title: "Aquarium pH"
realism: ASSUMPTION
drivers:
  water.ph: {constant: {value: 7.1, unit: pH, source: "ASSUMPTION: neutral tank"}}
```

Left out: `grid` (1 s air, 25 Hz body), `time` (2026-01-05 06:00 UTC, local = UTC), `earth_field_ut`
and `motion` (a body at rest). The defaults are in `core/world/world.py` (`DEFAULTS`), each an
ASSUMPTION, and every run's manifest lists which ones the world used. `realism` is never defaulted:
`ASSUMPTION` (made up from knowledge) or `recorded` (from a recording). Give `setting: indoor` or
`setting: outdoor` too: an event that only happens indoors (a door opening, an AC failure) is then
refused outdoors with a plain reason.

## Signals, drivers and references

```yaml
signals:                               # helpers: not quantities, not in any CSV
  compressor:
    duty_cycle: {period_s: {...}, duty: {...}, on_value: {...}, off_value: {...}, jitter: {...}}
drivers:                               # one per quantity id (configs/quantities) or relation input
  air.temperature_c:
    sum:
      - constant: {value: 21, unit: "°C", source: "ASSUMPTION: kitchen"}
      - product:
          - constant: {value: -40, unit: "°C", source: "ASSUMPTION: cooling at full duty"}
          - lowpass: {of: {ref: compressor}, tau_s: {...}, start: {...}}
  electrical.current_a:
    product: [{constant: {value: 0.9, unit: A, source: "..."}}, {ref: compressor}]
```

One signal drives several quantities, so they stay consistent; and an event aimed at the signal
(`compressor_failure` sets it to 0) changes all of them. **Name the parts of a quantity that an
event should hit on its own** (the pump room's `pump_vibration`, the tank's `leak` and `fill`).

## Primitives and operators

Full list with parameters at the top of `core/world/primitives.py`:

| primitive | use it for |
|---|---|
| `constant`, `step`, `ramp`, `pulse` | levels, switches, slow changes, a trapezoid |
| `exp_rise_decay` | something that builds up and dies away |
| `periodic`, `duty_cycle` | a sine; on/off with period, duty, transition and jitter (compressors, pumps) |
| `daily_cycle`, `schedule`, `solar` | the day: a cosine, hours of the day, daylight under a `sky` (below) |
| `random_walk` | slow natural variation (mean-reverting, with `smooth_s`) |
| `integrate` | a stock: tank level, energy, soil water: `start + ∫(inflow − outflow) dt`, stops at `lower` / `upper`, optional `relax_to` + `relax_tau_s` |
| `vapour_from_rh` | water vapour for a given RH and temperature |

`solar` needs a `sky`:
- `clear`: the clear-sky curve with a little haze, never below 90 % of it.
- `partly_cloudy`: the light switches between sun (the clear curve) and cloud shadow
  (`shade_fraction` of it, about 0.2 to 0.4). Sunny and shaded spells last an exponential time
  (`sun_mean_s`, `shade_mean_s`), and each change takes `transition_s` (seconds). Optional
  `edge_enhancement` (for example 1.2, with `edge_s`) adds the short brightening at a cloud edge.
  It is off by default.
- `overcast`: a slow, smooth fraction of the clear curve (`overcast_fraction`, about 0.15 to 0.3).

The light is never above the clear-sky curve, except at a cloud edge. `outdoor_day.yaml` shows every
parameter of `partly_cloudy`.

Operators: `sum`, `product`, `lowpass` (a lag, e.g. thermal mass; give `start`), `smooth`, `clip`,
`ref`. Every number is `{value, unit, source}`; a bare number is refused.

## Relations the world computes for you

| if the world has | it also gets |
|---|---|
| `air.temperature_c` and `air.vapour_pressure_hpa` | `air.humidity_rh` (Magnus; 100 % at saturation, never above) |
| a `clean_air` section (and gas drivers) | `air.o2_pct` (displaced by the gases; `combustible_gas` sets %vol per %LEL) |
| `air.sea_level_pressure_hpa` (and `floor_altitude_m`) | `air.pressure_hpa` at the device's height |
| a `motion` section (or none: at rest) | `body.accel_g`, `body.gyro_dps`, `body.mag_ut`, orientation |

Give either the input or the result, not both (e.g. vapour *or* RH). People worlds
(`indoor_worker_walking`) show the full `motion` section: walking and standing bouts, step frequency,
sway, small movements while standing (`fidget_deg`), device height.

## Check it

- `python3 cli/plot_world.py --preset <name> --hours 24`: every quantity over a day.
- `python3 -m unittest tests.test_world tests.test_primitives`.
- Then a scenario on it (`HOW_TO_ADD_AN_EVENT.md`) and `python3 cli/generate.py --scenario ...`.

Worked examples: `fridge.yaml` (one signal, three quantities), `water_tank.yaml` (stock and flows),
`field_day.yaml` (soil water with drainage, irrigation inflow), `pump_room.yaml` (shift schedule,
energy meter), `indoor_worker_walking.yaml` (a person, gases, floors).
