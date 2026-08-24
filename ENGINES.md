# Engine Reference

This file explains what each column "engine" does, when the AutoFitter picks
it, and what its known limits are. It's a supplement to the code, not a
replacement — line numbers refer to `core/generator.py` as of this writing
and will drift.

## The two-phase pipeline, one paragraph

`AutoFitter` reads a real CSV and *measures* it — durations, levels, noise,
rates, quantization steps — into a config JSON. Nothing from the raw CSV is
copied into that config; it's a statistical recipe, not a recording. `main.py`
then reads the config and *generates* a new CSV of any requested length. Each
column in the config has one `"engine"` value, which says which of the
classes below produced it and which one will regenerate it.

## Quick reference

| `"engine"` value | What is this used for? (plain language) | Models (technical) | Auto-picked when |
|---|---|---|---|
| `constant_noise` | A reading that stays about the same the whole time, just with everyday jitter — like a thermometer sitting still in one spot. | Flat baseline + noise (optionally per-state, sticky, ramped) | Default fallback; also genuinely static columns; also "held-then-steps-rarely" columns |
| `gradual_curve` | A reading that climbs or falls to a new normal and then stays there — like a fridge warming up after the door's been shut, or a bottle of soda going flat. Also covers a reading that just keeps drifting one direction the whole time, like barometric pressure falling for days before a storm. | Settle-then-plateau, or unbounded linear drift | Net change from start to end is large relative to noise |
| `cycling` | A reading that jumps between two clearly different values depending on what the machine is doing right now — like a vibration sensor that's loud while a motor runs and quiet the moment it shuts off. | A different LEVEL per state (not just different noise) | State-aware check: mean shifts meaningfully between states |
| `event_spike` | A reading that's boring almost the entire time, except for one or two one-time events — like a light sensor recording a single moment someone flips the light switch off. | Flat baseline + a list of one-off events at fixed times | Rare-but-large sample-to-sample jumps; or a column with 2-3 discrete levels that switches rarely |
| `periodic_motion` | Something that swings back and forth over and over, but never quite the same way twice — like someone waving an arm loosely, not on a strict mechanical beat. | Resting value + procedural repeated excursions (no fixed shape) | Fallback of `cycle_template` when a clean waveform can't be extracted |
| `cycle_template` | Something that repeats the exact same motion over and over, precisely — like a robotic joint doing one scripted movement on a loop. | Resting value + a REAL repeating waveform shape, replayed with jitter | Periodicity detected AND ≥5 clean cycles could be extracted |
| `sinusoidal_drift` | A reading that rises and falls once every 24 hours, like clockwork — outdoor temperature over day and night. | Smooth 24h day/night sine wave + noise | Column shows a clear day/night reversal over ≥18h of data |
| `derived_rolling_std` | Not a real sensor reading at all — it's a number calculated from how "shaky" another sensor has been over the last few seconds, so it's generated FROM that sensor instead of on its own. | Computed from another (already-generated) column, not generated independently | Column name contains "rolling" and correlates >0.8 with an acceleration channel's rolling std |
| `envelope_noise` | How "jumpy" a reading looks switches between calm and noisy on a repeating schedule. Built and ready to use, just not something the automatic fitting step currently reaches for on its own. | Noise amplitude alternates low/high on its own period | **Never auto-picked** — implemented, usable in a hand-written config, but no fitter path selects it |

Routing order in `_fit_column` (first match wins): stable/pressure-like →
static → derived-rolling → few-level event → day/night sinusoidal → trending
→ state-aware cycling → periodic → event spikes → constant-noise default.

---

## `ConstantNoiseEngine` → `"constant_noise"`

**Job:** hold a flat baseline and add Gaussian noise. Three optional
behaviors layer on top: a different noise level per state
(`noise_std_by_state`, e.g. quieter when the compressor is OFF), a
"stickiness" probability of just repeating the previous sample instead of
drawing a new one (mimics a sensor that holds a reading for a while, then
steps), and a noise *ramp* that grows or shrinks across a phase.

**Auto-picked:**
- Default fallback when nothing more specific matches.
- Genuinely static columns (relative std < 1e-4) — fixed at `stickiness=0.99`.
- Columns that are mostly held flat with rare small steps (consecutive-equal
  fraction > 0.7) — noise size is then measured from the real step sizes
  (nonzero diffs), not the raw global std, otherwise the synthetic version
  either freezes solid or steps far too often. (Found via aquarium
  `orientation_x`, robot-arm `acceleration_x`.)
