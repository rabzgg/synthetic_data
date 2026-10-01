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

**TL;DR.** The arm's physics failures came from generating every motion column on
its own (own template, own period). The joint-template engine replays whole real
arm cycles instead: orientation, accel and mag of all three sensors come from the
same moment of the recording, on one shared cycle schedule. All mandatory physics
gates pass on 5 seeds and on every hour of a 3-hour run. **Claim:** physical
consistency is inherited from the real recording; whole orientation–accel–mag cycles
are taken together and the three sensors share the same schedule. The sensor →
arm-link mapping is **[USER TO VERIFY]**. Nothing below says which link a sensor is on.

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

### Noise model, measured on the real XDK
| property | real | used |
|---|---|---|
| quaternion identical to previous sample, at rest | 63 / 72 / 77 % (s1/s2/s3) — **not** 100 % | sample-and-hold with the measured update rate |
| orientation noise while moving | floor 12–40× above the 1e-4 quantisation | rotation-vector noise at that floor |
| accel step while the whole arm is still | typically 1 LSB (0.001 g), std 0.004–0.009 g (clustered) | residual of another real cycle, same phase |
| accel noise while the arm moves | 2–5× larger (vibration) | (same) |
| resolution | quat 1e-4, accel 0.001 g, mag integer | same |

A stationary Gaussian per axis (the first attempt) dropped Check 7b to 61 %, and an
i.i.d. empirical bootstrap gave 62 %. Phase-aligned residual swap gives ~91 %.

### Physics gate (`physics_gate.py`; fixed thresholds; real in brackets)
Thresholds:
- validity: 0 % of samples with s > 1 + 1e-3
- gravity: median quiet error < 2°
- omega p99: within ±25 % of real
- jumps: 0 non-flip quaternion jumps
- Check 7b ≥ 85 %, Check 7c lag 0 ms
- copy: ≤ 5 % of windows with corr > 0.99 (s1, s2)

| seed | grav s1/s2/s3 (1.11/0.33/0.33°) | omega p99 s1/s2/s3 (44.9/16.4/43.1) | 7b (94.3) | 7c | copy s1/s2 | jumps | result |
|---|---|---|---|---|---|---|---|
| 42 | 1.15 / 0.34 / 0.34 | 42.8 / 15.5 / 42.2 | 91.7 | 0 ms | 0 / 0 % | 0 | PASS |
| 43 | 1.26 / 0.34 / 0.35 | 42.9 / 15.6 / 42.3 | 91.2 | 0 ms | 0 / 0 % | 0 | PASS |
| 44 | 1.25 / 0.34 / 0.35 | 42.7 / 15.5 / 42.2 | 90.6 | 0 ms | 0 / 0 % | 0 | PASS |
| 45 | 1.31 / 0.34 / 0.35 | 42.7 / 15.5 / 42.2 | 91.1 | 0 ms | 0 / 0 % | 0 | PASS |
| 46 | 1.23 / 0.34 / 0.34 | 42.6 / 15.6 / 42.2 | 91.5 | 0 ms | 0 / 0 % | 0 | PASS |

Against `baseline_before.json` (deck, seed 42):
- sensor_1 gravity 36.2 → 1.15°; omega p99 722 → 42.8°/s; % s > 1 (strict) 4.86 → 0.15 (real 0.14).
- sensor_3 gravity 27.9 → 0.34°.

Gate definition notes:
- The copy check excludes sensor_3: its real cycles are near-identical to each other
  (held-out vs training max-corr 0.997), so similarity cannot separate replay from
  real data.
- The jump check counts one-sample steps only (dt ≤ 2× median, the same rule as
  omega). A step across a timestamp gap is checked by angular speed instead
  (must be ≤ real p99 + 25 %). One seed-42 sensor_1 transition across a 0.98 s
  gap had flipped hemisphere mid-gap and was a false "jump" under the first
  definition.

### Longer than the recording (3 h, seed 42; recording = 94.9 min)
Gate run separately on each hour:

| hour | grav s1 | omega p99 s1 | 7b | 7c | copy s1 | result |
|---|---|---|---|---|---|---|
| 1 (0–60 min) | 1.18° | 42.7 | 91.9 % | 0 ms | 0 % | PASS |
| 2 (60–120, crosses end of recording) | 1.21° | 42.8 | 91.6 % | 0 ms | 1.0 % | PASS |
| 3 (120–180, all past the recording) | 1.30° | 43.0 | 91.4 % | 0 ms | 0 % | PASS |

