# Slow drift of the arm's rest orientation: XDK heading drift?

Sensor → arm-link mapping: **[USER TO VERIFY]**.

**TL;DR**
- **Step 1 (diagnosis): the drift of the rest orientation is a heading (yaw) drift of the XDK
  fusion, not robot motion.**
  - Yaw is 99–100 % of the drift.
  - gravity_body changes by ≤ 0.8° and mag_body by ≤ 2.6°.
  - The decisive test is on mag_body. If the arm had really turned, sensor_1's mag_body would have
    moved 16 µT; it moved 0.2 µT along that direction. sensor_3 behaves the same way.
  - For sensor_2 the test has no power (2.9° of yaw is below its mag noise).
  - The drift is not driven by temperature. sensor_1 is linear (+22°/h, R² 1.00), sensor_2 is
    roughly linear (+1.8°/h), and sensor_3 is non-linear.
- **Step 2 (heading-drift model, new flag, default OFF): the targets were not met.**
  - Test 1 (10-min bank + model): the model fixes the quaternion feature group (sensor_1 C2ST quat
    0.85 → 0.51). But accel, gravity and mag stay separable (0.74–0.85), so overall C2ST stays at
    0.85–0.89, not ~0.68. mag_world still fails.
  - Test 2 (95-min bank + model, 3 h): the physics gate passes every hour. In hour 3, C2ST rises to
    0.93–1.00, driven only by the quaternion group: the extrapolated heading lies outside the
    heading range of the real comparison window. The accel, gravity and mag groups improve.
  - Conclusion: the limitation "real input ≥ output duration" still applies.

## Step 1: diagnosis (`drift_diagnosis.py` / `.log` / `.json`, `yaw_drift.png`)

**Setup.**
- Same rest pose every cycle: rest samples within ±1 s of each cycle boundary of the joint-template
  bank, on the full real recording.
- Reference = mean of the first 3 cycles.
- 5 of 120 cycles (at 16.4, 17.0, 53.5, 74.4 and 75.1 min, the same in all sensors) sit at another
  rest pose: the accel gravity differs by 6.8° (52° for sensor_3), and the quaternion tilt agrees.
  They are left out. The pose is identified from accel only, which is independent of the fusion.

| | sensor_1 | sensor_2 | sensor_3 |
|---|---|---|---|
| a) mag_body direction change, last 15 min (p95 / max over all cycles) | 0.32° (0.48 / 0.59) | 1.12° (1.83 / 2.57) | 0.61° (1.21 / 2.14) |
| b) gravity_body (accel) change, last 15 min (max) | 0.48° (0.52) | 0.20° (0.24) | 0.72° (0.78) |
| c) orientation change, last 15 min: total / yaw / tilt | 30.27 / +30.26 / 0.45° | 2.89 / +2.88 / 0.20° | 4.75 / −4.70 / 0.67° |
| c) yaw share | **100 %** | **100 %** | **99 %** |
| d) yaw trend | +22.2°/h, R² 1.00, residual sd 0.70° | +1.8°/h, R² 0.90, sd 0.27° | −4.3°/h, R² 0.77, sd 1.09° (non-linear) |
| d) temperature | R² time 1.00 → time+temp 1.00 | 0.90 → 0.92 | 0.77 → 0.77 |
| **e) mag_body change if the arm had physically turned** | **16.0 µT** (5.4°) | 0.43 µT (0.5°) | 1.75 µT (1.9°) |
| e) observed mag_body change along that direction | 0.18 µT | 0.49 µT | −0.38 µT |
| e) regression slope, observed vs physical prediction (1 = physical, 0 = fusion drift) | **−0.01** | +0.77 (no power) | **−0.15** |

- **Gravity_body alone cannot tell the two hypotheses apart.** A physical turn about the vertical
  does not change it either; it only rules out tilt drift. The discriminating test is (e).
- **Temperature does not explain the yaw.** Yaw vs temperature traces loops (hysteresis) in
  `yaw_drift.png`, and adding temperature to time does not improve the fit.
- **Verdict:**
  - The reviewer's criteria (mag_body and gravity_body constant, > 90 % yaw) are met on all three
    sensors.
  - The stronger test (e) confirms fusion heading drift for sensor_1 and sensor_3.
  - It cannot decide for sensor_2, whose drift is small (2.9° in 92 min).

## Step 2: heading-drift model (flag, default OFF)

**Implementation.**
- `build_joint_bank.py --dedrift-yaw` removes the measured yaw from every sample: the yaw is
  measured per cycle as above and interpolated in time, and the sample is turned back about the
  world vertical. It also stores a linear yaw(t) model fitted on that bank's own data.
- With such a bank, the engine applies q_out = Rz(yaw(t)) · q. Accel and mag body are not changed.
- A normal bank is unaffected. Production output was checked byte-identical, and a unit test
  covers the yaw measurement.

The yaw slope fitted from the first 10 min alone differs from the 95-min slope:

| | sensor_1 | sensor_2 | sensor_3 |
|---|---|---|---|
| 10-min bank | +16.8°/h | +4.1°/h | **+6.6°/h** (wrong sign) |
| 95-min bank | +22.2°/h | +1.8°/h | −4.3°/h |

### Test 1: 10-min bank, 60 min output vs real 60 min (5 seeds; `test1_10min_bank.log`)

