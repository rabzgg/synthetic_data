# How to add an event (and a scenario)

**Short version:** an event is `configs/events/<kind>.yaml`: parameters with sources and effects on
a world node, on the body's motion or on a device. A scenario (`configs/scenarios/<name>.yaml`)
places events in a world with devices. Both are data; `docs/EVENTS.md` (generated) lists every
event, its parameters and which device presets can see it.

## An event on the world

```yaml
kind: leak
name: Leak
description: "A tank leaks: an extra outflow while the leak lasts; afterwards the level recovers."
probe_world: water_tank                 # where the compatibility table tries it
params:
  duration_s: {value: 10800, unit: s, source: "ASSUMPTION: three hours until it is found"}
  rate_pct_per_h: {value: 25, unit: "%/h", source: "ASSUMPTION: a large leak"}
label: "{rate_pct_per_h} %/h"
effects:
  - {target: leak, op: add, shape: {constant: $rate_pct_per_h}, after: revert}
```

- `target`: a quantity id, a short alias (`h2s`), a relation input, or a **named signal** of the
  world (`leak`, `compressor`, `pump_vibration`, `irrigation`). An effect on a node the world does
  not have is refused, unless it says `optional: true`.
- `op`: `add` or `multiply` with a `shape` (a primitive spec in time since the event start), `set`
  with a `value`, `approach` with a `value`, `tau_s` and `recovery_tau_s`.
- `after`: `revert` (default: the effect ends with the event) or `hold` (what it reached stays:
  wear, damage). `bearing_wear` holds, `compressor_failure` reverts.
- `duration`: an expression (`"$duration_s + 2 * $ramp_s"`); default `$duration_s`.
- Expressions allow numbers, `$parameters`, `+ - * /`, `min`, `max`.

For a stock (tank, soil water, battery) aim the event at a **flow**, not at the level: a leak is an
extra outflow, irrigation an inflow; the level then follows, stops at its bounds and recovers by
itself when the event ends.

## An event on the body

```yaml
effects:
  - target: motion
    segments:
      - {kind: fall, duration: $fall_s, needs: upright}
      - {kind: still, posture: lying, duration: $lying_s}
      - {kind: rise, duration: $rise_s}
```

Kinds: `still` (alive, small movements), `motionless`, `walk`, `fall`, `rise`, `stir` (lying,
moving). `posture: current` keeps the posture from just before. These events only reach devices
worn on the body (`mount: body`).

## An event on a device

```yaml
requires: [states.pump]                 # what the device must have (follows from its logic blocks)
effects:
  - {target: device.state, state: pump}
```

Targets: `device.input` (what a sensor is given: `quantities: $mix` with `op: set` for a bump test,
or `quantity` with `op: stuck | zero | offset`), `device.gap` (no rows), `device.state`,
`device.battery`. Features: `bump_test`, `connectivity`, `battery`, `states.<name>`,
`motion_alerts.fall`, `motion_alerts.no_motion`.

## A composite event

```yaml
kind: collapse
steps:
  - {event: gas_release, at: 0, params: {gas: $gas, level: $level, ...}, label: gas_release}
  - {event: fall_down, at: $fall_after_s, params: {fall_s: $fall_s}, label: fall}
  - {event: stir, after: 0, params: {duration_s: $no_motion_after_s}, label: stir}
  - {event: no_motion, after: 0, params: {duration_s: $no_motion_s}, label: no_motion}
  - {event: rise, after: 0, params: {rise_s: $rise_s}, label: rescue}
```

`at` is an offset from the composite's start, `after` a gap after the previous step. Small events
meant only for composites carry `building_block: true`.

## A scenario

```yaml
name: water_tank_leak
title: "Water tank leak"
realism: ASSUMPTION
world: water_tank
duration: 48h
seed: 42
devices:
  - {device: water_tank_monitor, mount: fixed, height_m: 3.0}
events:
  - leak: {at: "12:00:00", duration_h: 3, rate_pct_per_h: 25}
```

- Times: seconds, `"HH:MM:SS"` from the start of the run, or `"20min"`. `x_min` / `x_h` parameters
  are read as `x_s`.
- Random values: `{random: [lo, hi]}`, `{random_int: [lo, hi]}`, `{choice: [...]}`,
  `{choice_measured: [...]}` (a quantity some device measures), `{by_gas: {h2s: ..., co: ...}}`;
  each may carry its own `source`. `count`, `spacing_s` (gap between events of the same kind) and
  `devices` / `optional` (for device events) are entry keys.
- An event no device can see is refused with the reason (e.g. "changes nothing this device measures",
  "the device is fixed, the event moves the body", "needs the device feature states.pump").

## Check it

```bash
python3 cli/generate.py --scenario water_tank_leak --out out/tank     # files + gate
python3 cli/events_doc.py                                             # docs/EVENTS.md with the new event
```

Worked examples: `compressor_failure` (set a signal), `bearing_wear` (multiply, hold), `leak` and
`irrigation` (flows into stocks), `door_open` (approach), `bump_test` (device input), `collapse`
(composite).
