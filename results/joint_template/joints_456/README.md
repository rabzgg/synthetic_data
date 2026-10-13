# Joint-template engine for the second arm sensor group (sensor_4, sensor_5, sensor_6)

> **Superseded by `../arm6/`.** A separate bank for sensor_4–6 decouples them from sensor_1–3
> (activity correlation across groups 0.09–0.15 against 0.85–0.94 in real data). All six sensors
> now share one bank. This report is kept for the mag and drift diagnosis it contains.

Sensor → arm-link mapping: **[USER TO VERIFY]**.

**TL;DR**
- sensor_4/5/6 come from the same recording session as sensor_1/2/3 (95 min, same clock, same
  37 s cycle). They have their own joint-template bank with 147 of 151 cycles kept. Sensor_1/2/3
  are unchanged; their thresholds were re-derived and came out byte-identical.
- **The physics gate fails on every seed** (5 derivation seeds, 10 held-out seeds, every hour of a
  3-hour run). The thresholds were derived from data exactly as for sensor_1/2/3 and were **not**
  changed to make the run pass.
- Three blocking checks fail:

  | check | sensors | seeds failing | cause |
  |---|---|---|---|
  | `mag_world` | sensor_4 (+11 %) | 15/15 | **The mag residual.** It is large and motion-coupled on sensor_4 and sensor_6. Replaying it raw matches real (14.21 vs 14.17°), but raw replay fails the copy check (12.4 % / 8.2 %). |
  | `mag_world` | sensor_6 (−6 %) | 14/15 | Same as sensor_4. |
  | `mag_world` | sensor_5 (+1.5 %, tolerance ±1.3 %) | 10/15 | Same mechanism, small effect. |
  | `copy` | sensor_5 | 15/15 | **The check is uninformative here**, as for sensor_3. Real data held out from the comparison already scores 98.2 % against real 0–60 min. Not excluded: that is a gate-rule decision for the reviewer. |
  | `omega_p99` | sensor_6 | 2/10 held-out | The tolerance is tight (±1.3 %, from 5 seeds); values are 40.74–41.58 against a lower bound of 41.04. |

- Everything else passes on every seed: validity, gravity at rest, jumps, gap jumps, copy for
  sensor_4/6, and the cross-sensor checks 7b/7c.
  - Exception: in hour 3 of the 3-hour run (all past the recording), check 7b is 83.6 %, against
    a required ≥ 85 %.
- C2ST is reported only: 0.73–0.79 for sensor_4, 0.60–0.70 for sensor_5 and 0.72–0.78 for sensor_6,
  against thresholds 0.58 / 0.58 / 0.57. For sensor_1/2/3 the values are 0.66–0.71.
- The heading drift of the rest pose is again XDK fusion yaw drift: 100 % yaw, with mag_body and
  gravity_body nearly constant.

## Data and setup
- Real recordings: `ppt/arm_robot/sensor_{4,5,6}_real.csv`, copies of the raw sensor CSVs. They
  cover 13:38–15:12 UTC on 2026-05-05, the same session as sensor_1/2/3.
- Bank: `configs/robot_arm_456/joint_bank_arm456.npz`, built with
  `python3 build_joint_bank.py --real sensor_4=... --real sensor_5=... --real sensor_6=...`. It
  uses the same settings as the production bank: savgol accel/mag split, raw quaternion, no yaw
  de-drift.
  - Period 37.0 s, recording 94.9 min, 147 of 151 cycles kept.
  - The production sensor_1/2/3 bank keeps 120 of 150.
- Configs: `configs/robot_arm_456/sensor_k_joint.json`.
  - The environment columns are fitted by `extract_config.py` on the first 10 min, the same
    source as sensor_1/2/3.
  - The `motion` block is the production one, pointing at the new bank.
- Sensors 4–6 are a **separate bank**. Runs with the same seed and duration are synchronised
  within 4–6, but **not with sensor_1/2/3**. A single six-sensor bank would synchronise all six,
  but it would change the production sensor_1/2/3 output, so it was not done.
