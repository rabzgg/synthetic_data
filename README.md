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
steps, and within-phase amplitude ramps. The output is a human-editable JSON.

**2. Generate synthetic data:**

```bash
python3 main.py \
    --config configs/my_domain.json \
    --output out/my_domain_synthetic.csv \
    --duration 86400
```

`--duration` may exceed the fitted duration: cycles are drawn from the fitted
distributions, not replayed, so extrapolation does not repeat the source.

**3. Evaluate against real data:**

```bash
# distribution + texture similarity (Wasserstein, KS, increments, ACF)
python3 stat_eval.py --real real.csv --syn synthetic.csv --cols acceleration_z rolling_std

# utility: Train-on-Synthetic-Test-on-Real vs Train-on-Real
python3 tstr_eval.py --real real.csv --syn synthetic.csv --col rolling_std
```

TSTR/TRTR ratio below ~1.1 means the synthetic data is a valid training
substitute. Note: KS on quantized columns (e.g. an accelerometer that only
outputs 0.9/1.0) is only meaningful after rounding to ~4 decimals.

## Layout

```
core/generator.py   the library: TimestampGenerator, StateMachine,
                    column engines, SensorRealism, SyntheticXDKGenerator,
                    AutoFitter
main.py             CLI: config -> synthetic CSV
extract_config.py   CLI: real CSV -> config
stat_eval.py        statistical similarity evaluation
tstr_eval.py        TSTR utility evaluation
out/                generated CSVs (created at runtime, not tracked)
```

## Known limitations

- Amplitude parameters are static per config: a non-stationary session
  (e.g. a compressor working progressively harder) is averaged, so a config
  fitted on an early window under-estimates a later regime.
- Fitted linear drifts (pressure) do not saturate; very long extrapolations
  can exceed the physical range.
- The fitting window must contain >= 3 steady-state ON/OFF cycles for rhythm
  detection.
