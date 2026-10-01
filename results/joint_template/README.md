# Joint-template engine (arm_robot): raw gate and identity outputs

Everything here was produced by the scripts in the repo root, with the flag
`motion.joint_template` ON (configs `configs/robot_arm/sensor_k_joint.json`).
All runs are deterministic: the same seed reproduces the same files.

## gate/
| file | produced by | content |
|---|---|---|
| `regression_arm.log` | `python3 regression_arm.py --json gate/gate_5seeds.json` | flag-OFF check vs deck files, full physics gate for seeds 42–46, comparison with `baseline_before.json` |
| `gate_5seeds.json` | (same) | every gate check per seed: value, threshold, pass/fail |
| `long_duration_3h.log` | `python3 long_duration_test.py --hours 3 --seed 42 --json gate/gate_3h_per_hour.json` | 3-hour run (recording is 94.9 min), gate per hour, splice continuity |
| `gate_3h_per_hour.json` | (same) | schedule info + every gate check per hour |

## identity/
| file | produced by | content |
|---|---|---|
| `identity_report.json` / `.md` | `python3 identity_report.py` | fingerprints F1–F6 (real / joint template / old generator), distances, classifier confusion matrices for cases a, b, b2, c, d × feature sets all / no_mag / frame_safe |

Verdict: the identity test is **too weak to gate on**. The old generator (control c)
passes it for sensor_2. It is informational only in `physics_gate.py --identity`.
The sensor → arm-link mapping is **[USER TO VERIFY]**.

## csv/ (gzip)
| folder | content |
|---|---|
| `seeds/` | synthetic sensor_1/2/3, 60 min, seeds 42–46 (the files gated in `gate_5seeds.json`) |
| `3h/` | synthetic sensor_1/2/3, 180 min, seed 42. The per-hour files the gate used are row slices of these, by elapsed hour. |
| `leakfree/` | identity case b2: joint template built only from held-out real cycles |

Not included:
- The flag-OFF regenerations. They are byte-identical to the deck files, except a
  pre-existing sensor_1 `temperature` difference.
- The real recordings. The gate needs them at `ppt/arm_robot/sensor_k_real.csv`, or
  pass them with `physics_gate.py --real`.
