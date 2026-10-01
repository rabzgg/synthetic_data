# Sensor identity report (Level 1)

Level 1 only: is synthetic sensor_k recognisable as real sensor_k. Sensor -> arm-link mapping is **[USER TO VERIFY]**; nothing here makes a Level-2 claim.

## Fingerprint summary (real | joint template | old generator)

| sensor | field | real | joint template | old generator |
|---|---|---|---|---|
| sensor_1 | F1_mean_gravity_dir | [-0.995, -0.077, -0.014] | [-0.995, -0.077, -0.011] | [-0.992, -0.063, 0.014] |
| sensor_1 | F2_axis_mean_abs | [0.77, 0.25, 0.22] | [0.76, 0.26, 0.22] | [0.48, 0.56, 0.47] |
| sensor_1 | F3_median_deg | 9.6 | 10.2 | 61.0 |
| sensor_1 | F3_pct_near_vertical(<20deg) | 64.0 | 62.6 | 3.5 |
| sensor_1 | F4_p50 | 35.1 | 35.0 | 21.8 |
| sensor_1 | F4_p99 | 51.0 | 44.5 | 741.5 |
| sensor_1 | F5_mag_median | 185.5 | 185.9 | 59.1 |
| sensor_1 | rest_fallback | False | False | True |
| sensor_1 | F5_mean_vec | [56.0, -41.0, 160.0] | [57.0, -41.0, 161.0] | [26.0, 27.0, 36.0] |
| sensor_2 | F1_mean_gravity_dir | [-0.991, -0.089, 0.077] | [-0.991, -0.09, 0.077] | [-0.99, -0.087, 0.087] |
| sensor_2 | F2_axis_mean_abs | [0.18, 0.72, 0.54] | [0.2, 0.7, 0.54] | [0.44, 0.57, 0.44] |
| sensor_2 | F3_median_deg | 78.7 | 77.5 | 62.5 |
| sensor_2 | F3_pct_near_vertical(<20deg) | 0.0 | 0.0 | 1.7 |
| sensor_2 | F4_p50 | 10.4 | 9.7 | 5.5 |
| sensor_2 | F4_p99 | 19.5 | 16.6 | 14.0 |
| sensor_2 | F5_mag_median | 56.1 | 56.2 | 57.3 |
| sensor_2 | rest_fallback | False | False | False |
| sensor_2 | F5_mean_vec | [42.0, -22.0, 35.0] | [42.0, -22.0, 35.0] | [42.0, -9.0, -36.0] |
| sensor_3 | F1_mean_gravity_dir | [-0.408, -0.784, 0.163] | [-0.418, -0.777, 0.168] | [-0.404, -0.817, 0.223] |
| sensor_3 | F2_axis_mean_abs | [0.38, 0.24, 0.84] | [0.39, 0.24, 0.84] | [0.6, 0.41, 0.5] |
| sensor_3 | F3_median_deg | 83.8 | 82.9 | 65.2 |
| sensor_3 | F3_pct_near_vertical(<20deg) | 0.0 | 0.1 | 3.1 |
| sensor_3 | F4_p50 | 8.6 | 8.9 | 8.7 |
| sensor_3 | F4_p99 | 45.2 | 43.6 | 39.8 |
| sensor_3 | F5_mag_median | 54.9 | 55.0 | 61.3 |
| sensor_3 | rest_fallback | False | False | True |
| sensor_3 | F5_mean_vec | [47.0, 21.0, 26.0] | [47.0, 21.0, 26.0] | [49.0, 22.0, 23.0] |

## Fingerprint distances (to own real sensor / to nearest other real sensor)

| sensor | case | F1 | F2 | F3 | F4 | F5 |
|---|---|---|---|---|---|---|
| sensor_1 | real_k vs nearest other real | 0.0394 | 0.3870 | 47.1047 | 0.4963 | 111.7962 |
| sensor_1 | syn_new | 0.0013 / 0.0384 ✓ | 0.0089 / 0.3842 ✓ | 0.8632 / 46.6137 ✓ | 0.0434 / 0.4835 ✓ | 0.9568 / 112.7528 ✓ |
| sensor_1 | syn_leakfree | 0.0014 / 0.0384 ✓ | 0.0091 / 0.3839 ✓ | 0.8710 / 46.5639 ✓ | 0.0467 / 0.4860 ✓ | 1.0042 / 112.7813 ✓ |
| sensor_1 | syn_old | 0.0297 / 0.0354 ✓ | 0.2816 / 0.1758 ✗ | 31.4906 / 15.6140 ✗ | 0.2985 / 0.4272 ✓ | 110.3187 / 12.6692 ✗ |
| sensor_2 | real_k vs nearest other real | 0.0394 | 0.3250 | 6.9497 | 0.3346 | 4.3155 |
| sensor_2 | syn_new | 0.0005 / 0.0393 ✓ | 0.0126 / 0.3164 ✓ | 0.6601 / 7.4913 ✓ | 0.0419 / 0.3494 ✓ | 0.3500 / 4.1553 ✓ |
| sensor_2 | syn_leakfree | 0.0004 / 0.0394 ✓ | 0.0122 / 0.3171 ✓ | 0.7241 / 7.5825 ✓ | 0.0435 / 0.3504 ✓ | 0.3128 / 4.1865 ✓ |
| sensor_2 | syn_old | 0.0158 / 0.0442 ✓ | 0.1658 / 0.2666 ✓ | 13.1176 / 20.0305 ✓ | 0.3961 / 0.4820 ✓ | 4.0536 / 6.6414 ✓ |
| sensor_3 | real_k vs nearest other real | 0.4560 | 0.3250 | 6.9497 | 0.3346 | 4.3155 |
| sensor_3 | syn_new | 0.0075 / 0.4515 ✓ | 0.0100 / 0.3278 ✓ | 0.6028 / 6.5313 ✓ | 0.0416 / 0.3480 ✓ | 0.3432 / 4.4261 ✓ |
| sensor_3 | syn_leakfree | 0.0076 / 0.4516 ✓ | 0.0105 / 0.3281 ✓ | 0.6126 / 6.5083 ✓ | 0.0461 / 0.3522 ✓ | 0.3452 / 4.4265 ✓ |
| sensor_3 | syn_old | 0.1074 / 0.4902 ✓ | 0.2409 / 0.2038 ✗ | 20.6084 / 13.6954 ✗ | 0.2237 / 0.2240 ✓ | 7.4451 / 6.0277 ✗ |

