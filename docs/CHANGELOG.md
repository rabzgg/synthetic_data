# Changelog

## 2026-10-13: repo cleanup (branch `chore/repo-cleanup`)

**No logic changed.** Files were moved and imports were switched to package imports
(`import validate_physics as V` → `from validation import validate_physics as V`). The only code
edits are import lines, the repo-root path (`ROOT`, `sys.path`), the `cli/main.py` path in
subprocess calls, the `validation/baseline_before.json` path, and usage strings.

Verified before committing (seed 42; outputs compared with the same commands run before the move):
- unit tests: 21/21 pass, before and after.
- Physics gate JSON, three-sensor bank (`configs/robot_arm`) and six-sensor bank
  (`configs/robot_arm_6`): **identical** (byte for byte).
- Generator output with the joint-template flag OFF (deck configs `sensor_k_normal.json`):
  **byte-identical** to before. The comparison against the deck files also gives the same result
  as before: sensor_2 and sensor_3 are byte-identical; sensor_1 differs only in `temperature`, a
  known difference that predates the joint-template work.
- Joint-template outputs, seed 42, all 9 files (3 + 6 sensors): identical SHA-256 before and after.
  The six match `data/arm6/synthetic/`.
- `data/arm6` gzip files decompress to byte-identical copies of the former CSVs.

### Moves
| from (repo root) | to |
|---|---|
| `main.py`, `build_joint_bank.py`, `extract_config.py`, `run_robot_arm_joint.sh` | `cli/` |
| `physics_gate.py`, `validate_physics.py`, `imu_consistency.py`, `sensor_identity.py`, `identity_report.py`, `c2st_permutation.py`, `derive_gate_thresholds.py`, `regression_arm.py`, `real_bootstrap.py`, `baseline_before.json` | `validation/` |
| `ablation_arm.py`, `ablation_table.py`, `empirical_floor.py`, `dump_engines.py`, `long_duration_test.py`, `plot_real_vs_syn_arm.py`, `eval_plots.py`, `stat_eval.py`, `tstr_eval.py` | `experiments/` |
| `PHYSICS_REPORT.md`, `ENGINES.md`, `ENGINE_MAP.md`, `EVAL.md` | `docs/` |
| `README.md` (long usage guide) | `docs/USAGE.md`; a new short `README.md` replaces it |
| `arm_joints_data/` | `data/arm6/`, every CSV gzip-compressed (`.csv.gz`) |

- `real_bootstrap.py` was not in the target layout. It is used only by `derive_gate_thresholds.py`
  and the tests, so it went to `validation/`.
- `core/` is unchanged.
- Run scripts from the repo root: `python3 cli/main.py ...`, `python3 validation/physics_gate.py ...`.

### Removed from the tree (still in git history at 34b07df)
Kept in `results/`: the final outputs cited in the docs (gate thresholds, latest gate runs,
`identity_report.md`, the arm6 report and its calibration and 7a evidence, the IMU-check report).
Everything below was removed.

**`results/joint_template/ablation/`** (25 files)

- `results/joint_template/ablation/README.md`
- `results/joint_template/ablation/ablation_S1_A.log`
- `results/joint_template/ablation/ablation_S1_A_no_jitter.json`
- `results/joint_template/ablation/ablation_S1_empirical.json`
- `results/joint_template/ablation/ablation_S1_empirical.log`
- `results/joint_template/ablation/ablation_S1_gaussian.json`
- `results/joint_template/ablation/ablation_S1_gaussian.log`
- `results/joint_template/ablation/ablation_S2_B.log`
- `results/joint_template/ablation/ablation_S2_B_raw_accel_mag.json`
- `results/joint_template/ablation/ablation_S2_aligned.json`
- `results/joint_template/ablation/ablation_S2_aligned.log`
- `results/joint_template/ablation/ablation_S2_lattice.json`
- `results/joint_template/ablation/ablation_S2_lattice.log`
- `results/joint_template/ablation/ablation_S2_similar.json`
- `results/joint_template/ablation/ablation_S2_similar.log`
- `results/joint_template/ablation/c2st_permutation.json`
- `results/joint_template/ablation/c2st_permutation.log`
- `results/joint_template/ablation/gate_3h_per_hour_empirical.json`
- `results/joint_template/ablation/gate_5seeds_empirical.json`
- `results/joint_template/ablation/gate_5seeds_empirical.log`
- `results/joint_template/ablation/long_duration_3h_empirical.log`
- `results/joint_template/ablation/residual_step_covariance.log`
- `results/joint_template/ablation/residual_step_covariance.py`
- `results/joint_template/ablation/step1_tables.md`
- `results/joint_template/ablation/step2_tables.md`

