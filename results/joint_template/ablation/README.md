# Arm joint-template engine: one ablation per cause (review round 2)

> Round-2 record. Thresholds quoted here are the ones in force at that time. Round 3 changed them:
> the omega tolerance was re-derived, the C2ST threshold is now a permutation null and C2ST no longer
> blocks, and dropped ticks were added. See `../round3/README.md`.

**TL;DR**
- **Timestamps (Step 1): confirmed as a cause.**
  - With perfect timestamps (ablation A), omega p99 drops 12 / 4 / 1 % and the angular-velocity
    C2ST rises to 0.90 / 0.79 / 0.72.
  - The new empirical timestamp model brings the angular-velocity C2ST to 0.65 / 0.58 / 0.53
    (it was 0.68 / 0.63 / 0.70 with Gaussian jitter).
  - Omega p99 is now centred on real, but its seed spread is larger, so it fails the current
    tolerance in 2 of 5 seeds.
- **Accel/mag (Step 2): the donor residual is the cause, but neither suggested alternative fixes it.**
  - Raw replay (ablation B) makes accel and mag indistinguishable (0.50–0.54), but copy rises to
    35 % (sensor_1) and 10 % (sensor_2).
  - A most-similar donor, a phase-aligned (DTW) donor, and a quantisation-consistent ("lattice")
    donor all leave accel at about 0.63–0.67.
  - The mechanism measured instead: within one cycle, the smooth part and the residual are
    negatively correlated step to step. Swapping in a donor residual removes that, which raises
    the accel step variance by 2–22 %.
- **C2ST null (Step 3).**
  - The permutation null is centred on 0.50 (sd 0.025), which gives thresholds of
    0.585 / 0.594 / 0.583. The old thresholds were 0.621 / 0.577 / 0.523.
  - Synthetic (0.69 / 0.68 / 0.69) fails both.
- No threshold was changed. Sensor → arm-link mapping: **[USER TO VERIFY]**.

All numbers are from 5 seeds (42–46) × 60 min, compared with the first 60 min of the real
recording. Thresholds come from `configs/robot_arm/gate_thresholds.json` (unchanged). Tool:
`ablation_arm.py` (+ `ablation_table.py`); raw results are in `ablation_*.json` / `*.log` here.

## Step 1: timestamp model

### What the real logged timestamps look like (full recording)
- The XDK internal clock is regular, with a period of **100.003 ms** for all three sensors.
  This was measured over calm-to-calm spans of 200 samples and is stable across six
  15-minute blocks.
- The logged timestamp is that clock plus a **delivery delay**. Two patterns produce it:
  - a single late sample followed by a catch-up (`… 105 94 107 165 32 95 …` ms);
  - **backlogs**, where several samples are held for about 400 ms and then delivered within a
    few ms (`… 95 402 5 4 4 512 4 4 1 1 …`).
- Backlogs are **shared between sensors** (same gateway). A late event in one sensor has a late
  event in another within 0.3 s in:
  - s1–s3: 92 % (14 % expected by chance);
  - s1–s2: 30 % (7 % by chance);
  - s2–s3: 41 % (7 % by chance).
- About 0.5 % of steps are **dropped ticks** (dt ≈ 200 ms with no catch-up).
- Corrections to the earlier description:
  - lag-1 autocorrelation of dt over the full recording is −0.1 to −0.2. The −0.4 to −0.5 I
    reported came from the first 100 rows only.
  - The old `internal_clock()` split segments at every late sample (> 1.5 × nominal), so its
    "offsets" were contaminated. Its segments had a median length of 18 samples. That is why the
    earlier i.i.d. residual resampling overshot.

### New model (`log_jitter: "empirical"`, now the default with bank v4)
- Whole real blocks of offsets are replayed (600 ticks ≈ 60 s).
- Each block is taken from the **same real time span for all sensors**, so the shared backlogs
  stay shared.
- A block starts at a calm sample, meaning a step within 4 ms of P on both sides.
- A block ends at the first tick L ≥ 600 where every sensor is calm again and back within 4 ms
  of its start level. The step between blocks is therefore itself a calm step.
- Within a block, ticks are assigned backwards from that end point, because the last sample of a
  backlog is the punctual one.
- Missing real ticks get interpolated offsets. Which rows exist is still the generator's
  timestamp model (see open item 1).
- The model is non-parametric: no distribution is fitted.
- Bank v4 = bank v3 + the real logged time axis per sensor. All v3 arrays are bit-identical.
  `log_jitter: "gaussian"` on the v4 bank reproduces the previous output byte for byte
  (checked on all three sensors, seed 42).

### Results

Omega p99 relative to real (tolerance from gate_thresholds.json):