| | mag_world s1 / s2 / s3 (pass band 7.62–8.36 / 3.46–3.64 / 3.80–3.92°) | C2ST s1 / s2 / s3 | physics gate |
|---|---|---|---|
| 95-min bank (production, for reference) | 7.95–7.98 / 3.59–3.63 / 3.85–3.89 | 0.66–0.71 / 0.64–0.71 / 0.68–0.71 | PASS 5/5 |
| A: 10-min bank, no model | **7.00–7.04** / 3.62–3.64 / 3.89–3.93 | 0.88–0.90 / 0.87 / 0.89–0.91 | FAIL 5/5 |
| B: 10-min bank, de-drift + model | **7.46–7.49** / 3.62–3.65 / **3.94–3.98** | 0.89 / 0.85–0.87 / 0.88–0.89 | FAIL 5/5 |

C2ST by feature group (seed 42). C (diagnosis only) is the 10-min de-drifted bank with the 95-min
slope, to separate slope error from bank size:

| sensor | variant | quat | accel | angular velocity | gravity | mag |
|---|---|---|---|---|---|---|
| sensor_1 | 95-min production | 0.47 | 0.67 | 0.66 | 0.53 | 0.52 |
| sensor_1 | A: 10 min, no model | 0.85 | 0.79 | 0.74 | 0.85 | 0.74 |
| sensor_1 | B: 10 min + model | **0.51** | 0.79 | 0.71 | 0.85 | 0.74 |
| sensor_1 | C: 10 min + 95-min slope | 0.52 | 0.79 | 0.72 | 0.86 | 0.74 |
| sensor_2 | 95-min production | 0.48 | 0.65 | 0.59 | 0.56 | 0.67 |
| sensor_2 | A | 0.85 | 0.80 | 0.58 | 0.83 | 0.77 |
| sensor_2 | B | 0.72 | 0.80 | 0.59 | 0.82 | 0.77 |
| sensor_2 | C | 0.62 | 0.80 | 0.58 | 0.81 | 0.77 |
| sensor_3 | 95-min production | 0.50 | 0.67 | 0.54 | 0.54 | 0.71 |
| sensor_3 | A | 0.86 | 0.84 | 0.58 | 0.87 | 0.72 |
| sensor_3 | B | 0.82 | 0.84 | 0.59 | 0.86 | 0.72 |
| sensor_3 | C | 0.59 | 0.84 | 0.60 | 0.86 | 0.72 |

- **The heading model works on what it models.**
  - The quaternion group returns to production level for sensor_1 (0.51) and for sensor_3 with the
    right slope (0.59).
  - With the slope estimated from 10 min, sensor_2 and sensor_3 stay higher.
- **What the model cannot reach.**
  - Gravity (from the quaternion) is unaffected by yaw, yet it is 0.81–0.87 with any 10-min bank,
    against 0.53–0.56 with the 95-min bank. Accel (0.79–0.84) and mag (0.72–0.77) behave the same.
  - So the real 60 min also hold slow sub-degree tilt, accel and mag variation that 10 min of input
    does not contain. Step 1 measured that tilt drift at 0.2–0.7°, which is small but separable.
- **mag_world, sensor_1:** the model raises it 7.02 → 7.47° but stays below 7.62°. The 10-min slope
  is too low (16.8 vs 22.2°/h).
- **mag_world, sensor_3:** it now fails (3.94–3.98°) because the 10-min slope has the wrong sign.

### Test 2: 95-min de-drifted bank, 3 h (seed 42; `test2_3h_dedrift.log/.json`)

| hour | physics gate | C2ST s1 / s2 / s3 | without model (production) |
|---|---|---|---|
| 1 (0–60 min) | PASS | 0.678 / 0.632 / 0.703 | 0.668 / 0.674 / 0.702 |
| 2 (60–120, crosses end of recording) | PASS | 0.650 / 0.736 / 0.684 | 0.620 / 0.702 / 0.589 |
| 3 (120–180, all past the recording) | PASS | **0.995 / 0.998 / 0.928** | 0.822 / 0.837 / 0.830 |

Hour 3 by feature group (real comparison window = last 60 min of the recording):

| sensor | variant | quat | accel | angular velocity | gravity | mag |
|---|---|---|---|---|---|---|
| sensor_1 | no model | 0.80 | 0.78 | 0.64 | 0.74 | 0.59 |
| sensor_1 | yaw model | **0.99** | 0.71 | 0.62 | **0.59** | 0.61 |
| sensor_2 | no model | 0.81 | 0.76 | 0.57 | 0.64 | 0.75 |
| sensor_2 | yaw model | **1.00** | 0.67 | 0.54 | 0.58 | 0.71 |
| sensor_3 | no model | 0.81 | 0.76 | 0.53 | 0.64 | 0.62 |
| sensor_3 | yaw model | **0.93** | 0.71 | 0.53 | 0.59 | 0.64 |

- **The model improves accel, gravity and mag in hour 3.** With the drift removed, all 120 cycles
  are pose-compatible past the recording: 75 distinct templates instead of 25, and splice
  full-pose max 1.18° instead of 2.97°.
- **The jump comes only from the quaternion group.** The model keeps turning the heading, e.g.
  sensor_1 at +42..+64° in hour 3, while the real comparison window covers +11..+33°.
- **This C2ST cannot validate an extrapolation.** There is no real data after 95 min, and any
  continued drift moves away from the last real window. Without the model, the heading stays
  frozen near the end-of-recording value, which is inside that window. That is why it scores
  lower; it does not mean it is more realistic.

## Status
- Code: `rest_yaw_series()` and `build_bank(dedrift_yaw=...)` in `core/joint_template.py`; the
  `--dedrift-yaw` flag in `build_joint_bank.py`; engine option `yaw_drift` (automatic with a
  de-drifted bank).
- **Default OFF.** The production bank and configs are unchanged.
- Not adopted for production. Decision for the reviewer: keep the option (useful past the
  recording for accel, gravity and mag diversity) or remove it. The duration limitation
  "real input ≥ output duration" stays.
