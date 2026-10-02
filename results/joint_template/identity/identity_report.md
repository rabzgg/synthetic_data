# Sensor identity report (Level 1)

Can synthetic sensor_k be told apart from real sensor_k? Sensor -> arm-link mapping is **[USER TO VERIFY]**; nothing here makes a Level-2 claim.

## C2ST (balanced accuracy; 0.5 = indistinguishable)

| sensor | real vs real (baseline) | threshold | synthetic (5 seeds) | old generator (control) | test has power | synthetic passes |
|---|---|---|---|---|---|---|
| sensor_1 | 0.444 ± 0.086 | 0.621 | 0.694 ± 0.022 | 0.977 | yes | **no** |
| sensor_2 | 0.419 ± 0.076 | 0.577 | 0.695 ± 0.021 | 0.999 | yes | **no** |
| sensor_3 | 0.397 ± 0.059 | 0.523 | 0.766 ± 0.020 | 1.000 | yes | **no** |

C2ST restricted to one feature group (seed 42):

| sensor | quat | accel | angular velocity | gravity (from quat) | mag |
|---|---|---|---|---|---|
| sensor_1 | 0.465 | 0.652 | 0.693 | 0.521 | 0.536 |
| sensor_2 | 0.470 | 0.624 | 0.609 | 0.523 | 0.691 |
| sensor_3 | 0.503 | 0.652 | 0.716 | 0.515 | 0.711 |

## Fingerprint distances (F1-F3 Wasserstein, F4 KS, F5 Wasserstein)

| sensor | pair | F1 | F2 | F3 | F4 | F5 |
|---|---|---|---|---|---|---|
| sensor_1 | real half A vs half B | 0.0002 | 0.0016 | 0.1310 | 0.0058 | 0.1987 |
| sensor_1 | synthetic vs real | 0.0006 | 0.0008 | 0.0664 | 0.0179 | 0.1107 |
| sensor_1 | old generator vs real | 0.0295 | 0.2812 | 31.4509 | 0.2961 | 110.6179 |
| sensor_2 | real half A vs half B | 0.0001 | 0.0025 | 0.1151 | 0.0118 | 0.0538 |
| sensor_2 | synthetic vs real | 0.0004 | 0.0016 | 0.0843 | 0.0201 | 0.2511 |
| sensor_2 | old generator vs real | 0.0158 | 0.1656 | 13.0876 | 0.3944 | 4.0584 |
| sensor_3 | real half A vs half B | 0.0004 | 0.0009 | 0.0600 | 0.0069 | 0.0403 |
| sensor_3 | synthetic vs real | 0.0010 | 0.0007 | 0.0303 | 0.0087 | 0.1029 |
| sensor_3 | old generator vs real | 0.1073 | 0.2409 | 20.6081 | 0.2230 | 7.4652 |

## Fingerprint summary (real | synthetic | old generator)

| sensor | field | real | synthetic | old generator |
|---|---|---|---|---|
| sensor_1 | F1_mean_gravity_dir | [-0.995, -0.077, -0.012] | [-0.995, -0.076, -0.012] | [-0.992, -0.063, 0.014] |
| sensor_1 | F2_axis_mean_abs | [0.77, 0.25, 0.22] | [0.77, 0.25, 0.22] | [0.48, 0.56, 0.47] |
| sensor_1 | F3_median_deg | 9.6 | 9.7 | 61.0 |
| sensor_1 | F3_pct_near_vertical(<20deg) | 64.1 | 63.9 | 3.5 |
| sensor_1 | F4_p50 | 35.1 | 34.8 | 21.8 |
| sensor_1 | F4_p99 | 54.2 | 45.2 | 741.5 |
| sensor_1 | F5_mag_median | 185.9 | 185.8 | 59.1 |
| sensor_1 | rest_fallback | False | False | True |
| sensor_1 | F5_mean_vec | [56.0, -41.0, 160.0] | [56.0, -41.0, 160.0] | [26.0, 27.0, 36.0] |
| sensor_2 | F1_mean_gravity_dir | [-0.991, -0.09, 0.077] | [-0.991, -0.09, 0.077] | [-0.99, -0.087, 0.087] |
| sensor_2 | F2_axis_mean_abs | [0.18, 0.72, 0.54] | [0.18, 0.72, 0.54] | [0.44, 0.57, 0.44] |
| sensor_2 | F3_median_deg | 78.7 | 78.7 | 62.5 |
| sensor_2 | F3_pct_near_vertical(<20deg) | 0.0 | 0.0 | 1.7 |
| sensor_2 | F4_p50 | 10.3 | 10.1 | 5.5 |
| sensor_2 | F4_p99 | 21.0 | 18.2 | 14.0 |
| sensor_2 | F5_mag_median | 56.3 | 56.2 | 57.3 |
| sensor_2 | rest_fallback | False | False | False |
| sensor_2 | F5_mean_vec | [42.0, -22.0, 35.0] | [42.0, -22.0, 35.0] | [42.0, -9.0, -36.0] |
| sensor_3 | F1_mean_gravity_dir | [-0.408, -0.784, 0.163] | [-0.41, -0.783, 0.164] | [-0.404, -0.817, 0.223] |
| sensor_3 | F2_axis_mean_abs | [0.38, 0.24, 0.84] | [0.38, 0.24, 0.84] | [0.6, 0.41, 0.5] |
| sensor_3 | F3_median_deg | 83.8 | 83.8 | 65.2 |
| sensor_3 | F3_pct_near_vertical(<20deg) | 0.0 | 0.0 | 3.1 |
| sensor_3 | F4_p50 | 8.6 | 8.6 | 8.7 |
| sensor_3 | F4_p99 | 45.5 | 45.4 | 39.8 |
| sensor_3 | F5_mag_median | 54.7 | 54.9 | 61.3 |
| sensor_3 | rest_fallback | False | False | True |
| sensor_3 | F5_mean_vec | [47.0, 21.0, 26.0] | [47.0, 21.0, 26.0] | [49.0, 22.0, 23.0] |

## F6 counter-rotation about the vertical (%)

| metric | real | synthetic (5 seeds) | old generator |
|---|---|---|---|
| 1-2 per-sample rel50 | 1.2 | 0.9 ± 0.5 | 52.6 |
| 1-2 per-sample fixed3 | 1.1 | 5.4 ± 0.3 | 50.0 |
| 1-2 episodes | 100.0 | 100.0 ± 0.0 | 42.0 |
| 1-2 n_episodes | 12.0 | 1.4 ± 0.9 | 219.0 |
| 2-3 per-sample rel50 | 0.1 | 0.2 ± 0.1 | 57.1 |
| 2-3 per-sample fixed3 | 0.0 | 0.0 ± 0.0 | 54.1 |
| 2-3 episodes | 3.2 | 0.9 ± 0.9 | 65.0 |
| 2-3 n_episodes | 155.0 | 92.2 ± 1.6 | 160.0 |
| 1-3 per-sample rel50 | 0.0 | 0.0 ± 0.0 | 53.9 |
| 1-3 per-sample fixed3 | 0.0 | 0.2 ± 0.1 | 51.0 |
| 1-3 episodes | 0.0 | 0.0 ± 0.0 | 52.8 |
| 1-3 n_episodes | 607.0 | 389.6 ± 0.5 | 180.0 |
