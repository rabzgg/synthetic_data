# One joint-template bank for all six arm sensors (sensor_1 … sensor_6)

Sensor → arm-link mapping: **[USER TO VERIFY]**.

This replaces the two-bank setup of `../joints_456/` (sensor_1–3 and sensor_4–6 as separate banks).
That setup broke the coupling between the two groups.

**TL;DR**
- **The cross-group defect is fixed.** All six sensors now replay one shared cycle schedule.
  - Activity correlation between groups: 0.86–0.94 (real 0.85–0.94), up from 0.09–0.15.
  - Lag: 0 ms (was −1100 ms). Six-way agreement: 83 % (real 79 %, was 49 %).
- **The bank keeps 144 of 150 cycles.** No sensor blocks cycles; 6 are dropped for their length.
  The old 3-sensor bank kept 120 of 150.
- **Cross-sensor checks now cover any number of sensors** (every pair plus N-way agreement) and
  block the gate.
  - The old fixed limits do not hold for six sensors: real data scores 78.7 % agreement (the
    limit was ≥ 85 %), and one real pair has a 100 ms lag (the limit was 0).
  - So the limits are now derived from data, like the other checks.
  - New check 7a: activity correlation per pair.
- **The gate still fails on every seed**, for four reasons:

  | failure | sensors | seeds failing | cause / trade-off |
  |---|---|---|---|
  | **7a** | pairs s1–s2, s1–s6 (all seeds); s1–s3, s1–s4, s2–s4, s3–s6 (some seeds) | 15/15 | Synthetic is 0.004–0.012 below real. The cause is the donor **accel** residual: raw replay passes. The old sensor_1–3 production data also scores s1–s2 0.946 against ≥ 0.954; the new check exposed it. |
  | **copy** | sensor_4 (3–46 %) | 12/15 | The price of the mag fix below. |
  | **omega p99** | sensor_6 | 7/15 | Tight tolerance (±1.4 %). |
  | **omega p99** | sensor_5, sensor_1 | 1/15 each | Tight tolerance (±3.8 %, ±5.9 %). |

- **mag_world passes on all six sensors and all 15 seeds**, with the mag residual taken from the
  same cycle (`mag_residual: own`).
  - Trade-off: sensor_4's mag is then replayed nearly as recorded, and the copy check catches it.
  - With the donor mag residual instead, sensor_4 mag_world fails (+11 %) but copy passes.
  - No setting passes both. Thresholds were not changed.
- **Copy rule is now data-based for all sensors.** The check is "not informative" when the
  sensor's own held-out real data already scores ≥ 97 % on it. That applies to sensor_3 and
  sensor_5 (98.2 % each); there the check is reported, not applied.
- C2ST (reported only): 0.54–0.72, lower than with the separate banks (0.60–0.79).

## Step 1: one bank, cycle accounting (`bank_cycle_attribution.py` / `.log`)
`python3 build_joint_bank.py --real sensor_1=… … --real sensor_6=… --output configs/robot_arm_6/joint_bank_arm6.npz`.
The script replays the bank's selection rules and names, for every dropped cycle, the rule and the
sensor responsible:

| bank | windows detected | kept | dropped: length off the period by > 4 % | dropped: a sensor not at rest at a boundary | dropped: pose jump |
|---|---|---|---|---|---|
| sensor_1–3 (old production) | 150 | 120 | 30 | 0 | 0 |
| sensor_4–6 (previous branch) | 151 | 147 | 4 | 0 | 0 |
| **sensor_1–6** | **150** | **144** | **6** | **0** | **0** |

- The "all sensors at rest at the boundary" condition did not drop a single cycle.
- The losses come from boundary detection. Boundaries are found on the combined motion of all
  sensors; with sensor_1–3 alone, 30 windows came out too long or too short, while with all six
  only 6 do.

Cross-group coupling (`cross_group_activity.log`; seed 42, real = first 60 min):

| | real | two banks (previous branch) | one bank |
|---|---|---|---|
| activity correlation, pairs across groups (s1–3 × s4–6) | 0.85–0.94 | **0.09–0.15** | 0.86–0.94 |
| activity correlation, pairs within a group | 0.83–0.96 | 0.83–0.95 | 0.83–0.95 |
| six-way moving agreement (7b) | 78.7 % | 49.2 % | 83.3 % |
| largest cross-correlation lag (7c) | 100 ms (s2–s5) | 1100 ms | 0 ms |

