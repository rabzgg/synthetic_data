# XDK Synthetic Data Generator

Core framework for generating synthetic XDK sensor data (CSV) that reproduces
the statistical properties, temporal patterns, and hardware quirks
(quantization, logging gaps, settling) of real XDK recordings.

## Install

Python >= 3.10.

```bash
pip install -r requirements.txt
```

## Workflow

```
real CSV --(extract_config.py)--> config JSON --(main.py)--> synthetic CSV
                                       ^
                        editable: duration, anomalies, params
```

**1. Fit a config from a real recording:**

```bash
python3 extract_config.py \
    --csv path/to/real_recording.csv \
    --output configs/my_domain.json \
    --domain my_domain
```

The AutoFitter detects sampling rate and jitter, ON/OFF rhythm (Otsu
thresholding on rolling std of the acceleration channels), gated logging
(device stops recording while idle), a per-column engine type, quantization
steps, and within-phase amplitude ramps. Phase durations are summarized with
outlier-proof statistics (fragment filter + median/MAD), trending columns
(temperature warm-up) get their rate from the measured settle time, and
columns that sit on a few discrete levels and switch rarely (a room light
turning off once) are fitted as constant + level-shift events. The output is
a human-editable JSON.

**2. Generate synthetic data:**

```bash
python3 main.py \
    --config configs/my_domain.json \
    --output out/my_domain_synthetic.csv \
    --duration 86400 \
    --seed 42
```

`--duration` may exceed the fitted duration: cycles are drawn from the fitted
distributions, not replayed, so extrapolation does not repeat the source.
Same seed = identical output; change `--seed` for a new realization.

**2b. Inject anomalies (optional, repeatable):**

```bash
python3 main.py --config configs/my_domain.json --output out/anomalous.csv \
    --duration 20574 \
    --anomaly 18588:19182:power_off \
    --anomaly 2000:2100:vibration_spike
```

Spec is `t_start:t_end:type` in seconds; leave `t_end` empty
(`18588::power_off`) to run the anomaly to the end. Types:

- `power_off` — appliance loses power: the running ON phase is truncated,
  the rhythm holds OFF for the window (all columns render their normal
  fitted OFF behavior — values do NOT freeze), and on power restore the
  rhythm restarts with an ON phase (thermostat behavior). Validated against
  a real unplug/re-plug event.
- `overheat`, `dropout`, `vibration_spike` — per-column template anomalies
  (value/noise multipliers).

An anomaly run consumes the random stream identically to a normal run with
the same seed, so both are byte-identical before `t_start` — matched
normal/anomalous pairs for training and evaluating detectors.


## Layout

```
core/generator.py   the library: TimestampGenerator, StateMachine,
                    column engines, SensorRealism, SyntheticXDKGenerator,
                    AutoFitter
main.py             CLI: config -> synthetic CSV
extract_config.py   CLI: real CSV -> config
out/                generated CSVs (created at runtime, not tracked)
```

## Known limitations

- Amplitude parameters are static per config: a non-stationary session
  (e.g. a compressor working progressively harder) is averaged, so a config
  fitted on an early window under-estimates a later regime.
- Fitted linear drifts (pressure) do not saturate; very long extrapolations
  can exceed the physical range.
- The fitting window must contain >= 3 steady-state ON/OFF cycles for rhythm
  detection, and must reach steady state for trending columns (otherwise the
  fitted plateau is anchored wherever the window happened to end).
- Settle curves are reproduced as a linear ramp + stair-steps, not an
  exponential; the plateau level and timing are correct, the early shape is
  slightly straighter than real.
- Session-anchored events (warm-up, a light switching off) happen at their
  fitted second once per run; they do not repeat on a daily schedule unless
  configured via `--light-on/--light-off`.
- Measured ON durations include the low-vibration lead/tail around each
  burst, slightly over-counting duty (~90 s per cycle).
