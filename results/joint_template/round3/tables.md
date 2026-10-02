### omega p99 vs real (5 seeds; tolerance from gate_thresholds.json)

| sensor | tol | R3_base_savgol | R3_lowpass |
|---|---|---|---|
| sensor_1 | ±3.6% | +2.2% (-0.3..+3.9), pass 3/5 | +2.2% (-0.3..+3.9), pass 3/5 |
| sensor_2 | ±1.4% | +0.9% (+0.2..+1.9), pass 3/5 | +0.9% (+0.2..+1.9), pass 3/5 |
| sensor_3 | ±0.9% | +0.2% (-0.2..+0.6), pass 5/5 | +0.2% (-0.2..+0.6), pass 5/5 |

### C2ST (mean ± sd over 5 seeds; 0.5 = indistinguishable)

| sensor | feature set | gate threshold | R3_base_savgol | R3_lowpass |
|---|---|---|---|---|
| sensor_1 | **all** | 0.621 | **0.692 ± 0.021** | **0.731 ± 0.015** |
| sensor_1 | quat | | 0.506 ± 0.025 | 0.506 ± 0.025 |
| sensor_1 | accel | | 0.659 ± 0.022 | 0.625 ± 0.018 |
| sensor_1 | angular velocity | | 0.647 ± 0.019 | 0.647 ± 0.019 |
| sensor_1 | gravity (from quat) | | 0.526 ± 0.019 | 0.526 ± 0.019 |
| sensor_1 | mag | | 0.546 ± 0.026 | 0.698 ± 0.014 |
| sensor_2 | **all** | 0.577 | **0.680 ± 0.028** | **0.642 ± 0.027** |
| sensor_2 | quat | | 0.513 ± 0.046 | 0.513 ± 0.046 |
| sensor_2 | accel | | 0.632 ± 0.017 | 0.619 ± 0.022 |
| sensor_2 | angular velocity | | 0.576 ± 0.034 | 0.576 ± 0.034 |
| sensor_2 | gravity (from quat) | | 0.547 ± 0.033 | 0.547 ± 0.033 |
| sensor_2 | mag | | 0.667 ± 0.017 | 0.605 ± 0.016 |
| sensor_3 | **all** | 0.523 | **0.688 ± 0.013** | **0.615 ± 0.024** |
| sensor_3 | quat | | 0.499 ± 0.034 | 0.499 ± 0.034 |
| sensor_3 | accel | | 0.645 ± 0.021 | 0.633 ± 0.024 |
| sensor_3 | angular velocity | | 0.529 ± 0.024 | 0.529 ± 0.024 |
| sensor_3 | gravity (from quat) | | 0.528 ± 0.051 | 0.528 ± 0.051 |
| sensor_3 | mag | | 0.681 ± 0.020 | 0.626 ± 0.022 |

### logged dt (ms), mean over seeds; real = full recording

| sensor | source | p1 | p25 | p50 | p75 | p99 | sd | excess kurtosis | lag-1 ac | lag-2 ac | % > 150 | % < 40 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sensor_1 | real | 65.2 | 97.3 | 100.1 | 103.0 | 152.3 | 16.8 | 262 | -0.20 | -0.07 | 1.02 | 0.56 |
| sensor_1 | R3_base_savgol | 62.8 | 97.0 | 100.0 | 103.0 | 160.0 | 19.1 | 452 | -0.18 | -0.04 | 1.09 | 0.58 |
| sensor_1 | R3_lowpass | 62.8 | 97.0 | 100.0 | 103.0 | 160.0 | 19.1 | 452 | -0.18 | -0.04 | 1.09 | 0.58 |
| sensor_2 | real | 63.5 | 98.2 | 100.6 | 103.0 | 138.7 | 16.6 | 286 | -0.19 | -0.09 | 0.74 | 0.61 |
| sensor_2 | R3_base_savgol | 61.2 | 98.0 | 101.0 | 103.0 | 141.8 | 17.2 | 327 | -0.19 | -0.08 | 0.82 | 0.64 |
| sensor_2 | R3_lowpass | 61.2 | 98.0 | 101.0 | 103.0 | 141.8 | 17.2 | 327 | -0.19 | -0.08 | 0.82 | 0.64 |
| sensor_3 | real | 66.8 | 98.8 | 100.1 | 101.6 | 149.0 | 16.3 | 275 | -0.14 | -0.12 | 0.99 | 0.55 |
| sensor_3 | R3_base_savgol | 65.3 | 99.0 | 100.0 | 102.0 | 155.9 | 18.5 | 465 | -0.12 | -0.09 | 1.06 | 0.57 |
| sensor_3 | R3_lowpass | 65.3 | 99.0 | 100.0 | 102.0 | 155.9 | 18.5 | 465 | -0.12 | -0.09 | 1.06 | 0.57 |

### copy metric (% of synthetic 37 s windows with corr > 0.99 to some real window)

| sensor | R3_base_savgol | R3_lowpass |
|---|---|---|
| sensor_1 | 0.0 | 0.0 |
| sensor_2 | 0.0 | 0.0 |
