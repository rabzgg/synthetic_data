# Joint-template engine (arm_robot): final gate and identity outputs

Only the final outputs cited in the docs are kept here. Earlier rounds (ablation, round 3, drift,
the separate sensor_4–6 bank, per-seed CSVs) were removed from the tree in the repo cleanup.
They are in git history at 34b07df; the list is in `docs/CHANGELOG.md`.

Sensor → arm-link mapping: **[USER TO VERIFY]**.

| folder | content |
|---|---|
| `arm6/` | **six-sensor bank (current):** report (`README.md`), thresholds, gate on seeds 42–46 and held-out 100–109, calibration |
| `gate/` | three-sensor bank (`configs/robot_arm/`): thresholds, gate on seeds 42–46 (`regression_arm.log`, `gate_5seeds.json`) and held-out 100–109 |
| `identity/` | `identity_report.md`: C2ST per sensor and fingerprint distances, three-sensor bank (`python3 validation/identity_report.py`) |
| `imu_consistency/` | gravity-while-moving (reported) and mag ↔ orientation (blocking) checks: definitions, tolerances, results |

All runs are deterministic: the same seed reproduces the same files. The real recordings are not
in this folder; the gate reads them from the path stored in the bank (`ppt/arm_robot/sensor_k_real.csv`).
Copies are in `data/arm6/original/`.
