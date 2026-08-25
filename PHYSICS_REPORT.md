# Is the synthetic data physically real? 
This is measurement only. Nothing in the generator was changed for this report. Every synthetic number sits next to the real number it's compared against. The test bed is the robot arm, joints 1, 2, and 3.

## The basic idea
We check one thing that must always be true in the real world: gravity always points down.
The sensor has two ways of knowing "down." One is the accelerometer, which feels gravity directly. The other is the orientation reading, which stores which way the sensor is tilted. If you know the tilt, you can calculate which way "down" should be. In a real recording, those two answers must agree.
So the test is: calculate "down" from the tilt reading, calculate "down" from the accelerometer, and measure the gap between them in degrees. Small gap = the two readings agree = physically sensible. Big gap = they disagree = something that can't really happen.

## Step 0 — checking our own assumptions first
Before measuring anything, we confirmed a few basics:

* The orientation columns are quaternions (a 4-number way of storing tilt), not simple angles.
* The arm data only stores 3 of the 4 numbers. The 4th is rebuilt using math. When the rebuilt number would be invalid, we mark it as invalid rather than quietly hiding it.
* Accelerometer values are in units of "g" (1g = normal gravity at rest).
* We had to figure out which rotation convention the sensor uses (there are 4 possible ways to define it). We tested all 4 on data where the arm is actually moving, and one of them won by a landslide (1.1° error vs 32°, 148°, and 179° for the wrong ones). So we know the convention is right, not guessed.

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
One honest caveat: the "quiet" samples we tested this on aren't perfectly still — the arm never fully stops moving. So a small part of that gap could be normal movement, not pure inconsistency. But we checked the accelerometer readings in this same window and they're close to 1g on both real and synthetic data, meaning things are calm enough that the comparison is fair. And since we measured the real data on the exact same kind of "quiet" window and it stayed near 1°, the difference is real, not a measurement artifact.
We also double-checked two possible objections:

* Maybe the 34.6° number is just being dragged up by the invalid tilt values from Check 1? We removed those samples and re-measured: 34.6° barely moved. So the problem is everywhere, not just in the broken samples.
* Maybe joint 3's 27.9° is measured on too few samples to trust? We loosened the filter step by step, from 10% of samples up to 49%. The error stayed the same the whole time. It's a real number, not a fluke of a small sample.

Interesting twist: the near-still datasets (the aquarium sensor, and joint 2, which barely moves) score well on this test. But that's not because the generator understood the physics — it's because there's almost no motion to get wrong in the first place. This test only catches problems when something is actually moving.

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
Some column pairs should move in a locked, opposite, or matching way — like two ends of a seesaw. We measured how strongly they're linked in real data versus synthetic data.
Result: every single pairing we checked collapses toward zero in the synthetic data. For example, on joint 1, two tilt columns that move almost perfectly opposite in real data (−0.991, like a seesaw) show basically no relationship at all in synthetic data (+0.018). Same story for magnetic and accelerometer pairs, and for every version of the aquarium data we tested. The seesaw is broken everywhere we looked.

## Check 6 — two loose threads we chased down
Where does the −0.40 ceiling on joint 1 come from?

* We suspected a hard-coded limit in the settings. It's not that. It turns out the generator learns a single "template" of the motion from the real recording, and that template is automatically stretched so its lowest point sits at exactly −0.5. When that template gets scaled back up, it lands at about −0.40 — well short of the real data's swing down to −0.75. So the ceiling is a side effect of how the template gets built, not an intentional limit.

Why does joint 1's cycle look twice as fast as it should?

* The real motion turns out to happen in pairs — two quick movements close together, then a long pause, then two more. The tool that counts "how long is one cycle" was counting each half of the pair as its own full cycle, which makes the measured rhythm look twice as fast as it really is. This is a counting-tool issue, not proof that the generator's timing itself is wrong.

## The short version

| Joint | Is the tilt number valid? | Do tilt and accelerometer agree? | Is the spin speed realistic? | Do paired columns move together? |
|---|---|---|---|---|
| 1 | No — 4.9% invalid | No — 35° off vs 1° | No — 16x too fast | No — collapsed to ~0 |
| 2 | Yes | Close — 4° off vs 0.3° | Yes | Barely tested (barely moves) |
| 3 | Yes | No — 28° off vs 0.3° | Yes | No — collapsed to ~0 |

The one-sentence explanation for all of it: every column (tilt, accelerometer, magnetic field) is currently learned and generated on its own, completely separately from the others. Nothing in the generator knows they're supposed to describe the same physical object moving through space. That's why a column can look correct all by itself and still be physically wrong once you check it against its neighbors.

## What we fixed already: Phase 1 — making the tilt numbers valid
We turned on a fix (behind an on/off switch, off by default so nothing else changes) that rescales any tilt reading that broke the math rule from Check 1.
Result: exactly what we expected, nothing more and nothing less.

* The invalid-number problem is gone: 5.1% invalid → 0%.
* The "does tilt agree with the accelerometer" problem is unchanged (34.9° before, 35.9° after). We predicted this beforehand — making the tilt number mathematically valid doesn't connect it to the accelerometer column, since those two are still generated completely separately. Fixing that connection is a separate, bigger fix, planned next.
* Nothing else got worse. Spin speed, distribution shape, everything else stayed the same or improved slightly.

## Fixes we've identified but haven't built yet
* Connect accelerometer to tilt: calculate the gravity part of the accelerometer reading directly from the tilt number, instead of generating it separately. This is the fix that should close the 34.6°/27.9° gap.
* Make paired columns move together: add correlated noise within each sensor's group of columns, instead of generating each one in isolation.
* Widen the joint-1 ceiling: fix the template-scaling issue so the motion can reach its real full range.
* Fix the joint-1 magnetic scale error: investigate the 2.4x magnitude mismatch separately.