- Thresholds: `configs/robot_arm_456/gate_thresholds.json` (copy here), from
  `python3 derive_gate_thresholds.py --config-dir configs/robot_arm_456`.
  - Same formulas and seeds (42–46) as sensor_1/2/3.
  - Same blocking status: `mag_world` blocking, gravity-while-moving and C2ST reported only.

Motion level (real, angular speed of the orientation), °/s:

| | sensor_1 | sensor_2 | sensor_3 | sensor_4 | sensor_5 | sensor_6 |
|---|---|---|---|---|---|---|
| omega p99 | 44.9 | 16.4 | 43.1 | 47.2 | 35.1 | 41.6 |

## Gate results (`regression_5seeds.log`, `heldout_seeds_100_109.log`, `long_duration_3h.log`)

Pass counts: seeds 42–46 (used for the thresholds) | seeds 100–109 (held-out).

| sensor | check | real | required | synthetic, all 15 seeds | pass |
|---|---|---|---|---|---|
| sensor_4 | omega p99 | 47.23 °/s | ±3.0 % | 46.80–48.09 | 5/5, 10/10 |
| sensor_4 | **mag_world** | 14.171° | ±3.1 % (13.73–14.61) | 15.55–15.85 | **0/5, 0/10** |
| sensor_4 | copy | — | ≤ 5 % | 0.0 % | 5/5, 10/10 |
| sensor_5 | omega p99 | 35.05 °/s | ±4.2 % | 34.16–35.36 | 5/5, 10/10 |
| sensor_5 | **mag_world** | 2.775° | ±1.3 % (2.74–2.81) | 2.80–2.84 | **0/5, 5/10** |
| sensor_5 | **copy** | — | ≤ 5 % | 55–83 % | **0/5, 0/10** |
| sensor_6 | **omega p99** | 41.58 °/s | ±1.3 % | 40.74–41.58 | 5/5, **8/10** |
| sensor_6 | **mag_world** | 10.821° | ±5.5 % (10.23–11.41) | 10.01–10.33 | **1/5, 0/10** |
| sensor_6 | copy | — | ≤ 5 % | 0.0 % | 5/5, 10/10 |
| all | check 7b (moving agreement) | — | ≥ 85 % | 86.8–88.2 % | 5/5, 10/10 |
| all | check 7c (lag) | — | 0 ms | 0 ms | 5/5, 10/10 |

Validity, gravity at rest (0.21 / 0.24 / 0.43°), jumps and gap jumps pass on every seed.

Reported only, not blocking:
- Gravity while moving, median: passes on all seeds.
- Gravity while moving, p95: fails on part of the seeds (sensor_4 8/15 pass, sensor_5 2/15,
  sensor_6 14/15). The deviation is 0.02–0.1°.
- C2ST: above threshold on every seed.

3-hour run (seed 42): the gate fails in every hour with the same `mag_world` and sensor_5 `copy`
failures. In hour 3 check 7b also fails (83.6 %). Hours 2–3 lie past the recording: mag_world
spread there drops, e.g. sensor_6 9.55 / 9.14°, while the reference stays the real first 60 min.

## Why mag_world fails (`mag_residual_diagnosis.log`)
The engine replays the smooth accel/mag shape of a real cycle and adds the high-frequency
residual (raw − savgol) of a **different** real cycle (the "donor"). On sensor_1/2/3 that
residual is small (sd ≤ 3.9 µT). On sensor_4 and sensor_6 the mag residual is large **only while
the arm moves**:

| mag residual sd [µT] | sensor_1 | sensor_2 | sensor_3 | sensor_4 | sensor_5 | sensor_6 |
|---|---|---|---|---|---|---|
| at rest (x/y/z) | 1.4/1.6/0.9 | 2.0/2.3/1.2 | 0.5/0.7/0.6 | 1.5/0.9/1.5 | 0.6/0.8/0.6 | 0.5/1.1/1.5 |
| moving (x/y/z) | 0.7/0.6/0.7 | 3.4/3.9/2.6 | 0.7/0.9/1.0 | **10.5/10.9/14.3** | 1.5/2.2/1.9 | **1.8/7.4/10.2** |

- A disturbance that appears only during motion is consistent with a magnetic field from a motor
  near those sensors. That is an inference: it was not checked against the arm.