**`results/joint_template/arm6/`** (31 files)

- `results/joint_template/arm6/bank_cycle_attribution.log`
- `results/joint_template/arm6/bank_cycle_attribution.py`
- `results/joint_template/arm6/cross_group_activity.log`
- `results/joint_template/arm6/demo_limitation_10min_gate.log`
- `results/joint_template/arm6/derive_thresholds.log`
- `results/joint_template/arm6/derive_thresholds_bootstrap.log`
- `results/joint_template/arm6/derive_thresholds_margin.log`
- `results/joint_template/arm6/gate_3h_per_hour.json`
- `results/joint_template/arm6/gate_5seeds_before_bootstrap.json`
- `results/joint_template/arm6/gate_5seeds_before_margin.json`
- `results/joint_template/arm6/gate_thresholds_before_bootstrap.json`
- `results/joint_template/arm6/gate_thresholds_before_margin.json`
- `results/joint_template/arm6/heldout_seeds_100_109_before_bootstrap.json`
- `results/joint_template/arm6/heldout_seeds_100_109_before_bootstrap.log`
- `results/joint_template/arm6/heldout_seeds_100_109_before_margin.json`
- `results/joint_template/arm6/heldout_seeds_100_109_before_margin.log`
- `results/joint_template/arm6/long_duration_3h.log`
- `results/joint_template/arm6/plots/demo_limitation_10min/sensor_1_orientation_accel_real_vs_syn.png`
- `results/joint_template/arm6/plots/demo_limitation_10min/sensor_2_orientation_accel_real_vs_syn.png`
- `results/joint_template/arm6/plots/demo_limitation_10min/sensor_3_orientation_accel_real_vs_syn.png`
- `results/joint_template/arm6/plots/demo_limitation_10min/sensor_4_orientation_accel_real_vs_syn.png`
- `results/joint_template/arm6/plots/demo_limitation_10min/sensor_5_orientation_accel_real_vs_syn.png`
- `results/joint_template/arm6/plots/demo_limitation_10min/sensor_6_orientation_accel_real_vs_syn.png`
- `results/joint_template/arm6/plots/sensor_1_orientation_accel_real_vs_syn.png`
- `results/joint_template/arm6/plots/sensor_2_orientation_accel_real_vs_syn.png`
- `results/joint_template/arm6/plots/sensor_3_orientation_accel_real_vs_syn.png`
- `results/joint_template/arm6/plots/sensor_4_orientation_accel_real_vs_syn.png`
- `results/joint_template/arm6/plots/sensor_5_orientation_accel_real_vs_syn.png`
- `results/joint_template/arm6/plots/sensor_6_orientation_accel_real_vs_syn.png`
- `results/joint_template/arm6/regression_5seeds_before_bootstrap.log`
- `results/joint_template/arm6/regression_5seeds_before_margin.log`

**`results/joint_template/csv/`** (18 files)

- `results/joint_template/csv/3h/sensor_1_3h_seed42.csv.gz`
- `results/joint_template/csv/3h/sensor_2_3h_seed42.csv.gz`
- `results/joint_template/csv/3h/sensor_3_3h_seed42.csv.gz`
- `results/joint_template/csv/seeds/sensor_1_seed42.csv.gz`
- `results/joint_template/csv/seeds/sensor_1_seed43.csv.gz`
- `results/joint_template/csv/seeds/sensor_1_seed44.csv.gz`
- `results/joint_template/csv/seeds/sensor_1_seed45.csv.gz`
- `results/joint_template/csv/seeds/sensor_1_seed46.csv.gz`
- `results/joint_template/csv/seeds/sensor_2_seed42.csv.gz`
- `results/joint_template/csv/seeds/sensor_2_seed43.csv.gz`
- `results/joint_template/csv/seeds/sensor_2_seed44.csv.gz`
- `results/joint_template/csv/seeds/sensor_2_seed45.csv.gz`
- `results/joint_template/csv/seeds/sensor_2_seed46.csv.gz`
- `results/joint_template/csv/seeds/sensor_3_seed42.csv.gz`
- `results/joint_template/csv/seeds/sensor_3_seed43.csv.gz`
- `results/joint_template/csv/seeds/sensor_3_seed44.csv.gz`
- `results/joint_template/csv/seeds/sensor_3_seed45.csv.gz`
- `results/joint_template/csv/seeds/sensor_3_seed46.csv.gz`

