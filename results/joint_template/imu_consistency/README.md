# Cross-column IMU consistency checks (quat ↔ accel while moving, quat ↔ mag)

**TL;DR**
- **Mag ↔ orientation passes and is now a blocking gate check.**
  - The world-frame mag direction is as steady in synthetic as in real: within −0.6 to +2.4 % of
    real on 5 seeds and on 10 held-out seeds.
  - The old generator fails it clearly: +88 % to +584 %.
- **Gravity consistency while moving fails on part of the metrics and is reported only**, as
  agreed for a failing check.
  - Synthetic differs from real by 0.01–0.1° (+0.8 to +5 %), against data-derived tolerances
    of ±0.6–5 %.
  - The cause is the donor accel residual: replaying the raw accel of the same cycle matches real
    exactly (sensor_1 p95 8.273 vs 8.287°, sensor_2 median 1.227 vs 1.226°).
  - The old generator is 2.5–35× off.
- Sensor → arm-link mapping: **[USER TO VERIFY]**.

Code: `imu_consistency.py`. Thresholds come from `derive_gate_thresholds.py` (section
`imu_consistency` in `configs/robot_arm/gate_thresholds.json`). The checks live in
`physics_gate.py` (`grav_moving_med`, `grav_moving_p95`, `mag_world`).

## Definitions
- **Moving** = orientation speed (rolling median over 10 samples) ≥ 3 °/s. This is the same rate
  used by the C2ST code.
- **Gravity error while moving**: the angle between R^T·[0,0,1] (q body→world, the convention of
  the existing at-rest gravity check) and accel/|accel|. It is not 0 in real data, because the
  arm's linear acceleration adds to gravity. Reported as median and p95.
- **Mag world-frame spread while moving**: the RMS angle of R·(m − b) from its mean direction.
  - b (hard-iron offset) is estimated once from the real recording by linear least squares on
    R_i·b + m = R_i·M_i, i.e. the offset that makes the real world-frame field most constant.
    The same b is then subtracted from real, synthetic and the old generator.
  - A sphere fit was tried first and rejected. The arm sweeps only a narrow range of
    orientations, so the fit is ill-posed: radius 13.7 for sensor_2, and the real spread rose
    from 6° to 79°.
  - b = (−28.1, −23.3, 121.6) / (−88.0, −22.8, 37.1) / (6.5, −22.2, 22.2).
  - sensor_2 barely rotates, so part of its b is weakly determined. The same b is applied
    everywhere, so the comparison stays like for like.
- **Reference** = real first 60 min, the span a 60-min synthetic file replays and the C2ST span.
  - This was chosen after a first pass against the full 95-min recording.
  - The mag spread grows with the span, because the world-frame direction drifts slowly: for
    sensor_1 the full recording gives 9.24°, while its two halves give 7.65 and 8.17°.
  - So a 60-min file must be compared with 60 min of real. Against the full recording,
    sensor_1's mag check would fail (−14 %) for that reason alone.
- **Tolerance** (same pattern as omega) = |real half A − real half B| / ref + 2 sd over seeds
  42–46 / ref, where A and B are the contiguous 30-min halves of the reference span.

## Results

Synthetic: 5 derivation seeds (42–46) and 10 held-out seeds (100–109, not used for any
threshold). The old generator is the deck file.

| sensor | metric | real (0–60 min) | tolerance | synthetic, 5 seeds | pass | held-out, 10 seeds | pass | old generator |
|---|---|---|---|---|---|---|---|---|
| sensor_1 | gravity moving, median | 3.718° | ±2.3 % | 3.723–3.789 | 5/5 | 3.715–3.794 | 10/10 | 36.31 (+877 %) |
| sensor_1 | gravity moving, p95 | 8.287° | ±0.6 % | 8.362–8.404 | **0/5** | 8.348–8.394 | **0/10** | 88.46 (+967 %) |
| sensor_1 | **mag world spread** | 7.991° | ±4.6 % | 7.946–7.983 | 5/5 | 7.924–7.986 | 10/10 | 54.64 (+584 %) |
| sensor_2 | gravity moving, median | 1.226° | ±2.7 % | 1.269–1.301 | **0/5** | 1.275–1.305 | **0/10** | 4.40 (+259 %) |
| sensor_2 | gravity moving, p95 | 3.790° | ±4.0 % | 3.681–3.717 | 5/5 | 3.653–3.730 | 10/10 | 9.39 (+148 %) |
| sensor_2 | **mag world spread** | 3.545° | ±2.5 % | 3.593–3.630 | 5/5 | 3.601–3.620 | 10/10 | 6.67 (+88 %) |
| sensor_3 | gravity moving, median | 0.760° | ±0.8 % | 0.762–0.769 | 4/5 | 0.751–0.773 | **4/10** | 26.57 (+3395 %) |
| sensor_3 | gravity moving, p95 | 2.999° | ±5.1 % | 2.989–3.036 | 5/5 | 2.981–3.064 | 10/10 | 47.42 (+1481 %) |
| sensor_3 | **mag world spread** | 3.859° | ±1.6 % | 3.845–3.891 | 5/5 | 3.850–3.903 | 10/10 | 26.78 (+594 %) |

3-hour run (seed 42): mag passes in all three hours on every sensor (7.82–7.99° / 3.60–3.62° /
3.85–3.89°). The physics gate passes in every hour. The gravity-while-moving results follow the
same pattern as above.

Why gravity-while-moving fails (5 seeds, real first 60 min):

| sensor | real median / p95 | production (donor accel residual) | raw accel replay (round-2 ablation B, diagnosis only) |
|---|---|---|---|
| sensor_1 | 3.718 / 8.287 | 3.746 / 8.382 | 3.720 / 8.273 |
| sensor_2 | 1.226 / 3.790 | 1.288 / 3.695 | 1.227 / 3.799 |
| sensor_3 | 0.760 / 2.999 | 0.765 / 3.018 | 0.758 / 3.008 |

- The orientation is identical in both variants; only the accel noise texture differs. So this is
  the known accel/mag issue (see round 3) and not a new defect.
- Raw replay is not a production option, because it breaks the copy gate (13–68 %).
- No fix was attempted (no new accel/mag work).

## Status in the gate
- `mag_world`: **blocking**.
- `grav_moving_med`, `grav_moving_p95`: **reported** (`INFO-PASS` / `INFO-FAIL`), not blocking.
  - Blocking status is stored per metric in `gate_thresholds.json` (`"blocking"`) and set in
    `derive_gate_thresholds.py` (`BLOCKING_IMU`).
  - Making it blocking is a one-line change, but it would fail every seed today.
- Physics gate result with the new checks: PASS on seeds 42–46, on 100–109 and on every hour of
  the 3-hour run (`../gate/`).