- A residual taken from another cycle no longer agrees with the orientation, so the world-frame
  mag direction gets wider (sensor_4) or narrower (sensor_6) than real.

| mag_world spread, seed 42 | real | production (random donor) | raw replay (own residual) | most-similar donor | DTW-aligned donor | lattice donor |
|---|---|---|---|---|---|---|
| sensor_4 | 14.17° | 15.72 | **14.21** | 15.73 | 15.58 | 15.74 |
| sensor_5 | 2.78° | 2.84 | **2.79** | — | — | — |
| sensor_6 | 10.82° | 10.16 | **10.86** | 10.13 | 10.02 | 10.16 |

- The existing donor variants do not help.
- Raw replay matches real but fails the copy check: 12.4 % on sensor_4 and 8.2 % on sensor_6,
  against ≤ 5 %. So it is not a fix.
- This is the same accel/mag residual issue found on sensor_1/2/3 (see `../imu_consistency/`),
  but much stronger here. No engine change was made.

## Why sensor_5 copy fails (`copy_real_vs_real.log`)
Same test that excluded sensor_3: real 60–95 min (not in the reference) vs real 0–60 min, with the
gate's copy metric.

| | sensor_1 | sensor_2 | sensor_3 | sensor_4 | sensor_5 | sensor_6 |
|---|---|---|---|---|---|---|
| real vs real, copy % | 0.0 | 0.0 | 98.2 | 1.8 | **98.2** | 0.0 |
| median max-corr | 0.958 | 0.957 | 0.997 | 0.972 | 0.993 | 0.946 |

- Real sensor_5 cycles are as repetitive as sensor_3's, so similarity to the recording cannot
  separate replay from genuine data there.
- The gate still blocks on it, because `COPY_EXCLUDE` lists only sensor_3. Adding sensor_5 is
  the reviewer's decision.

## Heading drift (`drift/drift_diagnosis.log` / `.json`)
Same diagnosis as `../drift/` (rest pose at every cycle boundary, reference = first 3 cycles).
No cycle at another rest pose was found.

| | sensor_4 | sensor_5 | sensor_6 |
|---|---|---|---|
| orientation change, last 15 min: total / yaw / tilt | 8.24 / −8.21 / 0.65° | 18.10 / −18.06 / 1.15° | 2.52 / +2.51 / 0.21° |
| yaw share | 100 % | 100 % | 100 % |
| yaw slope | −6.0°/h, R² 0.99 | −13.4°/h, R² 0.99 | +1.5°/h, R² 0.83 |
| mag_body change, last 15 min | 1.72° | 0.90° | 0.49° |
| mag_body change if the arm had physically turned | 2.46° | **10.23°** | 2.29° |

- sensor_5 gives the clearest result: a physical turn would move mag_body by 10.2°, but it moved
  0.9°. That points to a fusion heading drift.
- For sensor_4 and sensor_6 the predicted and observed changes are closer in size. The
  observation is still 2.35 / 2.65° away from the physical prediction.

## Files
| file | content |
|---|---|
| `derive_thresholds.log`, `gate_thresholds.json` | threshold derivation (copy of `configs/robot_arm_456/gate_thresholds.json`) |
| `regression_5seeds.log`, `gate_5seeds.json` | `python3 regression_arm.py --config-dir configs/robot_arm_456 --json ...` (seeds 42–46) |
| `heldout_seeds_100_109.log` / `.json` | same, seeds 100–109 |
| `long_duration_3h.log`, `gate_3h_per_hour.json` | `python3 long_duration_test.py --config-dir configs/robot_arm_456 --tag _456 --json ...` |
| `copy_real_vs_real.log` | real-vs-real copy metric, all six sensors |
| `mag_residual_diagnosis.log` | mag residual size; mag_world for donor variants and raw replay; copy of raw replay |
| `drift/` | heading-drift diagnosis |
| `plots/sensor_k_orientation_accel_real_vs_syn.png` | `python3 plot_real_vs_syn_arm.py --syn-dir out/robot_arm_joint_456_1h --sensors 4 5 6 --out ...` |

Run everything for this group: `./run_robot_arm_joint.sh 42 3600 out/robot_arm_joint_456 configs/robot_arm_456`.