| sensor | tol | Gaussian (before) | A: no jitter | empirical |
|---|---|---|---|---|
| sensor_1 | ±3.6 % | −2.2 % (−2.5..−2.1), pass 5/5 | **−12.4 %**, pass 0/5 | +2.1 % (−0.5..+3.8), pass 4/5 |
| sensor_2 | ±1.4 % | −1.6 % (−2.1..−1.1), pass 1/5 | **−4.3 %**, pass 0/5 | +0.9 % (+0.2..+1.9), pass 3/5 |
| sensor_3 | ±0.9 % | −0.5 % (−0.7..−0.2), pass 5/5 | **−1.3 %**, pass 0/5 | +0.2 % (−0.2..+0.6), pass 5/5 |

C2ST, mean ± sd over 5 seeds:

| sensor | feature group | Gaussian | A: no jitter | empirical |
|---|---|---|---|---|
| sensor_1 | all (threshold 0.621) | 0.694 ± 0.022 | 0.884 ± 0.014 | 0.691 ± 0.021 |
| sensor_1 | angular velocity | 0.676 | **0.897** | **0.654** |
| sensor_2 | all (threshold 0.577) | 0.695 ± 0.021 | 0.803 ± 0.016 | 0.680 ± 0.023 |
| sensor_2 | angular velocity | 0.625 | **0.789** | **0.577** |
| sensor_3 | all (threshold 0.523) | 0.766 ± 0.020 | 0.772 ± 0.024 | 0.694 ± 0.022 |
| sensor_3 | angular velocity | 0.703 | **0.724** | **0.530** |

Quaternion, gravity, accel and mag groups are unchanged by the timing model (within ±0.02).
Full tables, including dt percentiles, kurtosis and autocorrelation, are in `step1_tables.md`.

Logged dt (ms), sensor_1, compared with the real stream after the same block processing (dropped
ticks interpolated):

| | p1 | p25 | p50 | p75 | p99 | lag-1 ac | % < 40 | % > 150 |
|---|---|---|---|---|---|---|---|---|
| real | 66.4 | 97.4 | 100.1 | 102.9 | 128.6 | −0.27 | 0.53 | 0.43 |
| Gaussian (before) | 84 | 95 | 100 | 105 | 116 | −0.49 | 0.00 | 0.02 |
| empirical (seeds 42/43) | 62.9 / 58.5 | 97.3 / 97.4 | 100.1 | 102.9 | 130.4 / 134.4 | −0.30 / −0.31 | 0.61 / 0.66 | 0.50 / 0.61 |

Full physics gate on the empirical model, 5 seeds (`gate_5seeds_empirical.log/.json`):
- **Passes on every seed:** validity, gravity (1.19–1.33° / 0.33° / 0.34°), jumps, gap jumps,
  copy (0 %), 7b (92.2–92.9 %), 7c (0 ms).
- **Fails:**
  - C2ST, all sensors, every seed;
  - omega p99 on seed 43 (sensor_1 +3.8 % vs ±3.6 %, sensor_2 +1.6 % vs ±1.4 %) and
    seed 46 (sensor_2 +1.9 %).
- About the omega tolerance:
  - Its seed term (2 sd) was derived with the Gaussian model, whose seed spread was 0.2–0.4 %.
  - With empirical jitter the spread is about 1.5 %, because the p99 now depends on which real
    backlogs were drawn.
  - The tolerance was **not** re-derived. Doing so would widen it, and that decision is the reviewer's.

3-hour run with empirical jitter, seed 42 (`long_duration_3h_empirical.log`,
`gate_3h_per_hour_empirical.json`):

| hour | omega p99 s1 / s2 / s3 (vs real) | C2ST s1 / s2 / s3 | 7b | 7c | result |
|---|---|---|---|---|---|
| 1 (0–60 min) | +2.8 / +0.3 / −0.1 % | 0.670 / 0.666 / 0.713 | 92.3 % | 0 ms | FAIL: C2ST ×3 |
| 2 (60–120, crosses end of recording) | +3.0 / +1.0 / +0.8 % | 0.632 / 0.712 / 0.586 | 91.8 % | 0 ms | FAIL: C2ST ×3 |
| 3 (120–180, all past the recording) | +0.7 / +0.2 / −0.1 % | 0.828 / 0.841 / 0.832 | 92.1 % | 0 ms | FAIL: C2ST ×3 |

## Step 2: accel/mag texture

Each variant changes only the accel/mag residual. The base is the Step 1 empirical model.

