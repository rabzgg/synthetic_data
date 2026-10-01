# EVAL.md — evaluation audit and metric definitions

Purpose: give every number on the results slides a source, and correct the
factual errors flagged in the review. Each section below maps 1:1 to a deck
slide so the text box on that slide can be pasted from here.

All statistical numbers were recomputed from the exact CSV pairs used to build
the deck (`ppt/fridge/`, `ppt/aquarium/`, `ppt/arm_robot/`) with `stat_eval.py`.
All metrics are "lower = more similar".

---

## TL;DR (read this first)

1. **The "pressure KS 0.2 is above the bad threshold" claim was wrong.** KS and
   Wasserstein use *different* bands. Pressure KS D = 0.202 lands in **OK**
   (KS band: GOOD < 0.10, OK < 0.25), not POOR. The 0.15 figure is the
   *Wasserstein* cutoff and was applied to the wrong metric.
2. **"Only 1 of 6 fridge features is good" was wrong.** Recounted with the
   correct band per column: by KS, **2 GOOD / 3 OK / 1 POOR**; by Wasserstein
   (value), **3 GOOD / 3 OK**.
3. **"ASF" is not a metric.** It is **ACF diff** (autocorrelation-function
   difference). The term is now expanded in `stat_eval.py` output and in the
   metric definitions below.
4. **The LLM (Opus) claim is not supported by the deck's own numbers.** Opus is
   on par with, or better than, the 50% fit on most columns, and it even beats
   the 100% AutoFitter fit on 4 of 7 aquarium columns. It loses in exactly one
   place that matters: **light**, because it does not model the physical
   constraint that the light is only on for a couple of hours.
5. **The aquarium light bug is real and specific to the Opus/LLM config.**
   Real light is on ~2.5 h/day; the Opus config keeps it on **~11 h/day** and
   never reaches full brightness. The AutoFitter 50%/100% configs reproduce the
   ~2 h duration correctly. This is a config-quality problem, not a generator
   problem.
6. **KS bands are project-internal, not a hypothesis test.** At these sample
   sizes the formal KS test always rejects (see the D_crit argument below), so
   D is used as an *effect size*. Slides must say this instead of implying a
   textbook pass/fail threshold.

---

## A. Audit — corrected claims

### A0. "ASF metric" → ACF diff  (was: Slide with the "ASF" label)

There is no metric called ASF. The intended metric is **ACF diff**: the mean
absolute difference between the real signal's autocorrelation function and the
synthetic signal's autocorrelation function. "ACF" = **autocorrelation
function**. It is now spelled out in full in the `stat_eval.py` docstring, its
printed reading guide, and section B below.

### A1. Fridge verdict table — corrected  (Slide 9)

Recomputed from `ppt/fridge/fridge_xdk1_real.csv` vs `ppt/fridge/fridge_xdk1_syn.csv`
(n = 46,378 after length-matched subsampling). Bands applied **per metric**:

| Column          | W(value) | KS (D) | W(incr) | ACF diff | ACF MSE | KS verdict | W(value) verdict |
|-----------------|---------:|-------:|--------:|---------:|--------:|:----------:|:----------------:|
| temperature     |   0.0713 |  0.264 |  0.0139 |   0.0361 |  0.0017 | POOR       | OK               |
| light           |   0.0825 |  0.083 |  0.0000 |   0.0033 |  0.0000 | GOOD       | OK               |
| humidity        |   0.0411 |  0.114 |  0.0120 |   0.0363 |  0.0017 | OK         | GOOD             |
| pressure        |   0.0702 |  0.202 |  0.0630 |   0.0038 |  0.0000 | OK         | OK               |
| acceleration_z  |   0.0123 |  0.012 |  0.0140 |   0.0259 |  0.0007 | GOOD       | GOOD             |
| rolling_std     |   0.0241 |  0.217 |  0.0025 |   0.4088 |  0.1838 | OK         | GOOD             |

Bands: W(value)/W(incr)/ACF diff — GOOD < 0.05, OK < 0.15. KS(D) — GOOD < 0.10,
OK < 0.25. ACF MSE — GOOD < 0.01, OK < 0.05.

**Corrected counts:**
- **By KS (D):** 2 GOOD (light, acceleration_z), 3 OK (humidity, pressure,
  rolling_std), 1 POOR (temperature). → **not** "1 of 6".
- **By Wasserstein (value):** 3 GOOD (humidity, acceleration_z, rolling_std),
  3 OK (temperature, light, pressure).

