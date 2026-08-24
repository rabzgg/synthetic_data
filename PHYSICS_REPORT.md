# PHYSICS_REPORT.md — physical-validity of synthetic XDK output

Measurement only. No generator changes in this phase. Every synthetic number is
next to its REAL baseline (`baseline_before.json`, from `validate_physics.py
--suite`). Benchmark = robot-arm joints 1/2/3. Phase 0 = locked baseline.

Amendments A1–A4 (corrections to Step 0–2) applied and noted inline.

---

## Step 0 — verified assumptions

- **orientation = quaternion** (ENGINES.md: "quaternion components… ‖q‖=1"; XDK110 briefing).
- **w column:** arm robot stores only x/y/z → `w = clamp(√(1−s), 0)`, sign fixed by
  temporal continuity (double-cover). **s>1 ⇒ w=0**, i.e. an *invalid* rotation —
  reported, not silently renormalised (A1). Aquarium stores `orientation_w`.
- **accel = g** (|accel| median ≈ 0.998 ≈ 1g). **mag = milli-Tesla** per briefing,
  but raw magnitudes are unit-ambiguous, so Step 3 uses ratio metrics only.
- **sampling:** arm ≈10 Hz with large gap jitter; aquarium 10 Hz. Timestamps differ
  per file (ISO / epoch-ms / epoch-seconds) — detected per file.

### A4 — frame convention resolved on the ARM (moving data), aquarium confirms

Median gravity angle error over the 4 combinations, on quiet real samples:

| combo | arm j1 real | aquarium real |
|---|---:|---:|
| **Rᵀ·[0,0,+1]** | **1.1°** ✓ | **0.4°** ✓ |
| R·[0,0,−1] | 32.0° | 9.9° |
| R·[0,0,+1] | 148.0° | 170.1° |
| Rᵀ·[0,0,−1] | 178.9° | 179.6° |

Convention = **`g_sensor = Rᵀ·[0,0,+1]`** (q is body→world). On the arm the margin
is decisive (1.1° vs 32°); the near-static aquarium (where R ≈ Rᵀ) only weakly
separates, so the arm is the deciding dataset and aquarium is confirmation.

---

## Check 1 — quaternion validity  (s = x²+y²+z²)

| dataset | max s | %>1 | %>1.001 |
|---|---:|---:|---:|
| **arm j1 SYN** | **1.697** | **4.86%** | **4.81%** |
| arm j1 real | 1.0001 | 0.14% | 0.00% |
| arm j2/j3 SYN | 0.47 / 0.75 | 0% | 0% |
| aquarium real + all syn | ~0.54 | 0% | 0% |

Only **arm joint 1 synthetic** produces invalid rotations (4.8% of samples), because
it has the largest orientation motion and independent per-column generation pushes
x/y/z off the unit sphere. Real j1's 0.14% are all floating-point at the s=1 edge.

## Check 2 — gravity consistency  (angle between accel and quaternion-predicted gravity, °)

Quiet mask is a **quantile ("quietest-half")**, not a physical-static criterion (A2):
`|accel−1|<0.05` AND rolling-std below its own median → ~50%. An **absolute** run
(`||accel|−1|<0.02` AND rolling-std<0.01) is added; it passes ~0% on the arm (the
arm is never physically static) and ~100% on the aquarium. So arm numbers are the
quietest half of a moving signal.

Grav = median angle, quietest-half & s≤1. |accel| columns (B1) show how still the
mask really is: median ≈ 1g on both sides, so linear acceleration is small there —
the comparison is real-vs-syn **at the same condition**, not an absolute violation size.

| dataset | grav real | **grav syn** | \|accel\| med R/S | \|accel\| std R/S | syn p90 | syn max | quiet% (syn) |
|---|---:|---:|---:|---:|---:|---:|---:|
| arm j1 | 1.1° | **34.6°** | 0.998 / 0.998 | 0.006 / 0.020 | 77° | 180° | 49% |
| arm j2 | 0.3° | **4.1°** | 0.998 / 0.999 | 0.004 / 0.020 | 7.7° | 16.5° | 49% |
| arm j3 | 0.3° | **27.9°** | 1.001 / 1.002 | 0.004 / 0.029 | 45.6° | 63° | **10%** (A3) |
| aquarium fit100/50/opus | 0.4° | **0.4°** | ~0.995 / ~0.995 | tiny | ~0.9° | ~2° | 50% |

