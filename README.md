# XDK Synthetic Data Generator

Self-contained library for generating synthetic XDK sensor data (CSV) that
reproduces the statistical properties, temporal patterns, and hardware
quirks (quantization, logging gaps, settling) of real XDK recordings.

Companion to the report *"Synthetic Data Generator: From Pipeline Validation
to Generalization Testing"* — every experiment in that report is a runnable
script in this folder.

## Install

Python >= 3.10.

```bash
pip install -r requirements.txt
```

## Quickstart

```bash
bash run_fridge.sh        # fit from real fridge data -> generate 5.7h synthetic
```

Outputs land in `out/`, fitted configs in `configs/`.

## Workflow

```
real CSV --(extract_config.py)--> config JSON --(main.py)--> synthetic CSV
                                       ^
                        editable: duration, anomalies, params
```

1. **Fit**: `python3 extract_config.py --csv data/fridge/... --output configs/my.json --domain fridge`
   The AutoFitter detects sampling rate, compressor rhythm (Otsu on rolling
   std), gated logging (device stops recording while idle), per-column engine
   type, quantization, and within-phase ramps.
2. **Generate**: `python3 main.py --config configs/my.json --output out/my.csv --duration 86400`
   `--duration` can exceed the fitted duration; cycles are drawn from the
   fitted distributions, not replayed.
3. **Evaluate**: see *Evaluation tools* below.

## Experiment scripts (map to the report)

| Script | Report section | What it does |
|---|---|---|
| `run_fridge.sh` | II (validation) | Fit full session, generate same duration |
| `run_fridge_24h.sh` | III, Test A+B | Fit full + 25% windows, generate 24 h each, compare vs real |
| `run_fridge_holdout.sh` | III, Test C | Fit first 60%, evaluate against unseen last 40% (structure + stats + TSTR) |
| `run_robot_arm.sh` | — | Robot-arm domain (periodic joint motion) |
| `run_aquarium.sh` | — | Aquarium domain (constant pump vibration) |

## Evaluation tools

| Tool | Question it answers |
|---|---|
| `compare_fridge.py` | Does the duty cycle / gap structure / level distribution match? (`--syn label=path.csv`, repeatable) |
| `stat_eval.py` | Do value/increment distributions and autocorrelation match? (Wasserstein, KS, ACF) |
| `tstr_eval.py` | Is it useful for training? Train-on-Synthetic-Test-on-Real vs Train-on-Real (ratio < ~1.1 = synthetic is a valid substitute) |

Note: KS on quantized columns (e.g. `acceleration_z`, only 0.9/1.0) is only
meaningful after rounding to ~4 decimals; `compare_fridge.py` does this
internally, `stat_eval.py` reports raw KS.

## Layout

```
core/generator.py   the library: TimestampGenerator, StateMachine, engines,
                    SensorRealism, SyntheticXDKGenerator, AutoFitter
main.py             CLI: config -> synthetic CSV
extract_config.py   CLI: real CSV -> config
data/               input recordings (fridge / aquarium / robot_arm)
configs/            fitted configs (JSON, human-editable)
out/                generated CSVs (created at runtime, not shipped)
```

## Known limitations (see report, Sec. IV-V)

- Amplitude parameters are static per config: a non-stationary session
  (compressor working harder over time) is averaged, so a config fitted on an
  early window under-estimates a later regime.
- Fitted linear drifts (pressure) do not saturate; long extrapolations can
  exceed the physical range.
- The fitting window must contain >= 3 steady-state ON/OFF cycles.