**Pressure specifically:** KS D = **0.202 → OK**, not POOR. Report both metrics
so the reader sees it is decent on value distribution (W = 0.070, OK) and only
mediocre on the KS effect size (D = 0.202, ~20% of the mass shifted at worst).

**One number to flag honestly:** `rolling_std` ACF diff = **0.4088** (ACF MSE
0.1838) is the worst temporal-structure number in the table. `rolling_std` *is*
correctly assigned to the `derived_rolling_std` engine in the config, so this is
not an engine-assignment bug — it is a genuine limitation to investigate, not to
hide. (Follow-up item, not deck-blocking.)

**Diagnostic — why temperature is POOR (KS 0.264): it is the plateau, not the
warm-up.** (Diagnostic only, not a replacement for the headline number.)
- Re-running `stat_eval` on temperature **excluding the first 90 min** (the
  warm-up) makes it *worse*, not better: **KS 0.264 → 0.387**, and W(incr)
  **0.014 → 0.084 (~6×)**. So the disagreement lives in the plateau region, and
  the jump in W(incr) — the step-to-step texture metric — points at a per-cycle
  *shape* mismatch, not a warm-up transient.
- **Correction — the earlier "linear vs exponential" curvature claim was a
  misalignment artefact, retracted.** Fitting a line to a fixed *time* window
  (real 10–12% deviation vs synthetic 3%) blurred cycles that do not line up. Redone
  properly as a **cycle-averaged** shape (detect peaks in the plateau, take each
  peak-to-peak cycle, normalise to a common phase and amplitude, average
  separately; `ppt/fridge/temp_cycle_averaged.png`), the averaged curvatures are
  **similar**: real fall 14.6% / rise 21.7%, synthetic fall 13.6% / rise 17.9% of
  amplitude. So the per-cycle *curvature* is NOT the problem.
- **What the cycle-average does show (n = 7 cycles each):**
  - **Inverted asymmetry.** Real trough sits at phase **≈ 0.29** (fast fall, slow
    rise); synthetic trough at phase **≈ 0.60** (slow fall, fast rise) — the two
    mean cycles are near mirror images in time.
  - **Period regularity.** Real **28.3 ± 1.0 min** (very regular); synthetic
    **30.1 ± 5.7 min** — ~6× more cycle-to-cycle jitter. The synthetic cycles are
    individually irregular in timing.
  - **Amplitude.** Synthetic **908 ± 18** vs real **782 ± 75** raw: synthetic swings
    a bit wider *and* far more uniformly (real amplitude varies cycle to cycle).
  - **Per-sample texture** (unchanged from before, still valid): synthetic plateau
    jitter std ≈ 53 vs real ≈ 8.5, ~7.5% vs ~52% held samples — this is what drives
    the W(incr) 0.014 → 0.084 jump.
- **What actually drives the phase-invariant KS 0.387.** KS/Wasserstein are
  phase-invariant, and a time-mirrored shape has essentially the same value
  histogram, so the inverted asymmetry does **not** explain the KS. The drivers are
  the ones that change the value/level distribution: the amplitude and
  cycle-to-cycle level spread differ (real drifts across cycles, synthetic is
  uniform) and the per-sample texture is ~6× too noisy. So the honest summary is:
  the synthetic temperature cycles are individually about the right *curvature* but
  **mirror-asymmetric, over-uniform in amplitude, irregular in period, and too
  noisy per sample** — not a simple "linear-ramp" shape error.

### A2. Aquarium: LLM (Opus) vs AutoFitter — corrected  (Slide 15)

Head-to-head on `ppt/aquarium/aquarium_xdk1_real.csv`, metric = **Wasserstein
(value)**, lower = better. Opus config vs 50% fit vs 100% fit:

| Column          | Opus   | Fit 50% | Fit 100% | Opus vs 50% | Opus vs 100% |
|-----------------|-------:|--------:|---------:|:-----------:|:------------:|
| orientation_x   | 0.0852 |  0.3683 |   0.3089 | Opus better | Opus better  |
| acceleration_y  | 0.0255 |  0.0947 |   0.0387 | Opus better | Opus better  |
| mag_x           | 0.0157 |  0.0264 |   0.0266 | ~tie (both GOOD) | Opus better |
| humidity        | 0.0352 |  0.0303 |   0.1145 | ~tie (both GOOD) | Opus better |
| pressure        | 0.1317 |  0.1045 |   0.0988 | 50% better  | 100% better  |
| light           | 0.1411 |  0.1116 |   0.0462 | **Opus worse** | **Opus worse** |
| acceleration_z  | 0.0518 |  0.0275 |   0.0175 | Opus worse  | Opus worse   |