**B1 caveat (framing).** The mask is the **quietest half**, not physical stillness
(the absolute-static run passes ~0% on the arm — the arm never fully stops). So the
quiet samples still contain some linear acceleration, and part of any error is that,
not pure inconsistency. But |accel| median ≈ 1g and the REAL baseline is measured on
the **same mask** and gives only 1.1° / 0.3°. So the honest statement is a
comparison: **at |accel|≈1g quiet samples, real is 1.1° and synthetic 34.6°** — not
an absolute claim about the magnitude of the physical violation. (Note synthetic
|accel| std is 3–5× the real even in its quietest half.)

**A1 (dropping s>1 samples):** arm j1 syn goes 36.2° (all quiet) → **34.6°** (s≤1) —
barely moves. The 180° tail *is* the s>1 samples, but the **median is independently
broken**, so Check 1 and Check 2 are **not** double-counting one defect: validity is
the 4.8% tail, gravity inconsistency is pervasive across the other 95%.

**A3 (joint-3 coverage):** synthetic j3 passes the quiet mask on only **10%** of
samples (vs 49–50% elsewhere) — the calmest tenth — so 27.9° is a **lower bound**,
not an average. Loosening the |accel−1| tolerance raises coverage but not the error:

| tolerance | j3 syn quiet% | median | p90 |
|---|---:|---:|---:|
| <0.05 | 10% | 27.9° | 45.6° |
| <0.10 | 18% | 27.9° | 45.1° |
| <0.20 | 33% | 26.9° | 43.6° |
| <0.50 | 49% | 25.9° | 42.2° |

**Interpretation (contradiction flagged honestly).** The check splits on **moving
vs static**, not real-vs-synthetic. Where the device *moves* (arm j1 36°, j3 28° vs
real ~0.3–1°) synthetic orientation is **not physically valid**. Where it is
near-static (aquarium 0.4°, arm j2 4°) synthetic "passes" — but only because there
is almost no motion to decorrelate, so each column sitting at its real mean inherits
gravity consistency trivially. "Passing" on aquarium is **not** evidence the
generator preserves physics.

## Check 3 — magnetic world-frame stability  (std of mag rotated to world ÷ mean|mag|)

| dataset | side | mean\|mag\| | std\|mag\| (control) | world-std/mean (x,y,z) |
|---|---|---:|---:|---|
| arm j1 | real | 153.9 | 34.5 (22%) | 0.59, 0.36, 0.09 |
| arm j1 | **syn** | **65.3** | 29.5 | 0.60, 0.52, 0.52 |
| arm j2 | real | 59.0 | 9.8 | 0.16, 0.09, 0.06 |
| arm j2 | syn | 58.0 | 9.6 | 0.24, 0.17, 0.07 |
| arm j3 | real | 63.2 | 9.6 | 0.11, 0.12, 0.07 |
| arm j3 | syn | 61.5 | 16.5 | 0.21, 0.34, 0.30 |
| aquarium | real | 96.6 | 2.5 | 0.011, 0.026, 0.017 |
| aquarium | syn | 95.8 | 2.0 | 0.011, 0.026, 0.018 |

- **Weak real baseline on the arm (honest caveat):** even REAL arm mag is not a clean
  constant world field — j1 real magnitude varies 22% and world-std/mean reaches
  0.59. Likely hard/soft-iron and reconstructed-w limits. So this metric only has a
  clean baseline on the static aquarium, where real and synthetic are both excellent
  and nearly identical.
- **Synthetic is more scrambled** where there is motion (arm j3 syn 0.21/0.34/0.30 vs
  real 0.11/0.12/0.07 — no low axis remains), and **arm j1 |mag| is off by 2.4×**
  (153.9 vs 65.3 — the previously-noted number, verified). That magnitude miss is an
  isolated joint-1 scale error, separate from the correlation gap.

## Check 4 — angular velocity  (deg/s) — **PRIMARY METRIC** (with gravity)

This is the strongest, most interpretable result: it needs no quaternion or
sensor-fusion argument to read, and it has a **hard hardware ceiling** — a joint
physically cannot rotate faster than its motor allows. Actual per-sample dt used
(the ±314 ms timestamp jitter forbids nominal dt); intervals with dt>2×median dropped.

| dataset | side | median | p99 | max | dropped |
|---|---|---:|---:|---:|---:|
| arm j1 | real | 10.7 | 44.9 | 13811* | 0.4% |
| arm j1 | **syn** | 20.9 | **721.8** (659 at s≤1) | 1538 | 0.0% |
| arm j2 | real | 0.0 | 16.4 | 2489* | 0.3% |
| arm j2 | syn | 2.6 | 12.9 | 21.5 | 0.0% |
| arm j3 | real | 0.1 | 43.1 | 2973* | 0.4% |
| arm j3 | syn | 8.0 | 39.4 | 101.5 | 0.0% |

