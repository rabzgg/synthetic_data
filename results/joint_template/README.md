# Joint-template engine (arm_robot): raw gate and identity outputs

Everything here was produced by the scripts in the repo root, with the flag
`motion.joint_template` ON (configs `configs/robot_arm/sensor_k_joint.json`).
All runs are deterministic: the same seed reproduces the same files.

**Status:** the physics gate passes on all 5 seeds and on every hour of a 3-hour run.
C2ST is reported, not blocking: a classifier can still tell synthetic from real on all
three sensors (0.69 / 0.68 / 0.69 vs thresholds 0.583 / 0.606 / 0.566).

See PHYSICS_REPORT.md, "Joint template".

`gate/`, `identity/` and `csv/` hold the **current** engine: empirical timestamp offsets,
real dropped ticks, savgol accel/mag split. The thresholds are from round 3. The earlier
states are in git history.
- `ablation/`: review round 2 (one ablation per cause; tables use the thresholds of that time).
- `round3/`: review round 3 (leak-free split experiment, re-derived omega tolerance,
  permutation C2ST threshold, dropped ticks).

## gate/
| file | produced by | content |
|---|---|---|
| `derive_gate_thresholds.log`, `gate_thresholds.json` | `python3 derive_gate_thresholds.py` | data-derived omega p99 tolerance and C2ST threshold per sensor (copy of `configs/robot_arm/gate_thresholds.json`) |
| `regression_arm.log`, `gate_5seeds.json` | `python3 regression_arm.py --json gate/gate_5seeds.json` | flag-OFF check vs deck files, full gate for seeds 42–46 (C2ST shown as INFO), comparison with `baseline_before.json` |
| `long_duration_3h.log`, `gate_3h_per_hour.json` | `python3 long_duration_test.py --hours 3 --seed 42 --json gate/gate_3h_per_hour.json` | 3-hour run (recording is 94.9 min), gate per hour, splice continuity |

## identity/
| file | produced by | content |
|---|---|---|
| `identity_report.json` / `.md` | `python3 identity_report.py` | C2ST per sensor (permutation null, synthetic over 5 seeds, old-generator control, by feature group), fingerprint distances F1–F5 vs a real split-half, F6 counter-rotation |

The sensor → arm-link mapping is **[USER TO VERIFY]**.

## ablation/
| file | produced by | content |
|---|---|---|
| `README.md` | — | the round-2 report (tables for Steps 1–3) |
| `ablation_<variant>.json` / `.log`, `step1_tables.md`, `step2_tables.md` | `python3 ablation_arm.py --name <variant> --motion ...`, `python3 ablation_table.py ...` | omega p99, C2ST overall + per feature group, dt statistics, copy metric; 5 seeds per variant |
| `c2st_permutation.json` / `.log` | `python3 c2st_permutation.py --syn-dir out/ablation/S1_empirical` | permutation null (100×) and both thresholds |
| `gate_5seeds_empirical.json` / `.log` | `physics_gate.check_physics_gate` on the S1_empirical files | full gate, seeds 42–46 |
| `long_duration_3h_empirical.log`, `gate_3h_per_hour_empirical.json` | `python3 long_duration_test.py --json ...` | 3-hour run, gate per hour |
| `residual_step_covariance.py` / `.log` | (itself) | smooth vs residual step covariance (Step 2 mechanism) |

## round3/
| file | produced by | content |
|---|---|---|
| `README.md` | — | the round-3 report |
| `split_check.py` / `.log` | (itself; needs the experimental low-pass bank, see README) | in-cycle step correlation and donor/raw step variance, savgol vs low-pass |
| `step_var_outputs.py` / `.log` | (itself) | output step variance vs real |
| `ablation_R3_*.json` / `.log`, `tables.md` | `ablation_arm.py`, `ablation_table.py` | base (savgol) vs low-pass split |
| `lowpass_cutoffs.json` | `build_joint_bank.py --am-split lowpass` | chosen cutoffs and the rule |

## csv/ (gzip)
| folder | content |
|---|---|
| `seeds/` | synthetic sensor_1/2/3, 60 min, seeds 42–46 (the files gated in `gate_5seeds.json`; ~0.3–0.7 % of rows dropped like the real logger) |
| `3h/` | synthetic sensor_1/2/3, 180 min, seed 42. The per-hour files the gate used are row slices of these, by elapsed hour. |

Not included:
- The flag-OFF regenerations. They are byte-identical to the deck files, except a
  pre-existing sensor_1 `temperature` difference.
- The real recordings. The gate needs them at `ppt/arm_robot/sensor_k_real.csv`, or
  pass them with `physics_gate.py --real`.