**Honest conclusion:** Opus is roughly **on par with or better than** the 50%
fit, and beats even the 100% AutoFitter fit on 4 of 7 columns
(orientation_x, acceleration_y, mag_x, humidity). It loses on **light** (the
physical-constraint failure, see A3), and is somewhat worse on pressure and
acceleration_z. The blanket statement "the LLM underperforms, especially at 50%
input" is **not** supported by these numbers — the failure is narrow and
specific, not general.

**Input fraction Opus received: not recorded.** The Opus config
(`configs/aquarium/aquarium_01_2d_opus.json`) stores only
`domain / sensor_position / frequency_hz / duration_s` — no provenance. The LLM
*wrote* the config from a prompt; it was not *fitted* from a stated data
percentage, so "input fraction" is not directly comparable to the 50%/100% fits.
The slide should state this rather than imply a fair like-for-like comparison.

### A3. Aquarium light duration — the real physical-constraint bug  (Slide 11/12)

Measured light-on time (share of samples above half the per-file maximum):

| Variant | light-on per day | max light level | note |
|---------|-----------------:|----------------:|------|
| real    | **~2.5 h**       | 11520 (full)    | ground truth |
| Fit 50% | ~1.6 h           | 2880 (dim)      | AutoFitter, plausible duration |
| Fit 100%| ~2.6 h           | 11520 (full)    | AutoFitter, matches real |
| Opus    | **~11 h**        | 2880 (dim)      | **LLM config — far too long, never full brightness** |

This confirms the reviewer's "light stays on far too long" point and pins it to
the **Opus/LLM config**, not the AutoFitter path. The fix belongs at config-
validation level (record and enforce the measured on-duration bounds), which is
the Task-6 work item — deferred until after the deck per agreed priority.

---

## B. Metric definitions (formula · meaning · band)

Each metric below has a formula, a one-line plain-language meaning, and the
justification for its band. Bands are labelled honestly as project-internal
where they are not textbook thresholds.

### B1. Wasserstein (value), normalized

- **Formula:** `W1(real, syn) / (max(real) - min(real))`, where `W1` is the
  1-D Wasserstein-1 (earth-mover) distance between the two value distributions.
- **Measures:** how far the whole value distribution has to be "moved" to match
  the real one — captures shifts in mean and spread. Dividing by the real range
  makes it unitless and comparable across columns.
- **Good looks like / why:** GOOD < 0.05, OK < 0.15 (project-internal, visual
  calibration). 0.05 means the average probability mass moves < 5% of the
  signal's full range — visually indistinguishable histograms in our data.

### B2. Wasserstein (increment), normalized — the texture metric

- **Formula:** `W1(diff(real), diff(syn)) / (max(diff(real)) - min(diff(real)))`,
  i.e. the same distance but on the per-step changes `x[t+1] - x[t]`.
- **Measures:** *how the signal moves step to step* (roughness / texture). This
  catches a synthetic column that has the right histogram but the wrong
  smoothness — e.g. too jittery or too flat between the same min and max.
- **Good looks like / why:** same band as B1. It is the metric that separates
  "right values, wrong dynamics" from a genuine match.

### B3. KS statistic (D) — read as an effect size, not a hypothesis test

- **Formula:** `D = max over v of |F_real(v) - F_syn(v)|`, the maximum vertical
  gap between the two empirical cumulative distribution functions (CDFs).
- **Measures:** the single worst point of disagreement between the two
  distributions. D = 0.10 means "at worst, 10% of the probability mass has
  shifted" — this reading is definitional and needs no citation.
- **Why we do NOT use it as a pass/fail test:** the alpha = 0.05 two-sample
  critical value is
  `D_crit = 1.36 * sqrt((n + m) / (n * m))`.
  For fridge (n = m ≈ 46k) `D_crit ≈ 0.009`; for aquarium (n ≈ 774k)
  `D_crit ≈ 0.002`. Every single column — including ones that overlay almost
  perfectly — has D far above D_crit, so the formal test *always* rejects "same
  distribution". The hypothesis test is therefore uninformative at sensor sample
  sizes. `stat_eval.py` now prints D, D_crit and the p-value together so this is
  visible on the output.
- **Good looks like / why:** GOOD < 0.10, OK < 0.25 (**project-internal
  effect-size bands, grounded against the empirical real-vs-real floor — NOT
  significance tests**; see section D). Slides must carry this label; it is the
  direct fix for "thresholds presented with no source".