**% of synthetic rotations exceeding the real reference speed** (real max is
glitch-inflated, so `real p99` is the meaningful ceiling):

| joint | real p99 | syn p99 | % syn > real p99 | % syn > real max |
|---|---:|---:|---:|---:|
| j1 | 45°/s | **722°/s** | **11.5%** | 0.00% |
| j2 | 16°/s | 13°/s | 0.1% | 0.00% |
| j3 | 43°/s | 39°/s | 0.5% | 0.00% |

- **Real max is glitch-contaminated** (*13811°/s is impossible for the arm —
  residual timestamp/reconstructed-w glitches survive the gap filter). Nothing
  synthetic exceeds it (0%), which confirms it is a glitch, so **p99 is the honest
  ceiling**. Real imperfect too — reported, not hidden.
- **Synthetic joint 1 is physically impossible in ~1 sample in 9.** p99 = **722°/s
  vs real 45°/s (16×)**, and it stays 659°/s even after removing invalid-quaternion
  transitions (not a w=0 artifact). **11.5% of synthetic j1 rotations exceed the
  fastest 1% of real motion.**
- **Hardware ceiling — [USER TO VERIFY]:** no xArm/robot spec is present in the repo,
  so the absolute max-joint-speed cannot be cited from the data. **Fill in the
  documented max joint speed for this arm.** For reference, UFACTORY xArm-series max
  joint speed is commonly on the order of ~180°/s — *unverified for this model*. If
  the true ceiling is ≲180°/s, then synthetic j1's 659–722°/s bursts are **motions
  the arm cannot execute**, not merely "inconsistent" — a hard-physics violation.
- Joints 2/3 stay within real speeds (0.1–0.5% over p99); the failure is joint 1.
- Shape note: synthetic never truly rests (higher median: j2 2.6 vs 0.0, j3 8.0 vs
  0.1 — constant low-level motion) yet fires fast bursts — consistent with the
  trapezoid-ramp transitions vs the real near-vertical edges.

## Check 5 — cross-column correlation  (Pearson, real | syn | Δ)

Aquarium rows name the variant (A-note). Inter-axis correlation collapses to ~0 in
every synthetic dataset (columns fitted/generated independently):

| dataset | pair | real | syn | Δ |
|---|---|---:|---:|---:|
| arm j1 | orient qx–qz | **−0.991** | +0.018 | 1.009 |
| arm j1 | mag mx–mz | +0.806 | +0.244 | 0.562 |
| arm j1 | accel ay–az | −0.400 | +0.017 | 0.417 |
| arm j3 | orient qx–qz | +0.979 | −0.109 | 1.088 |
| arm j3 | accel ax–ay | −0.988 | +0.005 | 0.993 |
| arm j3 | mag mx–my | −0.976 | +0.009 | 0.985 |
| aquarium **fit100** | orient qx–qz | +1.000 | +0.160 | 0.840 |
| aquarium **fit100** | mag mx–my | +0.623 | +0.001 | 0.623 |
| aquarium **fit50** | orient qx–qz | +1.000 | +0.070 | 0.930 |
| aquarium **fit50** | accel ax–ay | +0.412 | +0.001 | 0.411 |
| aquarium **opus** | mag mx–my | +0.623 | +0.000 | 0.623 |
| aquarium **opus** | accel ax–ay | +0.412 | +0.000 | 0.412 |

Prior notes verified with variant now attached: the "aquarium qx-qz +1.000 → +0.160"
was **fit100**; fit50 is +0.070, opus similar for mag/accel.

## Check 6 — open questions (investigation only, kept off the fix phases)

**6a. Joint-1 −0.40 floor is NOT an explicit clip.** Config joint-1 orientation_x/z
have `engine=cycle_template`, `realism=None` — no `clip/min/max/range/bounds` field
anywhere. The floor comes from the **cycle_template extraction**: the stored
templates are normalised to a minimum of **exactly −0.5** in *both* columns, and
`resting + excursion×(−0.5)` gives **−0.384 (x)** and **−0.405 (z)** — hence the
identical ~−0.40 floor. Real swings to ∓0.75, but the template's −0.5 normalisation
floor caps the synthetic at −0.40. (Candidate fix noted below; not implemented.)

