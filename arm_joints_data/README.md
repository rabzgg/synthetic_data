# Arm sensors sensor_1 … sensor_6: original recordings, synthetic data and plots

Sensor → arm-link mapping: **[USER TO VERIFY]**. The files are named by XDK sensor (sensor_k), not by
robot joint; which link each sensor sits on is not confirmed.

**TL;DR**
- `original/`: the six real XDK recordings, unchanged.
  - One session: 2026-05-05, 13:38–15:12 UTC, 95 min, 10 Hz, one shared clock.
- `synthetic/`: 60 min of synthetic data per sensor (seed 42) from the joint-template engine.
  - **All six sensors come from one bank and one cycle schedule**, so they move together as on
    the real arm.
  - The bank is built from the whole 95-min recording.
- `plots/`: real first 60 min (black) vs synthetic (orange), orientation x/y/z and acceleration
  x/y/z, whole hour plus a 3-min zoom.
- `demo_limitation/`: synthetic data built from only the first 10 min of input. **Not a usable
  dataset**; it shows why the input must be at least as long as the output (see its README).
- **The physics gate fails on this data.** See the table below and
  `results/joint_template/arm6/README.md`.

## How the data was made
- Bank: `configs/robot_arm_6/joint_bank_arm6.npz`, 144 of 150 arm cycles of 37 s.
  - All 6 dropped cycles fail on cycle length.
  - No cycle is dropped because a sensor was not at rest at a cycle boundary.
- Accel: smooth real-cycle shape plus the high-frequency residual of another real cycle.
- Mag: the residual comes from the same cycle (`mag_residual: own`). Reason: the large mag
  disturbance of sensor_4 and sensor_6 while the arm moves.
- The environment columns (temperature, light, humidity, pressure) come from a config fitted on
  the first 10 min.
- Synthetic files use integer-millisecond timestamps from the generator clock. Original files
  keep their ISO timestamps and raw column names (`quat_*`, `accel_*`).

## Physics gate (seed 42 = these files; reference = real first 60 min; thresholds derived from data)

| check | result (seed 42) | over 15 seeds |
|---|---|---|
| cross-sensor coupling: activity correlation per pair (7a), 15 pairs | 12 pass; **s1–s2, s1–s6, s3–s6 fail** by 0.004–0.006 | s1–s2 and s1–s6 fail on every seed |
| all-six moving agreement (7b) | pass: 83.3 % (real 78.7 %) | 15/15 |
| lag between sensors (7c) | pass: 0 ms | 15/15 |
| mag ↔ orientation (mag_world) | pass on all six sensors | 15/15 |
| copy (replay of the recording) | **sensor_4 fails**: 9.3 % against ≤ 5 %; sensor_3 and sensor_5 not informative (reported) | sensor_4 fails 12/15 |
| omega p99 | **sensor_6 fails**: 40.85 against ≥ 40.99 °/s | sensor_6 fails 7/15 |
| validity, gravity at rest, jumps | pass | 15/15 |
| C2ST (reported only) | sensor_1–6: 0.64 / 0.63 / 0.54 / 0.61 / 0.59 / 0.64 | — |

- **7a.** The donor accel residual decouples the sensors slightly (0.004–0.012 below real). Raw
  replay passes but would copy the recording.
- **Copy, sensor_4.** Replaying sensor_4's own mag residual fixes mag_world but makes its mag
  channel nearly the recording. With the donor mag residual, copy passes but mag_world fails
  (+11 %). No setting passes both.
- **Copy, sensor_3 and sensor_5.** Their held-out real data already scores 98.2 % on the copy
  check, so the check is not informative there (rule: ≥ 97 %).