- **Field practice this follows (verify exact wording before quoting on a
  slide):** reporting a continuous distribution-similarity *score* rather than a
  binary pass/fail is standard in synthetic-data evaluation — e.g. SDV's
  SDMetrics reports **KSComplement = 1 − D** as a per-column shape-quality score;
  TSTR (train-on-synthetic, test-on-real) originates with Esteban, Hyland &
  Rätsch (2017); TimeGAN (Yoon et al., NeurIPS 2019) reports continuous
  discriminative/predictive scores. Cite these only for the narrow claim
  "the field reports continuous scores, not pass/fail", which is what we do.

### B4. ACF diff and ACF MSE — temporal structure (self-similarity)

- **Formula:** compute each signal's own normalized autocorrelation function
  independently, `acf_r[k]` and `acf_s[k]` for lags k = 0..N (default N = 300),
  where `acf[k] = sum_t (x[t]-mean)(x[t+k]-mean) / (var * n)`. Then:
  - **ACF diff** = `mean_k |acf_r[k] - acf_s[k]|`
  - **ACF MSE**  = `mean_k (acf_r[k] - acf_s[k])^2`
- **Measures:** whether the synthetic signal preserves the **real signal's own
  temporal structure** (stickiness, drift, periodicity). **This is NOT a
  correlation between the real and synthetic signals.** Each signal's
  self-similarity curve is computed separately and the two *curves* are then
  compared. This is the framing fix for the autocorrelation slide.
- **Why MSE is valid here (but not on raw values):** ACF diff and ACF MSE
  compare two curves that correspond point-to-point (lag 0 to lag N), so a
  standard MSE is meaningful. Raw-value MSE between real and synthetic would
  require the two to be the *same realization* — which for synthetic data would
  mean the data was copied — so raw-value MSE is deliberately not used.
- **Good looks like / why:** ACF diff — GOOD < 0.05, OK < 0.15; ACF MSE —
  GOOD < 0.01, OK < 0.05 (project-internal). MSE is smaller because it squares
  values < 1.

### B5. TSTR (from `tstr_eval.py`) — utility, standard names

- **Metrics:** RMSE and MAE of a forecaster **T**rained **o**n **S**ynthetic,
  **T**ested **o**n **R**eal, compared to TRTR (train on real) and a naive
  (last-value) baseline. These are already standard named metrics — the deck
  just needs to label them RMSE / MAE explicitly and name the column each row
  was computed on.

---

## C. TSTR (utility) — slide 12

**What slide 12 actually is.** The old slide-12 TSTR table (TSTR 0.0032 / TRTR
0.0040 / naive 0.0050, TSTR vs-naive 0.637×) was identified by reproduction: it
is **`rolling_std`, no detrend**, on `ppt/fridge/fridge_xdk1_real.csv` vs
`ppt/fridge/fridge_xdk1_syn.csv`. All four numbers match exactly (TSTR/TRTR =
0.808), and it agrees with ENGINES.md's `derived_rolling_std` note ("TSTR/TRTR
1.31 → 0.81"). Engine: `derived_rolling_std`. Verdict: **GOOD** — synthetic
`rolling_std` beats the naive baseline and is a strong training substitute.

**temperature TSTR (a different, later experiment).** Engine `gradual_curve`.
- **Detrended (the correct method for a warm-up drift):** TRTR 0.478× vs naive,
  TSTR 3.168× vs naive, TSTR/TRTR 6.62. TRTR beats naive but TSTR does not →
  the synthetic temperature does not yet transfer. Consistent with temperature
  being the POOR column (KS D = 0.264).
- **No detrend (degenerate — kept off the slide):** on a monotonic warm-up the
  lag-1 naive baseline is trivially near-perfect (naive RMSE ≈ 33 on a ~12,000
  range), so the vs-naive ratios explode into meaningless artifacts:
  **TRTR ≈ 57× and TSTR ≈ 275× vs naive** (TSTR/TRTR 4.80). These numbers say
  nothing about generator quality — they are recorded here and deliberately kept
  off the slide.

**Why `rolling_std` is GOOD on TSTR yet has ACF diff 0.409 (they are linked, not
independent).** ENGINES.md's design rationale for `derived_rolling_std` is that
it preserves autocorrelation (real lag-1 ≈ 0.998). Checking the actual ACF
curves confirms the mechanism and locates the split:

| lag | ACF real | ACF syn | \|diff\| |
|----:|---------:|--------:|---------:|
| 1   | 0.9958 | 0.9886 | 0.007 |
| 5   | 0.9771 | 0.9432 | 0.034 |
| 10  | 0.9523 | 0.8883 | 0.064 |
| 20  | 0.9246 | 0.7755 | 0.149 |
| 50  | 0.8456 | 0.4406 | 0.405 |
| 300 | 0.7059 | 0.1221 | 0.584 |

- **Lag-1 is preserved** (0.9958 vs 0.9886, Δ = 0.007). A one-step lag-window
  forecaster leans on exactly this short-lag structure → good TSTR (0.637×).
- **The curves separate from ~lag 8** (|Δ| > 0.05 at lag 8, > 0.10 at lag 15,
  > 0.20 at lag 26). By lag 50 real is still 0.85 while synthetic has fallen to
  0.44.
- **Real has long memory** (plateaus ~0.70 and never drops below it through lag
  300); synthetic decays to ~0.12. That long-lag divergence is what drives ACF
  diff = 0.409.

So ACF and TSTR are linked by our own design rationale: the synthetic preserves
the short-lag structure the forecaster needs (good TSTR) but loses the long
memory (large ACF diff). Not two unrelated metrics. Figure:
`ppt/fridge/rolling_std_acf.png`.

---

## D. Grounding the bands against the real data (real vs real)

The GOOD/OK bands were originally set by visual calibration. This section
replaces that opinion by scoring the **real** fridge recording against *itself*,
three ways (`empirical_floor.py`). Each split answers a different question, and
the honest reading of what each does (and does NOT) prove matters.

| column | random split KS (≈ D_crit) | block split KS (10-min, fair self-distance) | synthetic KS (slide 11) |
|---|---:|---:|---:|
| temperature | 0.009 | 0.175 | 0.264 |
| light | 0.003 | 0.018 | 0.083 |
| humidity | 0.007 | 0.125 | 0.114 |
| pressure | 0.007 | 0.102 | 0.202 |
| acceleration_z | 0.002 | 0.007 | 0.012 |
| rolling_std | 0.006 | 0.045 | 0.217 |

**1. Random row split — sets the scale of "identical", it is NOT independent
evidence.** Assign rows to A/B at random: both sides have the same marginal
distribution, so KS between them is just finite-sample noise. It comes out
KS ≈ 0.002–0.009 — which *is* the definition of `D_crit` (the spread of the KS
statistic under the null). So calling this "a second independent route that
confirms D_crit" would be wrong: it is D_crit **measured empirically**, one route
counted twice. What it legitimately does: it fixes where **zero** is —
KS ≈ 0.01 means indistinguishable — so the slide-11 numbers can be read on a real
scale instead of in the abstract. (Note `D_crit ≈ 0.013` here vs `0.009` on
slides 10–11 because each half has half the samples; both are correct.)

**2. Block split — the realistic self-similarity target.** Cut the recording into
contiguous 10-min blocks and compare odd blocks vs even blocks. Because the blocks
**interleave in time, both halves span the same trend** rather than one being the
"before" and the other the "after", so the difference is no longer dominated by
the trend *direction* — but each block still contains a slice of trend, which is
exactly why a fast-moving column scores higher than a stable one. Temporal
structure inside each block is preserved (unlike the random split, which destroys
ordering). This is the fair "how close is the real process to itself" number: the
real recording scores **KS ≈ 0.10–0.18 on the drifting environmental columns**
(temperature 0.175, humidity 0.125, pressure 0.102) and **≈ 0.01–0.05 on the
stable ones** (acceleration_z 0.007, rolling_std 0.045). *That* is the target a
synthetic column should aim for, right around the GOOD < 0.10 line — grounded in
data, not a chosen multiplier.

*Block-length choice:* the compressor cycle is **~28 min** (phase_on 897 s +
phase_off 774 s, from the config), so 10-min blocks are ~⅓ of a cycle and give
~34 blocks — enough for a stable KS while staying inside short stretches. The
self-distance is scale-dependent (environmental KS 0.04 at 5-min blocks → 0.18 at
20-min — longer blocks hold more trend) but stays an order of magnitude above the
0.01 noise floor at every length tested; that order-of-magnitude gap is the robust
claim, not a single precise target.

**3. Read the synthetic against the block target (this reframes slide 11):**
- **humidity (0.114) is actually BELOW the real recording's own self-distance
  (0.125)** — a genuine finding, not just "in range". **temperature is 1.5×**
  (0.264 vs 0.175) and **pressure 2.0×** (0.202 vs 0.102). So the drifting
  environmental columns are at, or within a factor of two of, how close the real
  data is to itself — not 20–30× a noise floor.