### Cross-sensor checks (gate)
- `validate_physics.check_inter_sensor` takes any number of sensors: 7a and 7c over every pair,
  7b = % of time **all** sensors agree on moving vs not.
- Before this change it was hard-wired to three sensors, so the two groups were never checked
  together.
- With a `cross_sensor` section in `gate_thresholds.json` (written by `derive_gate_thresholds.py`)
  the gate uses data-derived limits. All are blocking.

| check | limit | values |
|---|---|---|
| 7a, per pair | synthetic ≥ real − (\|real half A − half B\| + 2 sd over seeds 42–46) | 15 pairs, minimum 0.823–0.954 |
| 7b, all six | same formula | ≥ 76.7 % (real 78.7 %) |
| 7c | \|lag\| ≤ the largest real \|lag\| in the reference or its halves | 100 ms (real s2–s5) |

- Without that section (the sensor_1–3 production config), the gate keeps the old fixed limits
  (≥ 85 %, 0 ms) and has no 7a.
- That gate's values were checked unchanged on seed 42.

## Step 2: mag residual from the same cycle (`../joints_456/`, `mag_residual_diagnosis.log` there)
- New engine option `motion.mag_residual: "own"`. The mag residual (raw − savgol shape) is taken
  from the template cycle itself, at the same sample; accel keeps the donor residual.
- It is set for all six sensors in `configs/robot_arm_6/`. A unit test checks that accel is
  unchanged and only mag differs.

Seed 42 comparison:

| sensor | mag_world real | donor mag | **own mag** | copy, donor mag | **copy, own mag** |
|---|---|---|---|---|---|
| sensor_1 | 7.99° | 7.99 | 7.99 | 0.0 % | 0.0 % |
| sensor_2 | 3.54° | 3.64 | 3.55 | 0.0 % | 1.0 % |
| sensor_3 | 3.86° | 3.87 | 3.85 | not informative | not informative |
| sensor_4 | 14.17° | **15.82** | 14.18 | 0.0 % | **9.3 %** |
| sensor_5 | 2.78° | 2.82 | 2.77 | not informative | not informative |
| sensor_6 | 10.82° | **10.15** | 10.82 | 0.0 % | 0.0 % |

Over 15 seeds, sensor_4 copy with own mag is 3.1–46.4 % (passes 3/15).

**Why sensor_4 is caught.** Its motion-time mag disturbance (sd 10–14 µT) is the largest signal in
its mag channel. With the own residual that channel is the recording itself, so 37-s windows match
the recording at > 0.99.

**Why no in-between donor helps.** The disturbance is not a pure function of the motion phase. A
donor aligned to the same phase (DTW) still gives 15.6°. Each cycle carries its own disturbance.

**Over three hours** (`long_duration_3h.log`):
- With own mag, mag_world fails past the recording in hours 2–3 on sensor_4/5/6 (sensor_5 2.29–2.41°
  against ≥ 2.75°).
- Sensor_4 copy fails in hour 2 (26.8 %).
- Recommended duration stays ≤ the recording.

## Step 3: copy rule (physics_gate.copy_informative)
- **Rule.** For each sensor, the copy metric is run on its own held-out real data (after the first
  60 min) against the real first 60 min. If ≥ 97 % of those genuine windows already count as
  "copies", the check cannot tell replay from genuine data. It is then reported (INFO), not applied.
- **Code.** This replaces the per-sensor list `COPY_EXCLUDE`. Numbers are recorded in
  `gate_thresholds.json` (`copy_informative`).

| | sensor_1 | sensor_2 | sensor_3 | sensor_4 | sensor_5 | sensor_6 |
|---|---|---|---|---|---|---|
| held-out real scoring as "copy" | 0.0 % | 0.0 % | **98.2 %** | 1.8 % | **98.2 %** | 0.0 % |
| median max-corr of held-out windows | 0.958 | 0.957 | 0.997 | 0.972 | 0.993 | 0.946 |
| copy check | applied | applied | not informative | applied | not informative | applied |

- The 0.97 limit is applied to the **fraction of held-out windows** that count as copies, i.e. the
  copy check's own output.
