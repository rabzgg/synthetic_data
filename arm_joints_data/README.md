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

| check | result (seed 42) | over 15 seeds (42–46 + held-out 100–109) |
|---|---|---|
| cross-sensor coupling: activity correlation per pair (7a), 15 pairs | 11 pass; **s1–s2, s1–s6, s3–s6, s4–s5 fail** by 0.002–0.007 below the limit | 4–7 pairs fail on every seed |
| all-six moving agreement (7b) | pass: 83.3 % (real 78.7 %) | 15/15 |
| lag between sensors (7c) | pass: 0 ms | 15/15 |
| mag ↔ orientation (mag_world) | pass on all six sensors | 15/15 |
| omega p99 | 5 pass; **sensor_6 fails**: 40.85 against ≥ 40.89 °/s | sensor_6 fails 3/15, others 15/15 |
| copy (replay of the recording) | sensor_1, 2, 6 pass; sensor_3, 5 not informative; sensor_4 9.3 % (reported) | sensor_1, 2, 6 pass 15/15 |
| validity, gravity at rest, jumps | pass | 15/15 |
| C2ST (reported only) | sensor_1–6: 0.64 / 0.63 / 0.54 / 0.61 / 0.59 / 0.64 | — |

- **Tolerances of omega p99 and 7a** = 2·sqrt(σ_seed² + σ_real²), where σ_real is the real sampling
  uncertainty from a block bootstrap over arm cycles. Genuine real data (minutes 35–95, scored as
  if synthetic) fails 1 of these 21 checks.
- **7a.** Synthetic sits consistently below real on several pairs, e.g. s1–s2 0.950 vs 0.958 with a
  real uncertainty of 0.002. The cause is the donor accel residual, which decouples the sensors
  slightly; raw replay passes but would copy the recording.
- **Copy, sensor_4: reported, not blocking (user decision).** sensor_4's magnetometer is strongly
  disturbed while the arm moves, and a residual from another cycle breaks mag ↔ orientation
  consistency. We chose physical consistency over novelty for this channel: the mag residual comes
  from the same cycle. Its copy value (3–46 % over 15 seeds) is reported.
- **Copy, sensor_3 and sensor_5: not informative (data rule).** The check is not applied when the
  sensor's own held-out real data (after the first 60 min) already scores ≥ 97 % on it. The 0.97
  is the **fraction of held-out windows** counted as copies, i.e. the copy check's own output.
  sensor_3 and sensor_5 score 98.2 %; the other sensors 0–1.8 %.
