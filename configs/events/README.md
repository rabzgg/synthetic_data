# configs/events: things that happen

An event changes something for a while: a gas leaks, a compressor stops, a worker falls, a device
loses its connection. Each file describes one kind of event: its parameters (with defaults and
sources) and its effects. A scenario, or step 5 of the app, says when it happens and with which
values.

There are three kinds, depending on what the event acts on:

- **World events** change the true values (a gas level, a named signal such as the compressor).
  Every device that measures what changed sees them.
- **Body events** change how the person carrying a device moves (a fall, lying still). Only devices
  worn on the body (`mount: body`) see them.
- **Device events** change one device only (a connection gap, a bump test, a sensor fault). The
  device needs the matching feature (see `configs/devices/README.md`, "Logic decides which events a
  device can show").

The app only offers events the device can show in the chosen environment. The others are listed
under "Events this device cannot show (and why)" with the sentence from `missing` or
`wrong_setting`.

## The files

| file | on screen | kind | acts on | parameters |
|---|---|---|---|---|
| `gas_release.yaml` | Gas release | world | the chosen gas (`lel`, `co`, `h2s`, `voc`, `co2`) | `gas`, `level`, `duration_s`, `ramp_s` |
| `temperature_change.yaml` | Temperature change | world | `air.temperature_c` (RH follows) | `delta_c`, `ramp_s`, `duration_s` |
| `door_open.yaml` | Door open | world, indoor only | air temperature, vapour, CO2 and light move towards outside values | `duration_s`, `outside_temperature_c`, `outside_rh_pct`, `outside_co2_ppm`, `light_add_lux`, `exchange_tau_s`, `recovery_tau_s` |
| `ac_failure.yaml` | AC failure | world, indoor only | signal `ac` (server room) | `duration_s` |
| `compressor_failure.yaml` | Compressor failure | world | signal `compressor` (fridge) | `duration_s` |
| `bearing_wear.yaml` | Bearing wear | world, stays after the event | signal `pump_vibration` (pump room) | `duration_s`, `factor` |
| `leak.yaml` | Leak | world | signal `leak`, an extra outflow (water tank) | `duration_s`, `rate_pct_per_h` |
| `irrigation.yaml` | Irrigation | world | signal `irrigation`, an inflow (field) | `duration_s`, `added_pct` |
| `fall.yaml` | Fall | body, made of steps | fall down, lie, get up | `fall_s`, `lying_s`, `rise_s` |
| `no_motion.yaml` | No motion | body | completely still, as when unconscious | `duration_s` |
| `collapse.yaml` | Collapse | made of steps | gas release, fall, stir, no motion, rescue | `gas`, `level`, `duration_s`, `ramp_s`, `fall_after_s`, `fall_s`, `no_motion_after_s`, `no_motion_s`, `rise_s` |
| `fall_down.yaml` | Fall down | body, building block | only the fall itself | `fall_s` |
| `lie.yaml` | Lie on the ground | body, building block | lying, alive, small movements | `duration_s` |
| `stir.yaml` | Stir on the ground | body, building block | lying, moving clearly | `duration_s` |
| `rise.yaml` | Get up | body, building block | from lying to standing | `rise_s` |
| `bump_test.yaml` | Bump test | device, needs `bump_test` | test gas on the sensor inlet | `mix`, `applied_s` |
| `connection_loss.yaml` | Connection loss | device, needs `connectivity` | no rows written for a while | `duration_s` |
| `battery_drain.yaml` | Battery drain | device, needs `battery` | battery drains faster | `duration_s`, `extra_pct_per_h` |
| `pump_fault.yaml` | Pump fault | device, needs `states.pump` | sampling pump state | `duration_s` |
| `sos.yaml` | SOS | device, needs `states.sos` | SOS state | `duration_s` |
| `sensor_fault.yaml` | Sensor fault | device | one sensor sticks, reads zero or reads off | `quantity`, `mode`, `offset`, `duration_s` |

Building blocks (`building_block: true`) are small pieces used inside other events. The app shows
them only under "Building blocks (advanced)".

`docs/EVENTS.md` is generated from these files (`python3 cli/update_docs.py`) and has the full table
of which preset device can show which event.

## What one file looks like

A world event, `ac_failure.yaml`:

```yaml
kind: ac_failure
name: AC failure
description: "The air conditioner stops. The room warms towards the temperature the racks' heat would reach, until the AC runs again."
missing: "This environment has no air conditioner."
probe_world: server_room
setting: indoor
wrong_setting: "This environment is outdoors, it has no air conditioner."
params:
  duration_s: {value: 2700, unit: s, source: "ASSUMPTION: 45 minutes until it is restarted"}
label: "AC off for {duration_s} s"
effects:
  - {target: ac, op: set, value: 0, after: revert}
```

Read it as: while the event lasts, the world's `ac` signal is 0. The server room's temperature is
built on that signal, so it rises, and it falls again when the event ends.

| key | required | meaning |
|---|---|---|
| `kind` | yes | the event's id, equal to the file name |
| `name` | no | shown in the app (default: the kind). Give one. |
| `description` | no | plain sentences, shown in the app. Give one. |
| `params` | no | every parameter with a default `{value, unit, source}`. A parameter can list `choices` (the gases of `gas_release`). |
| `effects` | one of the two | what changes (below) |
| `steps` | one of the two | a composite event made of other events (below) |
| `duration` | no | an expression of the parameters (`"$duration_s + 2 * $ramp_s"`). Default `$duration_s`. |
| `label` | no | the detail written in the labels file, with parameters in braces |
| `requires` | device events | the device features it needs (`bump_test`, `connectivity`, `battery`, `states.<name>`) |
| `scope` | no | `world` or `device`. Worked out from the targets. |
| `missing` | no | the sentence the app shows when the environment or device lacks what the event acts on |
| `setting` | no | `indoor` or `outdoor`, for an event that only happens there |
| `wrong_setting` | no | the sentence shown when the environment's setting differs |
| `probe_world` | no | the world used to try the event when no run is given (for the tables in `docs/EVENTS.md`) |
| `building_block` | no | `true` for a small event meant only for composites |

## Effects

```yaml
effects:
  - {target: <what>, op: <how>, ..., after: revert}
```

On the world, `target` is a quantity id (`air.h2s_ppm`), a short alias (`h2s`), a relation input
(`air.vapour_pressure_hpa`), a named signal of the world (`compressor`, `leak`), or a parameter
(`$gas`).

| op | needs | does |
|---|---|---|
| `add` | `shape` | adds a shape in time since the event start (a `pulse`, a `ramp`, a `constant`) |
| `multiply` | `shape` | multiplies (vibration grows to a multiple) |
| `set` | `value` | holds the target at a value during the event |
| `approach` | `value`, `tau_s`, optional `recovery_tau_s` | moves towards a value, and back afterwards |

| key | meaning |
|---|---|
| `after: revert` | (default) the effect ends with the event |
| `after: hold` | what it reached stays to the end of the run (wear, damage) |
| `optional: true` | skip this effect in a world without that target, instead of refusing the event |

On the body, `target: motion` with `segments`, one after the other:

```yaml
effects:
  - target: motion
    segments:
      - {kind: fall, duration: $fall_s, needs: upright}
      - {kind: still, posture: lying, duration: $lying_s}
      - {kind: rise, duration: $rise_s}
```

Segment kinds: `still` (alive, small movements), `motionless`, `walk`, `fall`, `rise`, `stir`.
`posture` is `upright`, `lying` or `current`.

On a device:

| target | does |
|---|---|
| `device.input` | changes what a sensor is given: `quantity` with `op: stuck`, `zero` or `offset` (a fault), or `quantities: $mix` with `op: set` (a bump test) |
| `device.gap` | no rows are written (connection loss). The device keeps measuring. |
| `device.state` | sets a device state, read by a `state_flag` block (`state: pump`, `state: sos`) |
| `device.battery` | extra battery drain (`extra_pct_per_h`) |

Parameters are used as `$name`. Expressions allow numbers, `$parameters`, `+ - * /`, `min` and
`max`.

## Composite events

`collapse.yaml` is made of other events:

```yaml
steps:
  - {event: gas_release, at: 0, params: {gas: $gas, level: $level, duration_s: $duration_s, ramp_s: $ramp_s}, label: gas_release}
  - {event: fall_down, at: $fall_after_s, params: {fall_s: $fall_s}, label: fall}
  - {event: stir, after: 0, params: {duration_s: $no_motion_after_s}, label: stir}
  - {event: no_motion, after: 0, params: {duration_s: $no_motion_s}, label: no_motion}
  - {event: rise, after: 0, params: {rise_s: $rise_s}, label: rescue}
```

`at` is a time from the start of the composite. `after` is a gap after the previous step ends.

## Adding an event

1. First check whether an existing event can do it with other values. A new gas for
   `gas_release` is one more entry in its `choices`. A different temperature step is
   `temperature_change` with another `delta_c`.
2. Decide what it acts on. For a world event, the world needs something to hit:
   a quantity, or a named signal. A failure of one machine is best a named signal in the world
   (`compressor`), so that everything built on it follows.
3. For a stock (tank level, soil water), change a flow, not the level. A leak is an extra
   outflow. The level then follows, stops at its bounds and recovers by itself.
4. Write `configs/events/<kind>.yaml`. Give every parameter a default with a source, a plain
   `description`, and a `missing` sentence for environments or devices that lack the target.
5. Use it in a scenario (`configs/scenarios/`) and run
   `python3 cli/generate.py --scenario <name> --out out/try`.
6. `python3 cli/update_docs.py`, then `python3 -m pytest -q`.

Example for a new measurement, a radiation source brought near the device for a while (it needs the
quantity `radiation.dose_rate_usv_h`, see `configs/README.md`):

```yaml
kind: radiation_source
name: Radiation source nearby
description: "A radioactive source is brought near the device, stays for a while, then is taken away."
missing: "This environment has no radiation reading."
params:
  level: {value: 5, unit: "µSv/h", source: "ASSUMPTION: a weak check source at about 1 m"}
  duration_s: {value: 600, unit: s, source: "ASSUMPTION: ten minutes"}
  ramp_s: {value: 10, unit: s, source: "ASSUMPTION: carried in and out"}
duration: "$duration_s + 2 * $ramp_s"
label: "{level} µSv/h"
effects:
  - {target: radiation.dose_rate_usv_h, op: add, shape: {pulse: {duration_s: $duration_s, ramp_s: $ramp_s, level: $level}}, after: revert}
```

A new kind of effect, body motion or device target needs Python (`core/events/library.py`,
`core/world/motion.py`). Ask before writing it.

Longer guide: `docs/HOW_TO_ADD_AN_EVENT.md`.