- **acceleration_z (KS 0.012)** sits at the **detection limit** (≈ `D_crit` 0.013)
  — as close to real as two random samples of the real data are. (Not "at the
  floor": the floor is 0.002; 0.012 is ~6× that but ≈ D_crit, which is the
  meaningful comparison.)
- **rolling_std (0.217 vs 0.045 = 4.8×)** is the one genuine distribution outlier —
  though it is the short-lag / TSTR winner (section C), so it fails on marginal
  shape while succeeding on utility.

**Caveat kept off the floor:** a chronological first-half-vs-second-half split is
trend-dominated (KS 0.80 temperature, 0.87 pressure) — it measures how much the
process *moves*, a rough ceiling, not a floor. `empirical_floor.py --split chrono`.

**What the grounding does and does not claim.** The random split fixes the scale
(zero at KS ≈ 0.01); the block split gives a realistic self-similarity target
(block KS ≈ 0.10 for environmental columns). It does **not** independently derive
the exact 0.10 / 0.25 cut points — those remain project-internal reading aids, now
anchored to a measured self-distance rather than to visual taste. The raw metric
value stays the primary number.

**Slide-10 wording (drop-in):** *"The bands are not from a published standard —
none exists. Scoring the real recording against itself sets the scale: two random
halves differ by KS ≈ 0.01 (this is D_crit — the noise floor, where 'identical'
sits). A fairer test — odd vs even 10-minute blocks, same time range but keeping
temporal structure — gives KS ≈ 0.10–0.18 for the drifting environmental columns:
that is how close the real data is to itself. GOOD < 0.10 sits right at that
self-similarity level. Read against it, synthetic humidity (0.114) is actually
below the real self-distance (0.125), temperature is 1.5× and pressure 2.0×, and
acceleration_z sits at the detection limit — none are the 20–30× a raw noise floor
would suggest. The raw metric value stays the primary number; the band label is
only a reading aid."*

---

## E. Aquarium: does Opus still win once temporal metrics are included? (slide 18)

Slide 18 originally compared variants on W(value) / KS only. W(value) is blind to
time ordering, so it can flatter a variant that gets the mean right but the
dynamics wrong. Re-run with **four** metrics (W(value), KS, W(incr), ACF diff)
across Fit 100% / Fit 50% / Opus, all vs the same real recording (`slide_18.png`,
`make_aquarium_table.py`). Best-KS variant per column:

- **Opus wins the near-static channels on *every* metric, including ACF diff:**
  orientation_x (KS 0.238 vs 0.483 / 0.627; ACF 0.008 vs 0.011 / 0.017),
  orientation_y (KS 0.201; ACF 0.004), acceleration_y (KS 0.087), mag_x (KS 0.173).
- **The AutoFitter fits win the physically-dynamic channels:** light (Fit 100%
  KS 0.093 vs Opus 0.256), pressure (Fit 100% 0.230 vs Opus 0.245), acceleration_z
  (Fit 100% 0.098 vs Opus 0.222). humidity: Fit 50% best on KS (0.146).

**On the orientation_x / orientation_y hypothesis** ("Opus draws a smooth ramp
while real is a stepped staircase, so it should lose on ACF diff"): the numbers do
**not** support it — Opus has the *lowest* ACF diff on both orientation columns.
The reason is that these quaternion channels barely move, so every variant's ACF
is near its floor (0.004–0.017) and ACF diff simply does not adjudicate the
staircase-vs-ramp shape the eye sees on slide 14. So the honest statement is: on
orientation, W(value) is what separates the variants and Opus wins it; the
temporal metrics are uninformative there because there is almost no temporal
structure to get wrong.

**So the reframed conclusion is stronger and more honest than "Opus wins 4/7 on
W(value)":** the split is by channel *type*. Opus wins the near-static
orientation/mag channels (it nails the level, and there is no dynamics to break),
and loses the channels with real structure (light, pressure, acceleration_z) to
the fitters. Two shared limitations show up across *all* variants, so they are not
a variant difference: `acceleration_y` ACF diff ≈ 0.64 and `mag_x` ACF diff ≈ 0.12
everywhere.

**Fit 50% orientation_y collapse (also a Task-D item):** under Fit 50%,
orientation_y has **ACF diff 0.999** (vs 0.015 at Fit 100%, 0.004 Opus) — the
50% window degenerated the fit to a dead flat line, destroying all temporal
structure. This is the visible "collapse" on slide 14; it is a fit-window failure,
not a metric artifact.

### Aquarium TSTR (utility) — pressure, all three variants (slide 18b)

`humidity` was tried first (the Task asked for it) but **TRTR lost to the naive
baseline (2.86×)** with no detrend: humidity settles to a flat line, so
"predict last value" is near-perfect and the forecasting test is uninformative for
that column. Switched to **pressure with detrend** (same settings for all
variants: train-ratio 10%, window 50, detrend on). There the test is meaningful —
TRTR beats naive (0.681×) — and all three synthetic variants also beat naive and
sit at TRTR level:

| model | RMSE | NRMSE | vs Naive | TSTR/TRTR |
|---|---:|---:|---:|---:|
| TRTR (real) | 2.3173 | 4.374% | 0.681× | — |
| TSTR (Fit 100%) | 2.3834 | 4.498% | 0.700× | 1.029 |
| TSTR (Fit 50%) | 2.4091 | 4.547% | 0.708× | 1.040 |
| TSTR (Opus) | 2.3444 | 4.424% | 0.689× | 1.012 |
| Naive | 3.4028 | 6.422% | baseline | — |

Every variant's pressure is a strong training substitute (beats naive, ~TRTR
level), Opus marginally ahead. Figure `slide_18b.png` (`make_tstr_pressure_table.py`).

