# Joint-template engine (arm_robot): raw gate and identity outputs

Everything here was produced by the scripts in the repo root, with the flag
`motion.joint_template` ON (configs `configs/robot_arm/sensor_k_joint.json`).
All runs are deterministic: the same seed reproduces the same files.

**Status:** all physics checks pass except two.
- C2ST fails on all three sensors: a classifier can still tell synthetic from real.
- sensor_2 omega p99 is 1.2–2.2 % low against its ±1.4 % data-derived tolerance.

See PHYSICS_REPORT.md, "Joint template".

## gate/
| file | produced by | content |
|---|---|---|
| `derive_gate_thresholds.log`, `gate_thresholds.json` | `python3 derive_gate_thresholds.py` | data-derived omega p99 tolerance and C2ST threshold per sensor (copy of `configs/robot_arm/gate_thresholds.json`) |
| `regression_arm.log`, `gate_5seeds.json` | `python3 regression_arm.py --json gate/gate_5seeds.json` | flag-OFF check vs deck files, full gate for seeds 42–46, comparison with `baseline_before.json` |
| `long_duration_3h.log`, `gate_3h_per_hour.json` | `python3 long_duration_test.py --hours 3 --seed 42 --json gate/gate_3h_per_hour.json` | 3-hour run (recording is 94.9 min), gate per hour, splice continuity |

## identity/
| file | produced by | content |
|---|---|---|
| `identity_report.json` / `.md` | `python3 identity_report.py` | C2ST per sensor (real-vs-real baseline, synthetic over 5 seeds, old-generator control, by feature group), fingerprint distances F1–F5 vs a real split-half, F6 counter-rotation |

The sensor → arm-link mapping is **[USER TO VERIFY]**.

## csv/ (gzip)
| folder | content |
|---|---|
| `seeds/` | synthetic sensor_1/2/3, 60 min, seeds 42–46 (the files gated in `gate_5seeds.json`) |
| `3h/` | synthetic sensor_1/2/3, 180 min, seed 42. The per-hour files the gate used are row slices of these, by elapsed hour. |

Not included:
- The flag-OFF regenerations. They are byte-identical to the deck files, except a
  pre-existing sensor_1 `temperature` difference.
- The real recordings. The gate needs them at `ppt/arm_robot/sensor_k_real.csv`, or
  pass them with `physics_gate.py --real`.