- `_fit_state_aware`'s fallback: noise level differs by state (ratio > 1.5)
  but the *mean* doesn't move enough to count as `cycling`.

**Real example:** a mounted axis that's essentially motionless (aquarium
`orientation_x`), background acceleration noise on a resting axis.

---

## `GradualCurveEngine` → `"gradual_curve"`

**Job:** two distinct modes selected by shape, not by user choice.
*Settle-then-plateau*: value moves from a start toward a measured target at a
measured rate (from actual settle time, not `total_change / full_duration` —
that formula was wrong for any signal that plateaus early, see git history).
*Pure drift*: no plateau exists, so the value keeps moving at a constant
slope with a common-sense floor/ceiling clamp (used for a multi-day pressure
fall, for example). Extra features: per-state targets/rates (temperature
"breathing" with the compressor cycle), stickiness + quantization for
stair-step columns (integer-valued humidity), and Ornstein-Uhlenbeck
correlated wander noise on top of the trend.

**Auto-picked:** `_is_trending` — the net change from start to end is large
relative to the noise floor (environmental columns use a lower threshold
since they settle faster than they drift).

**Real example:** fridge temperature warm-up + per-cycle wobble, humidity
settle-then-flat, aquarium/fridge pressure's slow multi-hour fall.

**Known limits:** the settle shape is a straight ramp + stair-steps, not an
exponential — the plateau level/timing is right, the early shape is
slightly straighter than real sensors. A linear-trend extrapolation (used
for regime prediction) overshoots if the real growth decelerates.

---

## `CyclingEngine` → `"cycling"`

**Job:** the value sits at a genuinely different LEVEL depending on the
active state — not just different noise, a different mean. Each state gets
its own level and noise std, with an optional within-phase ramp (the value
climbing across a phase) and an optional per-segment level offset drawn once
per contiguous run of a state (a pose plateaus *within* one occurrence but
varies a bit between repeats of the same pose — added for dog-robot data).

**Auto-picked:** `_fit_state_aware` when `mean_shift > 0.5 * pooled_std` —
the state change visibly moves the average, not just the spread.

**Real example:** fridge `rolling_std` level ON vs OFF, light level per
dog-robot activity label.

---

## `EventSpikeEngine` → `"event_spike"`

**Job:** flat baseline most of the time, punctuated by a fixed list of
one-off events, each with a shape (`decaying` / `impulse` / `sustained`), a
magnitude, and an optional permanent level shift afterward. A dedicated
sub-path (`_fit_level_event`) handles columns that just sit on 2-3 discrete
values and switch rarely (≤5 times) — these get zero-magnitude events that
are pure level shifts (e.g. a room light switching off once).

**Auto-picked:** `_has_events` — a small fraction (0.01%-5%) of
sample-to-sample jumps are much larger than the median jump. Or the
few-level/rare-switch check above, which runs earlier and takes priority.

**Real example:** fridge `light` (one switch), a magnetometer axis with a
handful of sharp real disturbances.

**Known limit — important:** events are stored at FIXED absolute timestamps
taken from the original fit recording. If `--duration` extends generation
well past the fitted length, everything past the last scheduled event just
holds flat baseline + noise — the event structure does not repeat or
extrapolate. Confirmed on the robot-arm magnetometer columns: fit on ~10 min,
generated 60 min, and the last ~50 min (83% of the file) has no spike
structure at all. Fine if you only generate near the fitted duration; not
fine for long extrapolation of an event-heavy column.

---

## `PeriodicMotionEngine` → `"periodic_motion"`

**Job:** models "resting most of the time, with repeated excursions to
extremes" *without* needing a clean, copyable waveform shape. Each
excursion is drawn procedurally: motion duration, rest duration, period
jitter, a resting-vs-moving noise split, and an optional quaternion-flip
mode.

**Auto-picked:** it's the fallback inside `_fit_cycle_template` — used when
the periodicity check passes but fewer than 5 clean cycle templates could be
extracted from the real data (the motion is periodic-ish but too irregular
to copy a shape from).