- Splices after the recording: tilt ≤ 0.19°, full pose ≤ 2.97°, no fallbacks.
- Only 25 of 120 cycles are pose-compatible with the end-of-recording pose, so the
  orientation stays near that pose.
- The log warns that drift outside the recording window is not modelled.
- The first 3 h run failed 7c in hour 3 (100 ms lag). Cause: the engine timed motion
  from each file's first sample, and Check 7 aligned synthetic files on per-file
  elapsed time, so per-hour chunks started up to 88 ms apart. Fixed by timing motion
  on the generator's shared clock and aligning synthetic files on absolute
  timestamps (`check_inter_sensor(..., syn_use_abs=True)`; default unchanged).

### Sensor identity (Level 1 only: is synthetic sensor_k recognisable as real sensor_k?)
Level 2 (which link a sensor is on) is **not** answered: the mapping is **[USER TO VERIFY]**.

Fingerprints are heading-independent (F1 gravity direction at rest, F2 body-frame
rotation axis, F3 axis-vs-gravity angle, F4 speed). Distance = Wasserstein (F1–F3)
or KS (F4); "nearest other" = the closest *other* real sensor.

| sensor | F1 syn→own / →other | F2 | F3 (°) | F4 | old generator closer to own? |
|---|---|---|---|---|---|
| sensor_1 | 0.0013 / 0.038 | 0.009 / 0.38 | 0.86 / 46.6 | 0.043 / 0.48 | F2, F3 **no** |
| sensor_2 | 0.0005 / 0.039 | 0.013 / 0.32 | 0.66 / 7.5 | 0.042 / 0.35 | all yes |
| sensor_3 | 0.0075 / 0.45 | 0.010 / 0.33 | 0.60 / 6.5 | 0.042 / 0.35 | F2, F3 **no** |

Random-forest classifier on 10 s windows of motion columns only (temp, light,
humidity, pressure, id and timestamp excluded: temperature offsets alone identify the
device). Trained on real with an interleaved per-cycle split.

| case | accuracy (all / no mag / frame-safe) |
|---|---|
| a real holdout | 1.00 / 1.00 / 1.00 |
| b joint template (bank = whole recording, overlaps training) | 1.00 / 1.00 / 1.00 |
| b2 joint template from held-out cycles only (leak-free) | 1.00 / 1.00 / 1.00 |
| c old generator (deck) | 0.87 / 0.99 / 0.97 (sensor_2 and sensor_3 recall 1.00) |
| d shuffled labels | 0.32 / 0.33 / 0.33 |

**Verdict:** the identity test is too weak to gate on. Control c, the old generator,
passes it: classifier recall 1.0 for sensor_2/3, and F1–F4 closer to its own sensor
for sensor_2. The three sensors differ so much in static mounting orientation and
motion type that anything reproducing per-sensor marginals is "recognised".
`physics_gate.py --identity` therefore reports these checks as **informational**
only. Identity does not depend on the magnetometer: accuracy is the same without
mag and with heading-independent features only.

F6 (cross-sensor relations):

| relation | real | joint template |
|---|---|---|
| activity correlation (1–2 / 1–3 / 2–3) | 0.96 / 0.95 / 0.92 | 0.95 / 0.94 / 0.92 |
| rotation-amplitude ratio per cycle (s2/s1, s3/s1) | 0.16, 0.39 | 0.16, 0.39 |
| counter-rotation about the vertical, s1–s2 | 26.7 % | **9.0 %** (not reproduced; cause not investigated) |

### Limitations
- It replays patterns that were recorded; it cannot produce a motion the arm never made.
- Drift is not extrapolated outside the recording (log warning when the requested duration is longer).
- Noise is resampled real residuals, not a parametric model.
- The copy-paste check is uninformative for sensor_3.
- The identity test failed control validation (see above).
- With the flag OFF, `ppt/arm_robot/sensor_1_syn.csv` already differed from a fresh
  run in the `temperature` column *before* this work (an older, unrelated change).
  sensor_2/3 are byte-identical.