- Applied instead to the median max-corr, it would also exclude sensor_4 (0.972). But sensor_4's
  check is informative: genuine held-out data scores only 1.8 % on it.

## Gate results (`regression_5seeds.log`, `heldout_seeds_100_109.log`; seeds 42–46 derived the thresholds, 100–109 held out)

| check | sensor / pair | synthetic, 15 seeds | limit | pass 5 + 10 seeds |
|---|---|---|---|---|
| mag_world | all six | within ±0.5 % of real | ±1.1–4.7 % | 5/5 + 10/10 on every sensor |
| 7b | all | 82.3–83.6 % | ≥ 76.7 % | 5/5 + 10/10 |
| 7c | all | 0 ms | ≤ 100 ms | 5/5 + 10/10 |
| **7a** | s1–s2 | 0.947–0.950 | ≥ 0.954 | **0/5 + 0/10** |
| **7a** | s1–s6 | 0.864–0.871 | ≥ 0.872 | **0/5 + 0/10** |
| **7a** | s3–s6 | 0.882–0.890 | ≥ 0.888 | 2/5 + 2/10 |
| **7a** | s1–s4 | 0.903–0.910 | ≥ 0.907 | 4/5 + 2/10 |
| **7a** | s1–s3 | 0.941–0.946 | ≥ 0.943 | 4/5 + 6/10 |
| **7a** | s2–s4 | 0.916–0.921 | ≥ 0.918 | 4/5 + 7/10 |
| 7a | the other 9 pairs | | | 5/5 + 10/10 |
| **copy** | sensor_4 | 3.1–46.4 % | ≤ 5 % | 0/5 + 3/10 |
| copy | sensor_1, 2, 6 | ≤ 2.1 % | ≤ 5 % | 5/5 + 10/10 |
| **omega p99** | sensor_6 | 40.77–41.46 °/s | 40.99–42.17 | 2/5 + 8/10 |
| **omega p99** | sensor_5 | 33.71–34.62 | 33.73–36.37 | 4/5 + 10/10 |
| **omega p99** | sensor_1 | 43.83–48.21 | 42.29–47.57 | 5/5 + 9/10 |
| omega p99 | sensor_2, 3, 4 | | | 5/5 + 10/10 |
| validity, gravity at rest, jumps, gap jumps | all six | | | 5/5 + 10/10 |
| C2ST (reported) | 0.64–0.72 / 0.56–0.64 / 0.54–0.62 / 0.56–0.63 / 0.57–0.64 / 0.61–0.69 | | ≤ 0.59–0.61 | — |

**7a cause** (`check7a_diagnosis.log`, seed 42):
- Activity is the rolling sd of |accel|. With the accel residual taken from the template's own cycle
  (raw replay, diagnosis only), every pair passes. The mag setting has no effect on 7a.
- So this is the known donor accel-residual issue (`../imu_consistency/`), now visible as a small
  decoupling between sensors.
- Raw replay is not a production option: it breaks the copy check.

## Files
| file | content |
|---|---|
| `bank_cycle_attribution.py` / `.log` | dropped cycles by rule and sensor, for banks 1–3, 4–6 and 1–6 |
| `cross_group_activity.log` | activity correlation, agreement and lag: real vs two banks vs one bank |
| `derive_thresholds.log`, `gate_thresholds.json` | `python3 derive_gate_thresholds.py --config-dir configs/robot_arm_6` |
| `regression_5seeds.log`, `gate_5seeds.json` | `python3 regression_arm.py --config-dir configs/robot_arm_6 --json …` (seeds 42–46) |
| `heldout_seeds_100_109.log` / `.json` | same, seeds 100–109 |
| `long_duration_3h.log`, `gate_3h_per_hour.json` | `python3 long_duration_test.py --config-dir configs/robot_arm_6 --tag _arm6 --json …` |
| `check7a_diagnosis.log` | 7a per pair: production vs raw replay vs donor mag |
| `demo_limitation_10min_gate.log` | gate on the 10-min-input demo (fails 12 checks, as expected) |
| `plots/`, `plots/demo_limitation_10min/` | real vs synthetic orientation and acceleration per sensor (`plot_real_vs_syn_arm.py --sensors 1 2 3 4 5 6`) |

Run everything: `./run_robot_arm_joint.sh 42 3600 out/arm6 configs/robot_arm_6`.