**Known limit:** the periodicity DETECTOR that routes here
(`_is_periodic_motion`, a zero-crossing-regularity heuristic with a fairly
loose threshold) can false-positive on a one-off, multi-wiggle recovery
transient that isn't actually periodic — fabricating a repeating cycle that
does not exist in the source data. Found on gas-sensor R5/R6 (a one-time
shock-recovery wiggle got rendered as ~7 evenly-spaced oscillations over an
hour). Not fixed — a real fix needs an actual periodicity test
(autocorrelation peak / periodogram), not a tighter threshold, and the
detector is load-bearing for robot-arm's genuinely periodic columns so it
wasn't touched casually.

---

## `SinusoidalDriftEngine` → `"sinusoidal_drift"`

**Job:** a smooth 24-hour sine wave plus noise, with peak/trough timing
derived from where the extreme actually falls in the recording (not
assumed).

**Auto-picked:** `_has_reversal` — the column shows a clear U-shape (cold
trough) or ∩-shape (warm peak) in the middle of the recording, offset from
both endpoints, over **≥18 hours** of data. Shorter windows can't
distinguish a true daily cycle from an ordinary settle-then-plateau curve.

**Known limit / bug (found 2026-08-10):** despite the ≥18h guard above, this
engine IS assigned to `pressure` in the fridge configs (`fridge_fit60`,
`fridge_10pct`, `fridge_25pct`) and to `temperature` / `humidity` / `pressure`
in `aquarium_03`, on windows of only ~0.5–3h — far short of 18h. On such a short
window a 24h sine (`daily_period_s = 86400`) is fitted across less than a quarter
of its own period, so the output is a degenerate monotone curve, not a real
diurnal cycle. This directly contradicts the "needs ≥18h / not yet triggered"
description above: either the `_has_reversal` ≥18h guard leaks, or another
routing path reaches this engine before the guard runs. Both are bugs — **under
investigation**. Surfaced via the fridge deck config `fridge_fit60.json::pressure`
(~3h window). Do NOT present `sinusoidal_drift` as a working feature until the
routing is fixed; it currently produces a degenerate quarter-cycle fit.

---

## `CycleTemplateEngine` → `"cycle_template"`

**Job:** the strongest engine for periodic signals — it extracts the ACTUAL
repeating waveform shape from the real data (normalizes several real cycles
to a fixed-length template), then replays randomly-picked templates with
period/amplitude jitter, instead of describing the cycle statistically.

**Auto-picked:** `_is_periodic_motion` passes and at least 5 clean cycle
templates could be extracted (otherwise falls back to `periodic_motion`
above).

**Real example:** robot-arm joint orientation and acceleration — this is
the engine behind the strong real-vs-synthetic orientation match shown in
the presentation deck (`ppt/arm_robot/xdk*_orientation*.png`), including
that the match holds at both the start and the end of a run, because a
template gets redrawn every cycle rather than events running out.

---

## `derived_rolling_std` (special-cased, not a class)

**Job:** for a column whose name contains "rolling" and correlates strongly
(> 0.8) with the rolling standard deviation of an acceleration channel,
don't fit it as an independent signal at all — literally compute it from
the already-generated synthetic acceleration column, using the window
length, floor value, and update-and-hold cadence measured from the real
column. Runs as a deferred step after every other column has been
generated, since it needs its source column to already exist.

**Auto-picked:** `_fit_derived_rolling`, checked early for any column whose
name contains "rolling".