## Classifier confusion matrices (rows = true sensor_1..3, cols = predicted)

### feature set: all

| case | accuracy | recall s1/s2/s3 | confusion |
|---|---|---|---|
| a_real_holdout | 1.000 | 1.000 / 1.000 / 1.000 | [[122, 0, 0], [0, 122, 0], [0, 0, 122]] |
| b_syn_new | 1.000 | 1.000 / 1.000 / 1.000 | [[361, 0, 0], [0, 360, 0], [0, 0, 360]] |
| b2_syn_leakfree | 1.000 | 1.000 / 1.000 / 1.000 | [[361, 0, 0], [0, 360, 0], [0, 0, 360]] |
| c_syn_old_deck | 0.866 | 0.598 / 1.000 / 1.000 | [[216, 131, 14], [0, 360, 0], [0, 0, 360]] |
| d_shuffled_labels | 0.315 | 0.324 / 0.319 / 0.300 | [[117, 115, 129], [122, 115, 123], [122, 130, 108]] |

### feature set: no_mag

| case | accuracy | recall s1/s2/s3 | confusion |
|---|---|---|---|
| a_real_holdout | 1.000 | 1.000 / 1.000 / 1.000 | [[122, 0, 0], [0, 122, 0], [0, 0, 122]] |
| b_syn_new | 1.000 | 1.000 / 1.000 / 1.000 | [[361, 0, 0], [0, 360, 0], [0, 0, 360]] |
| b2_syn_leakfree | 1.000 | 1.000 / 1.000 / 1.000 | [[361, 0, 0], [0, 360, 0], [0, 0, 360]] |
| c_syn_old_deck | 0.994 | 0.981 / 1.000 / 1.000 | [[354, 6, 1], [0, 360, 0], [0, 0, 360]] |
| d_shuffled_labels | 0.327 | 0.310 / 0.325 / 0.344 | [[112, 129, 120], [127, 117, 116], [122, 114, 124]] |

### feature set: frame_safe

| case | accuracy | recall s1/s2/s3 | confusion |
|---|---|---|---|
| a_real_holdout | 1.000 | 1.000 / 1.000 / 1.000 | [[122, 0, 0], [0, 122, 0], [0, 0, 122]] |
| b_syn_new | 1.000 | 1.000 / 1.000 / 1.000 | [[361, 0, 0], [0, 360, 0], [0, 0, 360]] |
| b2_syn_leakfree | 1.000 | 1.000 / 1.000 / 1.000 | [[361, 0, 0], [0, 360, 0], [0, 0, 360]] |
| c_syn_old_deck | 0.973 | 0.920 / 1.000 / 1.000 | [[332, 26, 3], [0, 360, 0], [0, 0, 360]] |
| d_shuffled_labels | 0.329 | 0.319 / 0.344 / 0.325 | [[115, 113, 133], [126, 124, 110], [120, 123, 117]] |

## F6 inter-sensor relations

| set | act_corr_1-2 | counter_rot_pct_1-2 | act_corr_1-3 | counter_rot_pct_1-3 | act_corr_2-3 | counter_rot_pct_2-3 | amp_ratio_2/1_median | amp_ratio_3/1_median |
|---|---|---|---|---|---|---|---|---|
| real | 0.958 | 26.707 | 0.949 | 0.306 | 0.923 | 0.268 | 0.158 | 0.391 |
| syn_new | 0.950 | 8.965 | 0.938 | 0.258 | 0.920 | 0.000 | 0.159 | 0.394 |
| syn_old | -0.011 | 50.073 | -0.006 | 51.016 | -0.000 | 54.324 | 0.086 | 0.261 |
| syn_leakfree | 0.949 | 8.007 | 0.934 | 0.109 | 0.918 | 0.000 | 0.159 | 0.393 |
