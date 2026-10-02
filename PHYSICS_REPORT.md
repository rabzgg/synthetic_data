# Is the synthetic data physically real? 
This is measurement only. Nothing in the generator was changed for this report. Every synthetic number sits next to the real number it's compared against. The test bed is the robot arm, joints 1, 2, and 3.

> **Update:** the arm's physics gaps measured below are fixed for arm_robot by the joint-template engine (`motion.joint_template`, default OFF). Results, gate, limitations and the identity test are in the last section, "Joint template".

## The basic idea
 check one thing that must always be true in the real world: gravity always points down.
The sensor has two ways of knowing "down." One is the accelerometer, which feels gravity directly. The other is the orientation reading, which stores which way the sensor is tilted. If you know the tilt, you can calculate which way "down" should be. In a real recording, those two ansrs must agree.
So the test is: calculate "down" from the tilt reading, calculate "down" from the accelerometer, and measure the gap beten them in degrees. Small gap = the two readings agree = physically sensible. Big gap = they disagree = something that can't really happen.

## Step 0 — checking our own assumptions first
Before measuring anything, confirmed a few basics:

* The orientation columns are quaternions (a 4-number way of storing tilt), not simple angles.
* The arm data only stores 3 of the 4 numbers. The 4th is rebuilt using math. When the rebuilt number would be invalid, mark it as invalid rather than quietly hiding it.
* Accelerometer values are in units of "g" (1g = normal gravity at rest).
* had to figure out which rotation convention the sensor uses (there are 4 possible ways to define it). tested all 4 on data where the arm is actually moving, and one of them won by a landslide (1.1° error vs 32°, 148°, and 179° for the wrong ones). So know the convention is right, not guessed.

## Check 1 — is the tilt number even valid?
There's a hard math rule for these tilt numbers: three of their parts, squared and added together, can never be more than 1. If they are, the number doesn't describe a real tilt at all — like a date that says "day 35."
Result: Joint 1's synthetic data breaks this rule 4.86% of the time, reaching as high as 1.70. The real data almost never breaks it (0.14%, and even that is just tiny rounding noise). Joints 2 and 3 are fine.

## Check 2 — do tilt and accelerometer agree on "down"? (the core test)
This is the main test described above.
Result:

| Joint | Real data | Synthetic data |
|---|---|---|
| 1 | 1.1° | 34.6° |
| 2 | 0.3° | 4.1° |
| 3 | 0.3° | 27.9° |

Real data agrees with itself to about 1 degree. Synthetic data disagrees by 30-plus degrees on joints 1 and 3.
One honest caveat: the "quiet" samples tested this on aren't perfectly still — the arm never fully stops moving. So a small part of that gap could be normal movement, not pure inconsistency. But checked the accelerometer readings in this same window and they're close to 1g on both real and synthetic data, meaning things are calm enough that the comparison is fair. And since measured the real data on the exact same kind of "quiet" window and it stayed near 1°, the difference is real, not a measurement artifact.
 also double-checked two possible objections:

* Maybe the 34.6° number is just being dragged up by the invalid tilt values from Check 1? removed those samples and re-measured: 34.6° barely moved. So the problem is everywhere, not just in the broken samples.
* Maybe joint 3's 27.9° is measured on too few samples to trust? loosened the filter step by step, from 10% of samples up to 49%. The error stayed the same the whole time. It's a real number, not a fluke of a small sample.

Interesting twist: the near-still datasets (the aquarium sensor, and joint 2, which barely moves) score ll on this test. But that's not because the generator understood the physics — it's because there's almost no motion to get wrong in the first place. This test only catches problems when something is actually moving.

## Check 3 — does the magnetic field stay steady?
Earth's magnetic field doesn't move. So if you take the sensor's magnetic reading and "un-rotate" it using the tilt, it should point in roughly the same direction the whole time.
Result: even the real data isn't perfectly clean here (magnetic sensors pick up interference from nearby metal). But where the arm is moving, the synthetic reading is noticeably more scrambled than real. And on joint 1, the synthetic magnetic strength is off by 2.4 times (65.3 vs 153.9) — a separate scaling mistake, on top of the direction problem.