**Why it exists:** the real `rolling_std` column is a firmware-computed
statistic — smooth, strongly autocorrelated (real lag-1 autocorr ≈ 0.998).
Fitting it as independent per-sample noise destroyed exactly that texture
(it's what a forecasting model needs); TSTR/TRTR on it went from 1.31 →
0.81 ("synthetic is a strong training substitute") after this fix.

---

## `EnvelopeNoiseEngine` → `"envelope_noise"` (dormant)

**Job:** alternates a column's noise AMPLITUDE (not level) between a low and
a high value on its own period + duty cycle, independent of the shared
rhythm/state machine.

**Status:** fully implemented and buildable from a hand-written config, but
no `_fit_*` function in `AutoFitter` ever returns this engine — it's dead
code from the fitter's perspective. Not a bug, just worth knowing it exists
if you're hand-authoring a config and want simple ON/OFF noise cycling
without the full state-machine machinery.

---

## The state machine (not a column engine, but what most of them consult)

Most engines above read a `state` (e.g. `phase_on` / `phase_off`) at each
timestamp from a shared `StateMachine`, which runs in one of three modes:

- **Rhythm mode** (fridge, robot arm, aquarium): alternates two named phases,
  with each phase's duration drawn from a distribution measured from real
  data — median + MAD after dropping short chatter fragments, not a plain
  mean/std (a single long outlier or a handful of flicker fragments used to
  blow the fitted spread up to the point that the synthetic rhythm looked
  random; see `_detect_rhythm_on_column`).
- **Semi-Markov / label-driven mode** (dog robot): states are real activity
  labels from a labels CSV. Each label's duration and a label→label
  transition matrix are fit from the data, and generation *invents a new
  plausible sequence* of activities — it does not replay the recorded
  schedule.
- **Anomaly overrides**: `power_off` truncates the running phase, holds OFF
  for a specified window, and restarts at ON when power returns (all columns
  render ordinary fitted OFF behavior during the outage — nothing is
  injected). Template anomalies (`overheat`, `dropout`, `vibration_spike`)
  multiply target/noise parameters for affected columns instead.

**Gated logging:** if the fitted device stops recording while idle (a large
share of the recording is long timestamp gaps), the generator reproduces
that — dropping OFF-phase rows except a short lead/tail around each
transition — rather than emitting continuous rows the real device never
would have.

## `SensorRealism` (post-processing layer, applied after any engine)

Every column's raw generated values pass through: **quantization** (round to
the sensor's real step size, if one was detected/validated against the data
— see the "quant step validation" note below), **clipping** (stay within the
observed min/max — critical for bounded values like quaternion components),
and **settling noise** (extra noise injected only in the first few samples,
mimicking sensor warm-up).

**Quant-step validation:** a handful of quantization steps are hardcoded by
column NAME for XDK's raw units (`temperature`→10, `humidity`→1,
`pressure`→1, `light`→2880). These are only safe for XDK's large-magnitude
raw values. Any dataset reporting the same column names in plain physical
units (e.g. gas-sensor temperature ~26.5°C) would get rounded to nonsense by
these defaults, so `_get_realism` validates every hardcoded step against the
actual data (`_quant_step_fits_data`) before applying it, and drops it if the
data resolves finer than the claimed grid.

---

## Known architecture gaps (measured — see PHYSICS_REPORT.md for numbers)

Status legend: **OPEN** = not addressed; **PARTIAL (flag)** = a fix exists behind
a config flag, default OFF (deck reproduces the old behavior).

- **Columns are fit and generated fully independently.** [**OPEN**] No cross-column
  noise correlation. Real `mag_x/y/z` and `accel_x/y/z` are correlated (~0.4–0.6,
  e.g. aquarium mag mx–my 0.623, accel ax–ay 0.412); synthetic comes out ~0.00.
  Orientation axes are worse: arm real qx–qz ±0.98–0.99 → syn ~0.0. Anything derived
  from a combination of axes (vector magnitude, quaternion norm) won't match. Targeted
  by the planned Cholesky-correlated-noise phase.
- **Quaternion validity `s = x²+y²+z² ≤ 1`.** [**PARTIAL (flag)** —
  `physics.enforce_quaternion_norm`, default OFF] Independent generation pushed arm
  joint-1 synthetic off the unit sphere: **4.9% of samples s>1, max s = 1.70** (not a
  rotation at all). With the flag ON, a cross-column renormalization runs after
  clipping and brings **max s → 1.000 and real violations (s>1.001) → 0%**, with no
  marginal-quality cost (orientation KS/Wasserstein change ≤ 0.001, one column
  improves). **It does NOT fix gravity consistency** (34.9° → 35.9°, unchanged): a
  valid quaternion is still unrelated to the independently-generated accel — that is
  the separate gravity-derivation gap below.
- **Gravity component of accel is generated independently of orientation.** [**OPEN**]
  On moving joints the accel direction does not match the gravity implied by the
  quaternion: median angle error **arm j1 36°, j3 28° vs real ~0.3–1°**; synthetic
  joint-1 also produces angular speeds of **~720°/s (16× real p99)** — physically
  impossible for the arm. Targeted by the planned derive-gravity-from-orientation
  phase (same deferred slot as `derived_rolling_std`).
- **No engine models "shock, then slow asymmetric multi-hour recovery."**
  Found via the gas-sensor (HT_Sensor) dataset: columns with that shape get
  routed to `constant_noise` (losing all structure) or falsely to
  `periodic_motion` (fabricating cycles that don't exist). This needs a new
  engine, not a parameter tweak.
- **`event_spike` doesn't extrapolate beyond the fit window** (see above) —
  matters for any event-heavy column if you generate much longer than the
  original recording.