| sensor | feature | base (random donor) | **B: raw replay** | most-similar donor | DTW phase-aligned donor | lattice donor |
|---|---|---|---|---|---|---|
| sensor_1 | all | 0.691 | **0.624** | 0.690 | 0.679 | 0.697 |
| sensor_1 | accel | 0.661 | **0.505** | 0.667 | 0.647 | 0.658 |
| sensor_1 | mag | 0.545 | 0.532 | 0.562 | 0.551 | 0.586 |
| sensor_2 | all | 0.680 | **0.551** | 0.678 | 0.691 | 0.712 |
| sensor_2 | accel | 0.641 | **0.498** | 0.648 | 0.638 | 0.637 |
| sensor_2 | mag | 0.662 | **0.476** | 0.644 | 0.680 | 0.695 |
| sensor_3 | all | 0.694 | **0.514** | 0.675 | 0.674 | 0.726 |
| sensor_3 | accel | 0.649 | **0.540** | 0.631 | 0.628 | 0.653 |
| sensor_3 | mag | 0.682 | **0.532** | 0.680 | 0.672 | 0.729 |
| **copy sensor_1** (gate ≤ 5 %) | | 0.0 % | **35.3 %** (13–68 % per seed) | 0.6 % | 0.0 % | 0.0 % |
| **copy sensor_2** | | 0.0 % | **9.5 %** (5–17 %) | 0.0 % | 0.0 % | 0.0 % |

- **B confirms the donor residual is the cause.** It is diagnosis only: it breaks the copy gate.
  - With raw replay, overall C2ST passes the old threshold for sensor_2 (0.551 ≤ 0.577) and
    sensor_3 (0.514 ≤ 0.523).
  - sensor_1 is still above it (0.624 vs 0.621) because of its angular-velocity group (0.654).
- **Most-similar donor and DTW phase alignment:** no effect beyond seed noise. The donor's motion
  events do sit up to 0.7 s off under linear phase mapping (DTW lag p5 −7 samples), but aligning
  them does not help.
- **Lattice:** tested because adding a float residual and rounding again would double the
  quantisation error. It is worse for mag. The hypothesis is rejected.
- **Mechanism measured instead** (`residual_step_covariance.py` / `.log`, 40 cycles per sensor): inside one real cycle, the
  step of the smooth part (savgol 7,2) and the step of the residual are negatively correlated
  (smoother leakage). A donor residual has no such correlation with the template's smooth part,
  so step variance rises:

  | | sensor_1 | sensor_2 | sensor_3 |
  |---|---|---|---|
  | accel step variance, donor / raw | 1.22 | 1.02 | 1.02 |
  | mag step variance, donor / raw | 1.03 | 1.03 | 1.05 |

  This matches the per-window statistics: the donor variant has 4–10 % larger mean |step| and more
  distinct values per window, while B equals real.
  Not fixed yet. Possible next steps, for the reviewer to choose:
  - a decomposition with no leakage between the smooth and residual parts;
  - or a covariance correction.

## Step 3: C2ST null by permutation

Same windows and same block folds as the gate. The labels real/synthetic are shuffled across the
pooled windows 100 times; the pool is real 0–60 min plus empirical seed 42.
Permutation threshold = p95(null) + 2 · sd over seeds.

| sensor | null mean ± sd | null p95 | perm threshold | old threshold (real-vs-real + margin) | synthetic (empirical) | perm | old |
|---|---|---|---|---|---|---|---|
| sensor_1 | 0.503 ± 0.024 | 0.544 | **0.585** | 0.621 (0.444 + 0.177) | 0.691 | FAIL | FAIL |
| sensor_2 | 0.506 ± 0.026 | 0.548 | **0.594** | 0.577 (0.419 + 0.157) | 0.680 | FAIL | FAIL |
| sensor_3 | 0.503 ± 0.024 | 0.540 | **0.583** | 0.523 (0.397 + 0.126) | 0.694 | FAIL | FAIL |

- The permutation null is centred on 0.50, as it should be.
- The real-vs-real baseline sits below 0.5 (0.40–0.44) because real windows carry slow drift and
  structure in time. A label permutation destroys that structure, so it does not reproduce it.
- The permutation threshold is stricter than the old one for sensor_1 and looser for sensors 2 and 3.
- Raw replay (B) would pass the permutation threshold on sensors 2 and 3 and fail on sensor_1.

## Open items
1. **Dropped ticks:** real loses about 0.5 % of ticks; the generator's timestamp model loses
   0.02 %. This is not part of the jitter model and has not been changed.
2. **Omega seed spread:** the empirical jitter makes p99 vary about 1.5 % between seeds. The
   tolerance's seed term was derived with the old model.
3. **Accel/mag:** the smooth–residual covariance (see Step 2).
4. **C2ST threshold:** old method or permutation method — reviewer's decision.