## Check 4 — how fast is the arm spinning? (our strongest, clearest result)
This one needs no explanation of tilt math or sensor fusion to understand. A robot joint has a hard, physical top speed. It cannot spin faster than its motor allows, period.
Result:

| Joint | Real (99th percentile) | Synthetic (99th percentile) |
|---|---|---|
| 1 | 45°/s | 722°/s |
| 2 | 16°/s | 13°/s |
| 3 | 43°/s | 39°/s |

Joint 1's synthetic data is spinning 16 times faster than the real recording ever does. About 1 in every 9 synthetic samples on joint 1 moves faster than the fastest 1% of real motion.
For reference: this arm is a Franka Emika Panda, whose top per-joint speed is documented at 150–180°/s. 722°/s is roughly 5 times above even that ceiling. (One caveat: the sensor is bolted to the arm's outer link, not inside a single joint, so this comparison is suggestive rather than an exact hardware-spec violation — but the real-vs-synthetic gap of 16x stands on its own regardless.)

## Check 5 — do paired columns move together the way they should?
Some column pairs should move in a locked, opposite, or matching way — like two ends of a seesaw. measured how strongly they're linked in real data versus synthetic data.
Result: every single pairing checked collapses toward zero in the synthetic data. For example, on joint 1, two tilt columns that move almost perfectly opposite in real data (−0.991, like a seesaw) show basically no relationship at all in synthetic data (+0.018). Same story for magnetic and accelerometer pairs, and for every version of the aquarium data tested. The seesaw is broken everywhere looked.

## Check 6 — two loose threads chased down
Where does the −0.40 ceiling on joint 1 come from?

* suspected a hard-coded limit in the settings. It's not that. It turns out the generator learns a single "template" of the motion from the real recording, and that template is automatically stretched so its lost point sits at exactly −0.5. When that template gets scaled back up, it lands at about −0.40 — ll short of the real data's swing down to −0.75. So the ceiling is a side effect of how the template gets built, not an intentional limit.

Why does joint 1's cycle look twice as fast as it should?

* The real motion turns out to happen in pairs — two quick movements close together, then a long pause, then two more. The tool that counts "how long is one cycle" was counting each half of the pair as its own full cycle, which makes the measured rhythm look twice as fast as it really is. This is a counting-tool issue, not proof that the generator's timing itself is wrong.

## The short version

| Joint | Is the tilt number valid? | Do tilt and accelerometer agree? | Is the spin speed realistic? | Do paired columns move together? |
|---|---|---|---|---|
| 1 | No — 4.9% invalid | No — 35° off vs 1° | No — 16x too fast | No — collapsed to ~0 |
| 2 | Yes | Close — 4° off vs 0.3° | Yes | Barely tested (barely moves) |
| 3 | Yes | No — 28° off vs 0.3° | Yes | No — collapsed to ~0 |

The one-sentence explanation for all of it: every column (tilt, accelerometer, magnetic field) is currently learned and generated on its own, completely separately from the others. Nothing in the generator knows they're supposed to describe the same physical object moving through space. That's why a column can look correct all by itself and still be physically wrong once you check it against its neighbors.

## What fixed already: Phase 1 — making the tilt numbers valid
Turned on a fix (behind an on/off switch, off by default so nothing else changes) that rescales any tilt reading that broke the math rule from Check 1.
Result: exactly what expected, nothing more and nothing less.

* The invalid-number problem is gone: 5.1% invalid → 0%.
* The "does tilt agree with the accelerometer" problem is unchanged (34.9° before, 35.9° after). predicted this beforehand — making the tilt number mathematically valid doesn't connect it to the accelerometer column, since those two are still generated completely separately. Fixing that connection is a separate, bigger fix, planned next.
* Nothing else got worse. Spin speed, distribution shape, everything else stayed the same or improved slightly.

## Fixes 've identified but haven't built yet
* Connect accelerometer to tilt: calculate the gravity part of the accelerometer reading directly from the tilt number, instead of generating it separately. This is the fix that should close the 34.6°/27.9° gap. **RETIRED for arm_robot:** superseded by the joint-template engine, which closes the gap (see "Joint template").
* Make paired columns move together: add correlated noise (Cholesky) within each sensor's group of columns, instead of generating each one in isolation. **RETIRED for arm_robot:** the joint template takes whole real cycles, so the columns already move together.
* MuJoCo physics simulation (`MUJOCO_FEASIBILITY.md`): **parked**, not used in production.
* Widen the joint-1 ceiling: fix the template-scaling issue so the motion can reach its real full range.
* Fix the joint-1 magnetic scale error: investigate the 2.4x magnitude mismatch separately.

---

## Joint template (`motion.joint_template`, default OFF) — arm_robot

**TL;DR.**
- The arm's physics failures came from generating every motion column on its own
  (own template, own period). The joint-template engine replays whole real arm
  cycles instead: orientation, accel and mag of all three sensors come from the same
  moment of the recording, on one shared cycle schedule.
- **Claim:** physical consistency is inherited from the real recording; whole
  orientation–accel–mag cycles are taken together and the three sensors share the
  same schedule.
- **The physics gate passes on all 5 seeds, on every hour of a 3-hour run, and on 10
  held-out seeds (100–109) that were not used to derive any threshold.**
- Recommended duration: ≤ the recording length (94.9 min). See Limitations.
- The classifier two-sample test (C2ST) is a **reported metric, not a blocking check**
  (user decision). It is above its threshold on all sensors (0.64–0.71): a classifier can
  still tell synthetic from real, mainly by accel and mag.
- Review rounds:
  - Round 2 (`results/joint_template/ablation/README.md`): one ablation per cause.
    Timestamps are a confirmed cause, fixed with real offset blocks.
  - Round 3 (`results/joint_template/round3/README.md`):
    - the leak-free accel/mag split was tried once, failed for C2ST and was not adopted;
    - the omega tolerance was re-derived;
    - the C2ST threshold now comes from a permutation null;
    - dropped ticks now come from real blocks.
- The sensor → arm-link mapping is **[USER TO VERIFY]**. Nothing below says which link
  a sensor is on.

### Root cause (diagnosis)
- The `quaternion_flip` mode of `periodic_motion` is not the cause: the arm uses
  `cycle_template`, and forcing the flag off gives byte-identical output.
- The real XDK flips hemisphere (q → −q, x and z together) 304 times at |w| ≈ 0.
  Those flips are baked into the per-column templates. Laid out with independent
  periods (x 27.9 s, z 27.5 s, y 37.0 s; true cycle 37.0 s), the x and z flips
  coincide only 3.7 % of the time, and each half-flip reads as a huge rotation.
- Removing those steps drops omega p99 722 → ~191°/s. The rest, and the 36°
  gravity error, is the same independence: the pair (x, z) comes from different
  cycles, so the implied tilt is false.
- Unwrapping alone (variant A) made it worse (omega 983°/s, gravity 54°).

### Noise and timing model, measured on the real XDK
| property | real | used |
|---|---|---|
| quaternion repeats exactly (freeze) | 93–95 % of samples below 0.2°/s, ~0 % above | the real per-sample freeze pattern of the replayed cycle |
| quaternion noise | whatever the recording has | recorded quaternion as is (no smoothing, nothing added) |
| sample timing | regular internal clock (100.003 ms); only the logged timestamp is offset (step angle vs dt corr ≈ 0): heavy-tailed delivery delay — late sample then catch-up, backlogs of several samples delivered within a few ms — shared between sensors (s1–s3 92 % vs 14 % chance) | regular clock, timestamp = clock + real offset blocks (~60 s) from the same real time span for all sensors |
| dropped samples | 0.31–0.68 % of ticks (block measure), plus one 74 s outage in all sensors | the ticks dropped in the same real offset blocks (0.3–0.7 %); the outage is not reproduced |
| accel step while the whole arm is still | typically 1 LSB (0.001 g), std 0.004–0.009 g (clustered) | residual of another real cycle, same phase |
| accel noise while the arm moves | 2–5× larger (vibration) | (same) |
| resolution | quat 1e-4, accel 0.001 g, mag integer | same |

For accel noise:
- A stationary Gaussian per axis (the first attempt) dropped Check 7b to 61 %.
- An i.i.d. empirical bootstrap gave 62 %.
- Phase-aligned residual swap gives ~92 %.

### Physics gate (`physics_gate.py`; real in brackets)
Blocking checks:
- validity: 0 % of samples with s > 1 + 1e-3
- gravity: median quiet error < 2°
- omega p99: within a per-sensor data-derived tolerance, computed as real 60-min-window
  variation + 2 sd over seeds (`derive_gate_thresholds.py` → `configs/robot_arm/gate_thresholds.json`).

  | sensor | previous (seed term from Gaussian jitter) | **now (seed term from empirical jitter)** |
  |---|---|---|
  | sensor_1 | ±3.6 % (3.3 natural + 0.4 seeds) | **±7.0 %** (3.3 + 3.7) |
  | sensor_2 | ±1.4 % (0.6 + 0.8) | **±2.1 %** (0.6 + 1.5) |
  | sensor_3 | ±0.9 % (0.5 + 0.4) | **±1.2 %** (0.5 + 0.7) |

  - **Why it changed:** the previous seed term came from the Gaussian jitter model, which was
    replaced by real offset blocks. With real offset blocks, the p99 depends on which real
    backlogs a seed draws.
  - Both values are kept in `gate_thresholds.json` (`rel_tol`, `rel_tol_previous`, `change_reason`).
  - Caveat: the seed term comes from the same 5 seeds the gate is then run on.
- jumps: 0 one-sample non-flip quaternion jumps. Gap transitions must be ≤ real p99 + 25 %.
- Check 7b ≥ 85 %, Check 7c lag 0 ms
- copy: ≤ 5 % of windows with corr > 0.99 (sensor_1, sensor_2; sensor_3 is excluded
  because its real cycles are near-identical)

Reported, **not blocking** (user decision):
- C2ST per sensor, against a threshold of the 95th percentile of a label-permutation null
  (same windows, same block folds, 100 shuffles) + 2 sd over seeds: 0.583 / 0.606 / 0.566.
- The old threshold (real-vs-real baseline + margin: 0.621 / 0.577 / 0.523) was removed.

| seed | grav s1/s2/s3 (1.11/0.33/0.33°) | omega p99 s1/s2/s3 (44.9/16.4/43.1) | 7b (94.3) | 7c | physics gate | C2ST s1/s2/s3 (reported) |
|---|---|---|---|---|---|---|
| 42 | 1.26 / 0.33 / 0.34 | 46.3 / 16.5 / 43.0 | 92.2 | 0 ms | PASS | 0.68 / 0.67 / 0.71 |
| 43 | 1.28 / 0.33 / 0.34 | 46.7 / 16.7 / 43.3 | 92.2 | 0 ms | PASS | 0.71 / 0.69 / 0.69 |
| 44 | 1.33 / 0.33 / 0.35 | 45.3 / 16.5 / 43.2 | 92.1 | 0 ms | PASS | 0.71 / 0.71 / 0.70 |
| 45 | 1.31 / 0.33 / 0.34 | 44.8 / 16.4 / 43.0 | 92.5 | 0 ms | PASS | 0.66 / 0.68 / 0.68 |
| 46 | 1.20 / 0.33 / 0.34 | 46.6 / 16.7 / 43.3 | 92.8 | 0 ms | PASS | 0.69 / 0.64 / 0.68 |

Validity, jumps, gap jumps and copy are 0 in every seed and every hour.

Held-out check of the omega tolerance (seeds 100–109, never used to derive it; thresholds file
unchanged; `results/joint_template/gate/heldout_seeds_100_109.log`, `gate_heldout_seeds_100_109.json`):

| sensor | omega p99 vs real (10 seeds) | tolerance | largest deviation / tolerance | all blocking checks pass |
|---|---|---|---|---|
| sensor_1 | −1.7 .. +5.5 % (mean +1.4 %) | ±7.0 % | 0.78 | **10 / 10** |
| sensor_2 | −0.1 .. +1.4 % (mean +0.8 %) | ±2.1 % | 0.66 | **10 / 10** |
| sensor_3 | −0.5 .. +0.5 % (mean +0.1 %) | ±1.2 % | 0.43 | **10 / 10** |

- By the agreed rule (≥ 9/10 per sensor), the tolerance holds.
- On the same seeds: 7b is 91.8–92.7 %, 7c is 0 ms, and C2ST (reported) is 0.650–0.742.

Against `baseline_before.json` (deck, seed 42):
- sensor_1 gravity 36.2 → 1.26°; omega p99 722 → 46.3°/s.
- sensor_3 gravity 27.9 → 0.34°.

### Longer than the recording (3 h, seed 42; recording = 94.9 min)
| hour | grav s1 | omega p99 s1 / s2 / s3 | 7b | 7c | physics gate | C2ST s1/s2/s3 (reported) |
|---|---|---|---|---|---|---|
| 1 (0–60 min) | 1.30° | 46.3 / 16.5 / 43.0 | 92.2 % | 0 ms | PASS | 0.67 / 0.67 / 0.70 |
| 2 (60–120, crosses end of recording) | 1.31° | 46.3 / 16.6 / 43.4 | 91.9 % | 0 ms | PASS | 0.62 / 0.70 / 0.59 |
| 3 (120–180, all past the recording) | 1.35° | 45.3 / 16.4 / 43.0 | 92.0 % | 0 ms | PASS | 0.82 / 0.84 / 0.83 |

- Splices after the recording: tilt ≤ 0.19°, full pose ≤ 2.97°, no fallbacks.
- Only 25 of 120 cycles are pose-compatible with the end-of-recording pose, so the
  orientation stays near that pose.
- C2ST is highest in hour 3, the hour fully past the recording.

### Sensor identity (Level 1: can synthetic sensor_k be told apart from real sensor_k?)
Level 2 (which link a sensor is on) is **not** answered: the mapping is **[USER TO VERIFY]**.

C2ST setup:
- Classifier: random forest on 10 s windows of motion features only: quat, accel,
  mag, body angular velocity, gravity from the quaternion. temp, light, humidity,
  pressure, id and timestamp are excluded.
- Folds are contiguous blocks of 10 cycles. With cycle-interleaved folds, slow drift
  made the real-vs-real baseline collapse to 0.18, far below chance.

| sensor | permutation null (mean ± sd, p95) | threshold | synthetic (5 seeds) | old generator |
|---|---|---|---|---|
| sensor_1 | 0.502 ± 0.026, 0.541 | 0.583 | **0.692 ± 0.021** | 0.977 |
| sensor_2 | 0.505 ± 0.027, 0.549 | 0.606 | **0.680 ± 0.028** | 0.999 |
| sensor_3 | 0.504 ± 0.024, 0.540 | 0.566 | **0.688 ± 0.013** | 1.000 |

What C2ST shows:
- The test has power: the old generator is caught almost perfectly.
- Synthetic is above the threshold on all sensors. This is reported; it does not block.
- By feature group (5 seeds), quaternion and gravity are indistinguishable from real (0.50–0.55).
  - Angular velocity is close after the timestamp fix (0.65 / 0.58 / 0.53).
  - Accel (0.63–0.66) and, for sensors 2/3, mag (0.67–0.68) carry the difference.
- A real-vs-real split of the same 60 min scores 0.40–0.44, below chance (slow drift).
  The permutation null cannot reproduce that, so it centres on 0.50.

Fingerprint distances F1–F5, synthetic vs real next to real half A vs half B:
- Synthetic is mostly within about 1–5× of the split-half distance, for example F3 0.07 vs
  0.13 for sensor_1.
- Exception: F4 (angular speed distribution) for sensor_1 is 0.047 vs 0.006 (8×; it was 0.018
  with Gaussian jitter). This reflects the +2 % omega p99 offset of sensor_1.
- The old generator is 100–1000× away.
- The earlier "sensor recognition" classifier was removed: the old generator passed it too.

F6, counter-rotation about the vertical (quaternions slerped to 10 Hz):

| pair | real | synthetic (5 seeds) | old generator |
|---|---|---|---|
| 1–2, per sample, threshold 50 % of each sensor's p95 \|wz\| | 1.2 % | 2.1 ± 0.5 % | 52.6 % |
| 1–2, per sample, fixed 3°/s | 1.1 % | 5.4 ± 0.4 % | 50.0 % |
| 2–3, per motion episode | 3.2 % | 1.1 ± 0.8 % | 65.0 % |

- The 26.7 % previously reported for real 1–2 was a measurement artifact: wz
  interpolated across gaps, and a 3°/s threshold on a sensor whose yaw is mostly
  below that.
- With per-sensor thresholds at 20 % of p95, sensor_2's yaw is at noise level and the
  per-sample sign is random (real 52 %). That is why 50 % is shown.
- The earlier synthetic excess (52 % at the 50 % threshold) came from the random
  rest-hold model. Replaying the real freeze pattern fixed it.

### Review follow-up: what changed and why
- **Omega peaks "clipped 13–15 %"** was a timing artifact, not template smoothing:
  - Removing savgol changed nothing (sensor_1 F4 p99 44.6 → 44.1).
  - On a jitter-free slerp grid, synthetic and real p99 already agreed within 1–3 %.
  - Root cause: the engine moved the arm in step with the jittered timestamps, while
    the real XDK samples on a regular clock.
  - Fixed with the regular-clock model. Speed p99 at normal dt is now 45.2 vs 45.2 °/s
    for sensor_1.
- **Nearest-sample replay** keeps the real per-step texture; linear interpolation
  smoothed it. Template time sits on the real internal clock. Using the logged
  timestamps there produced skipped samples (speed p99 72 vs 45 °/s), now fixed.
- **Tried and reverted:** resampling the real logging residuals i.i.d. as timestamp
  jitter. It overshot omega p99 (sensor_1 +7 %, sensor_2 +2 %), because the real
  residuals are autocorrelated.

### Limitations
- **Recommended duration: ≤ the recording length (94.9 min).**
  - Past that, the physics gate still passes, but C2ST rises to 0.82–0.84 (hour 3 of the
    3-hour run), because drift outside the recording is not modelled.
  - Cycles past the recording come from the pose-compatible pool, and a warning is logged.
- It replays patterns that were recorded; it cannot produce a motion the arm never made.
- Noise is resampled real residuals, not a parametric model.
- The copy-paste check is uninformative for sensor_3.
- **C2ST accel/mag: cause unknown.** C2ST is reported, not blocking. It sits above its
  threshold because synthetic accel and mag windows are still separable from real.
  - The savgol mechanism was fixed (round 3): with a leak-free low-pass split, the in-cycle
    step correlation is ≈ 0 and the step variance equals real.
  - But accel C2ST fell only 0.01–0.03, so that mechanism is not the main cause.
  - No further accel/mag work is planned in this PR.
- sensor_1 omega p99 sits about +2 % above real; the re-derived ±7 % tolerance contains it.
- The 74 s outage in the real recording (all three sensors at once) is not reproduced. It is
  an anomaly, not normal logging behaviour. Normal dropped ticks (0.3–0.7 %) are reproduced.
- Earlier statement corrected: dt lag-1 autocorrelation over the full recording is −0.1 to −0.2
  (−0.4 to −0.5 held only for the first 100 rows).
- With the flag OFF, `ppt/arm_robot/sensor_1_syn.csv` already differed from a fresh
  run in the `temperature` column *before* this work (an older, unrelated change).
  sensor_2/3 are byte-identical.