---

## F. Robot-arm motion fidelity + cross-column correlation (measurement only)

Two diagnostics, no fix attempted — just how far off things are.

### F1. Per-joint cycle-averaged orientation shape (orientation_x, ppt/arm_robot/)

Same method as the fridge-temperature cycle average: detect peak-to-peak cycles,
normalise each to a common phase and amplitude, average real and synthetic
separately with a ±1σ band, and compare the first 5 vs the last 5 cycles.
Figures: `ppt/arm_robot/joint{1,2,3}_cycle_avg.png`.

| joint | mean-shape Δ (real vs syn) | period real / syn (s) | amplitude real / syn | across-run stability | verdict |
|---|---:|---|---|---|---|
| 1 | **0.222** | 28.6±14.2 / 14.2±9.6 | 1.32±0.29 / 0.95±0.18 | real drifts a lot (first5-vs-last5 Δ=0.37); syn fixed (0.007) | **does not match** |
| 2 | 0.029 | 18.8±6.2 / 18.6±3.3 | 0.057±0.00 / 0.059±0.00 | both stable (0.02 / 0.03) | **matches (best)** |
| 3 | 0.080 | 18.8±6.2 / 19.2±4.3 | 0.326±0.00 / 0.341±0.02 | stable; syn rise limb slightly slow | **matches (good)** |

- **Joint 2 best, joint 3 good, joint 1 worst.** Joint 2 reproduces the
  asymmetric sawtooth almost exactly; joint 3 reproduces the U-shaped valley well
  (synthetic rising limb is a touch slower/rounder, and its last-5 cycles lag the
  first-5 slightly). Both are stable across the run.
- **Joint 1 is the failure**, but for an instructive reason: the real joint-1
  motion is **not one repeating cycle** — its shape changes markedly across the run
  (first-5-vs-last-5 Δ = 0.37; the arm performs different motions in the second
  half). The `cycle_template` engine replays a single fixed template (syn drift
  0.007, essentially identical every cycle), so it cannot track that variety, and
  it also runs ~2× too fast (14.2 s vs 28.6 s) and under-swings the amplitude
  (0.95 vs 1.32). Note the joint-1 period figures are themselves unreliable because
  the motion is non-stationary.
- **Honest flag vs the earlier boss note.** The boss recalled "joints 1 & 2 replicate
  well, joint 3 fails". On this ppt data the ordering is the *opposite*: joint 3
  matches reasonably and **joint 1** is the one that does not. Worth reconciling
  which fit/recording the boss was looking at before repeating the joint-3 claim.
- **Raw orientation overlays** (`ppt/arm_robot/joint{1,2,3}_orientation_overlay.png`,
  x/y/z, first 5 min) confirm the ranking and add nuance the amplitude-normalised
  cycle average hides: joint 3 matches on raw levels too; **joint 2's normalised
  shape matches but its raw levels are compressed** (orientation_y plateau ~0.672
  synthetic vs ~0.69 real, smaller swing); joint 1's orientation_x/z have the wrong
  amplitude and sign coupling (real ±0.75 bipolar and x↔z anti-correlated; synthetic
  asymmetric and uncoupled). Phase is not locked in any joint (expected — the
  synthetic has its own timing).

### F2. Cross-column correlation, quaternion norm, vector magnitude