**`results/joint_template/drift/`** (11 files)

- `results/joint_template/drift/README.md`
- `results/joint_template/drift/drift_diagnosis.json`
- `results/joint_template/drift/drift_diagnosis.log`
- `results/joint_template/drift/drift_diagnosis.py`
- `results/joint_template/drift/plot_yaw_drift.py`
- `results/joint_template/drift/test1_10min_bank.log`
- `results/joint_template/drift/test1_A_10min_plain_gate.json`
- `results/joint_template/drift/test1_B_10min_dedrift_gate.json`
- `results/joint_template/drift/test2_3h_dedrift.json`
- `results/joint_template/drift/test2_3h_dedrift.log`
- `results/joint_template/drift/yaw_drift.png`

**`results/joint_template/gate/`** (3 files)

- `results/joint_template/gate/derive_gate_thresholds.log`
- `results/joint_template/gate/gate_3h_per_hour.json`
- `results/joint_template/gate/long_duration_3h.log`

**`results/joint_template/identity/`** (2 files)

- `results/joint_template/identity/identity_report.json`
- `results/joint_template/identity/identity_report.log`

**`results/joint_template/joints_456/`** (19 files)

- `results/joint_template/joints_456/README.md`
- `results/joint_template/joints_456/copy_real_vs_real.log`
- `results/joint_template/joints_456/derive_thresholds.log`
- `results/joint_template/joints_456/drift/drift_diagnosis.json`
- `results/joint_template/joints_456/drift/drift_diagnosis.log`
- `results/joint_template/joints_456/gate_3h_per_hour.json`
- `results/joint_template/joints_456/gate_5seeds.json`
- `results/joint_template/joints_456/gate_thresholds.json`
- `results/joint_template/joints_456/heldout_seeds_100_109.json`
- `results/joint_template/joints_456/heldout_seeds_100_109.log`
- `results/joint_template/joints_456/long_duration_3h.log`
- `results/joint_template/joints_456/mag_residual_diagnosis.log`
- `results/joint_template/joints_456/plots/bank_10min/sensor_4_orientation_accel_real_vs_syn.png`
- `results/joint_template/joints_456/plots/bank_10min/sensor_5_orientation_accel_real_vs_syn.png`
- `results/joint_template/joints_456/plots/bank_10min/sensor_6_orientation_accel_real_vs_syn.png`
- `results/joint_template/joints_456/plots/sensor_4_orientation_accel_real_vs_syn.png`
- `results/joint_template/joints_456/plots/sensor_5_orientation_accel_real_vs_syn.png`
- `results/joint_template/joints_456/plots/sensor_6_orientation_accel_real_vs_syn.png`
- `results/joint_template/joints_456/regression_5seeds.log`

**`results/joint_template/round3/`** (11 files)

- `results/joint_template/round3/README.md`
- `results/joint_template/round3/ablation_R3_base_savgol.json`
- `results/joint_template/round3/ablation_R3_base_savgol.log`
- `results/joint_template/round3/ablation_R3_lowpass.json`
- `results/joint_template/round3/ablation_R3_lowpass.log`
- `results/joint_template/round3/lowpass_cutoffs.json`
- `results/joint_template/round3/split_check.log`
- `results/joint_template/round3/split_check.py`
- `results/joint_template/round3/step_var_outputs.log`
- `results/joint_template/round3/step_var_outputs.py`
- `results/joint_template/round3/tables.md`

Known issue, not changed (logic): `cli/main.py` with a joint-template config and a very short
`--duration` (tested: 300 s) crashes in the single-sensor C2ST (no 10 s windows). It
behaves the same before the cleanup.