**6b. Half-period at joint 1 is a doublet split.** Real joint-1 inter-peak spacing is
**bimodal**: median gap 5.5 s but mean 18.7 s, p10 4.2 s vs p90 32.9 s (bimodal
hint = true). Short ~4–5 s gaps sit *inside* doublets, long ~33 s gaps *between*
them. The cycle detector counts each doublet spike as a separate cycle, which is why
the cycle-averaged period reads ≈half (14.2 s vs 28.6 s). It is a detector/segmenter
effect, not a generator period error per se.

**Cycle counts (B3 — baseline for a future doublet-detector fix):** detected
peak-to-peak cycles per joint (same detector both sides).

| joint | real | syn |
|---|---:|---:|
| j1 | 304 | 260 |
| j2 | 303 | 194 |
| j3 | 303 | 195 |

These are the numbers to diff against if the detector or generator is later changed;
they live in `baseline_before.json` under each pair's `cycles`.

---

## Summary vs benchmark (robot arm)

| joint | quat validity | gravity (syn vs real) | omega p99 (syn vs real) | orient corr Δ |
|---|---|---|---|---|
| 1 | **4.9% invalid** | **36° vs 1.1°** | 722 vs 45 (16×) | 1.01 |
| 2 | ok | 4° vs 0.3° (near-static) | 13 vs 16 | small motion |
| 3 | ok | **28° vs 0.3°** | 39 vs 43 | 1.09 |

Baseline is locked. Fixes are gated behind config flags in later phases; this file
is updated per phase with before/after on all four metrics.

---

## Phase 1 — quaternion normalization (behind flag `physics.enforce_quaternion_norm`, default OFF)

Change: a **cross-column** renormalization of the orientation vector, run after every
column's clipping (in `SyntheticXDKGenerator.generate`, mirroring the
`derived_rolling_std` deferred slot — the unit-norm couples the axes, so it cannot
live inside per-column `SensorRealism`). No w column ⇒ only samples with s>1 are
scaled down to s=1. Flag OFF is a byte-for-byte no-op, so the deck reproduces.

A/B on the 3 joints, same config + seed 42, flag the only difference:

| joint | metric | OFF (before) | ON (after) | verdict |
|---|---|---:|---:|---|
| j1 | validity: max s | 1.508 | **1.000** | **fixed** |
| j1 | validity: % s>1.001 | 5.09% | **0.0%** | **fixed** (residual 1.08% at s>1.0 is float-boundary noise) |
| j1 | gravity median | 34.9° | **35.9°** | **unchanged** (prediction confirmed) |
| j1 | omega p99 | 742°/s | 745°/s | unchanged |
| j1 | orientation KS (x/y/z) | 0.427/0.157/0.355 | 0.427/**0.131**/0.355 | not hurt (y improves; max Δ +0.001 on W) |
| j2, j3 | all four | — | identical | no-op (no s>1 to fix) |

**Result: Phase 1 does exactly what it targets and nothing more.**
- **Quaternion validity fixed:** max s 1.508 → 1.000, real violations (s>1.001) → 0%.
  Only the 5.1% invalid samples were touched (max value change ~0.13); marginals are
  not hurt (orientation KS/Wasserstein change ≤ 0.001, orientation_y KS actually
  improves 0.157 → 0.131).
- **Gravity error UNCHANGED (34.9° → 35.9°) — the prediction was correct.**
  Renormalizing makes the quaternion a *valid* rotation, but that rotation is still
  unrelated to the independently-generated accel column, so the gravity angle does
  not improve. This is Phase 2's job, not Phase 1's.
- **Omega unchanged** (norm is not a temporal property) and **correlation unaffected**
  (values move only on the 5% invalid samples).

Honest note: the residual "1.08% s>1" after the fix is pure floating-point at exactly
s=1.0 (`max s = 1.0000000000000004`); the meaningful validity metric `%>1.001` is 0.
Not tuned away — reported as-is.

Files for revert: generator change is one flagged block in `core/generator.py`
(before `df = pd.DataFrame(data)`); A/B configs and CSVs in `phase1_out/`.

---

## Recommended fixes (NOT implemented — for the fix phases / notes)

- **Gravity (Phase 2):** derive the gravity component of accel from the generated
  quaternion (like `derived_rolling_std`), keep residual accel statistical.
- **Quaternion validity (Phase 1):** renormalise the orientation vector after
  clipping so s≤1.
- **Correlation (Phase 3):** Cholesky-correlated residual noise within a sensor group.
- **6a (separate):** the `cycle_template` −0.5 normalisation floor caps amplitude;
  widening it to the real observed excursion would restore the ∓0.75 swing.
- **j1 |mag| 2.4× scale:** isolated magnitude error to investigate separately.