**Inter-axis correlation collapses to ~0 in every synthetic dataset** — expected,
since columns are fitted and generated independently (the known architecture gap
in ENGINES.md). Real axes are physically coupled (one device moving), synthetic
axes are not:

| dataset · pair | real | synthetic |
|---|---:|---:|
| arm j1 · orient qx–qz | **−0.991** | +0.018 |
| arm j3 · orient qx–qz | +0.979 | −0.109 |
| arm j1 · mag mx–mz | +0.806 | +0.244 |
| aquarium · orient qx–qz | **+1.000** | +0.160 |
| aquarium · mag mx–my | +0.623 | +0.001 |
| aquarium · accel ax–ay | +0.412 | +0.000 |

**Quaternion norm.**
- Aquarium stores `orientation_w`, so true ‖q‖ is computable: **both real and
  synthetic give ‖q‖ = 1.000 exactly** — but only because the aquarium device is
  near-static (the quaternion barely changes), so the norm holds *trivially*. This
  is not evidence the generator enforces the constraint.
- The robot arm stores only x/y/z (w implied by `w² = 1 − x² − y² − z²`, so a valid
  unit quaternion needs `x²+y²+z² ≤ 1`). **Real stays ≤ 1** (joint 1: mean 0.60,
  0.1% at the 1.0 rounding edge; joints 2–3: 0.0% over). **Synthetic joint 1
  reaches x²+y²+z² = 1.70 with 4.9% of samples > 1** — physically impossible, no
  real quaternion exists there. Joints 2–3 synthetic stay ≤ 1 only because they
  move less. So the norm constraint is genuinely violated once orientation moves.

**Vector magnitude.**
- **|accel| ≈ 1.0 g preserved everywhere** (real 0.996–0.997, syn 0.995–0.999) —
  the resting-gravity magnitude survives despite zero inter-axis correlation,
  because each axis sits near its own constant.
- **|mag|:** matches on aquarium (96.6 vs 95.8) and arm joints 2–3 (59.0/58.0,
  63.2/61.5), but **arm joint 1 is off by ~2.4×: real 153.9 vs synthetic 65.3** —
  an isolated magnetometer scale problem on joint 1, separate from the correlation
  gap.

---

## Reproduce these numbers

```
# fridge verdict table (Slide 9)
python3 stat_eval.py --real ppt/fridge/fridge_xdk1_real.csv \
    --syn ppt/fridge/fridge_xdk1_syn.csv \
    --cols temperature light humidity pressure acceleration_z rolling_std

# aquarium LLM-vs-fit comparison (Slide 15) — repeat for 50pct / 100pct / opus
python3 stat_eval.py --real ppt/aquarium/aquarium_xdk1_real.csv \
    --syn ppt/aquarium/aquarium_xdk1_opus_syn.csv \
    --cols orientation_x acceleration_y mag_x humidity pressure light acceleration_z

# TSTR slide 12 — rolling_std, NO detrend (the real slide-12 result)
python3 tstr_eval.py --real ppt/fridge/fridge_xdk1_real.csv \
    --syn ppt/fridge/fridge_xdk1_syn.csv --col rolling_std

# temperature TSTR — detrended (warm-up drift); no-detrend is degenerate
python3 tstr_eval.py --real ppt/fridge/fridge_xdk1_real.csv \
    --syn ppt/fridge/fridge_xdk1_syn.csv --col temperature --detrend

# band grounding (section D) — real vs real: random + block + chrono splits
python3 empirical_floor.py --csv ppt/fridge/fridge_xdk1_real.csv \
    --cols temperature light humidity pressure acceleration_z rolling_std \
    --split all --block-min 10

# aquarium 4-metric table (section E, slide 18) — repeat for 50pct / opus
python3 stat_eval.py --real ppt/aquarium/aquarium_xdk1_real.csv \
    --syn ppt/aquarium/aquarium_xdk1_100pct_syn.csv \
    --cols orientation_x orientation_y acceleration_y mag_x humidity pressure light acceleration_z

# aquarium TSTR (section E, slide 18b) — pressure with detrend, per variant
python3 tstr_eval.py --real ppt/aquarium/aquarium_xdk1_real.csv \
    --syn ppt/aquarium/aquarium_xdk1_opus_syn.csv --col pressure --detrend

# robot-arm per-joint cycle-averaged shape (section F1)
python3 arm_cycle_eval.py

# cross-column correlation / quaternion norm / |accel| |mag| (section F2)
python3 cross_corr_eval.py
```
