"""
main.py — generate synthetic data from a scenario config JSON.

Usage
-----
python3 main.py --config configs/robot_arm/idle.json --output out/idle_synthetic.csv

Optional flags
--------------
--duration      override duration_s (seconds)
--seed          random seed (default: 42)
--season        summer | winter | spring | autumn | indoor_warm
--start-time    starting local time HH:MM (affects daily sine phase), e.g. 08:00
--indoor        dampen seasonal amplitude (room is air-conditioned)
--light-on      time-of-day when light turns ON  HH:MM, e.g. 06:00
--light-off     time-of-day when light turns OFF HH:MM, e.g. 17:00
--anomaly       one or more anomaly specs: t_start:t_end:type
                e.g. --anomaly 1200:1500:overheat --anomaly 2000:2100:vibration_spike
                supported types: overheat, dropout, vibration_spike
                t_end is optional: 1200::overheat means anomaly from t=1200 to end

Example (24h equatorial aquarium)
-----------------------------------
python3 main.py \\
    --config configs/aquarium/sensor_03.json \\
    --output out/aquarium_24h.csv \\
    --duration 86400 \\
    --season equatorial \\
    --start-time 23:00 \\
    --light-on 06:00 \\
    --light-off 17:00
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from core.generator import SyntheticXDKGenerator, SEASON_PRESETS, INDOOR_DAMPING, ANOMALY_TEMPLATES

parser = argparse.ArgumentParser(description="Generate synthetic XDK data from a config JSON.")
parser.add_argument("--config",      required=True,            help="Path to scenario JSON config")
parser.add_argument("--output",      required=True,            help="Path to output CSV")
parser.add_argument("--duration",    type=float, default=None, help="Override duration_s (seconds)")
parser.add_argument("--seed",        type=int,   default=42,   help="Random seed (default: 42)")
parser.add_argument("--season",      default=None,             choices=list(SEASON_PRESETS.keys()),
                                                               help="Season context for temp/humidity")
parser.add_argument("--start-time",  default="08:00",          help="Local start time HH:MM (default: 08:00)")
parser.add_argument("--indoor",          action="store_true",  help="Dampen seasonal swing (AC environment)")
parser.add_argument("--no-season-temp",  action="store_true",  help="Apply season to humidity only, not temperature (e.g. aquarium with heater)")
parser.add_argument("--light-on",    default=None,             help="Time light turns ON  HH:MM (e.g. 06:00)")
parser.add_argument("--light-off",   default=None,             help="Time light turns OFF HH:MM (e.g. 17:00)")
parser.add_argument("--light-peak",  type=float, default=None, help="Peak light level at full brightness (e.g. 11520). Generates quantized ramp steps at sunrise.")
parser.add_argument("--anomaly",     action="append",          default=[],
                                                               help="Anomaly spec t_start:t_end:type (repeatable)")
args = parser.parse_args()

if not os.path.exists(args.config):
    print(f"Error: config not found: {args.config}")
    sys.exit(1)

with open(args.config) as f:
    scenario = json.load(f)

if args.duration:
    scenario["duration_s"] = args.duration

# ── Build environment config ──────────────────────────────────
environment_config = {}
if args.season:
    preset = dict(SEASON_PRESETS[args.season])
    if args.indoor:
        preset["amp_temp"] *= INDOOR_DAMPING
        preset["amp_hum"]  *= INDOOR_DAMPING
    # Convert start-time to phase offset in seconds
    try:
        h, m = map(int, args.start_time.split(":"))
    except ValueError:
        print(f"Error: --start-time must be HH:MM, got: {args.start_time}")
        sys.exit(1)
    start_of_day_s = h * 3600 + m * 60
    # Sine peaks at 14:00 → offset so that start_of_day lands at the right phase
    preset["phase_offset_s"] = start_of_day_s
    environment_config = preset

# ── Inject day/night light schedule ──────────────────────────
if args.light_on and args.light_off:
    def _parse_hhmm(s, label):
        try:
            h, m = map(int, s.split(":"))
            return h * 3600 + m * 60
        except ValueError:
            print(f"Error: {label} must be HH:MM, got: {s}")
            sys.exit(1)

    light_on_s  = _parse_hhmm(args.light_on,  "--light-on")
    light_off_s = _parse_hhmm(args.light_off, "--light-off")

    try:
        h_st, m_st = map(int, args.start_time.split(":"))
    except ValueError:
        print(f"Error: --start-time must be HH:MM, got: {args.start_time}")
        sys.exit(1)
    rec_start_s = h_st * 3600 + m_st * 60

    # Recording-relative times of next light transition from rec_start
    t_on  = (light_on_s  - rec_start_s) % 86400
    t_off = (light_off_s - rec_start_s) % 86400

    # Is recording start within daytime? (light_on <= rec_start < light_off, non-wrapping day)
    if light_on_s < light_off_s:
        is_day_start = light_on_s <= rec_start_s < light_off_s
    else:  # wrapping night (e.g. on=20:00, off=06:00)
        is_day_start = not (light_off_s <= rec_start_s < light_on_s)

    # Detect daytime light level from fitted config (first "light" column)
    day_value = None
    for col_name, col_cfg in scenario.get("columns", {}).items():
        if "light" in col_name.lower():
            p = col_cfg.get("params", {})
            q_step = col_cfg.get("realism", {}).get("quantization_step", 0)
            if col_cfg["engine"] == "constant_noise":
                bv = p.get("base_value", 0)
                day_value = bv if bv > 0 else q_step
            elif col_cfg["engine"] == "gradual_curve":
                # initial_value is the light level at recording start (daytime)
                iv = p.get("initial_value", 0)
                day_value = iv if iv > 0 else q_step
            elif col_cfg["engine"] == "event_spike":
                bl = p.get("baseline", 0)
                if bl > 0:
                    day_value = bl
                else:
                    for ev in p.get("events", []):
                        if ev.get("level_shift", 0) > 0:
                            day_value = ev["level_shift"]
                            break
            if not day_value and q_step > 0:
                day_value = q_step
            break
    if not day_value:
        day_value = 2880  # fallback: one quantization step

    # Build chronological event list within [0, 86400)
    # If recording starts in daytime: first event is OFF (t_off), then ON (t_on)
    # If recording starts at night  : first event is ON  (t_on),  then OFF (t_off)
    # Build sunrise ramp: if --light-peak given, step up in q_step increments.
    # Otherwise single jump to day_value.
    q_step = float(day_value)  # one quantization step = day_value level
    peak_value = float(args.light_peak) if args.light_peak else float(day_value)
    n_steps = max(1, round(peak_value / q_step))
    ramp_spacing_s = 420.0  # 7 minutes between ramp steps

    def _sunrise_events(t_start):
        evs = []
        for i in range(n_steps):
            t = t_start + i * ramp_spacing_s
            evs.append((t, q_step))  # each step adds one q_step
        return evs

    def _sunset_event(t_start):
        return [(t_start, -peak_value)]  # single hard OFF

    if is_day_start:
        baseline = peak_value
        raw_events = _sunset_event(t_off) + _sunrise_events(t_on)
    else:
        baseline = 0.0
        raw_events = _sunrise_events(t_on) + _sunset_event(t_off)

    events = [
        {"t_start": t, "duration": 1.0, "magnitude": 0.0,
         "level_shift": shift, "type": "sustained"}
        for t, shift in raw_events
        if t < scenario["duration_s"]
    ]
    events.sort(key=lambda e: e["t_start"])

    light_schedule = {
        "engine": "event_spike",
        "params": {
            "baseline": baseline,
            "baseline_noise_std": 0.0,
            "events": events,
        },
        "realism": {"quantization_step": 2880, "clip_min": 0},
    }

    for col_name in list(scenario.get("columns", {}).keys()):
        if "light" in col_name.lower():
            scenario["columns"][col_name] = light_schedule
            state_label = "DAY" if is_day_start else "NIGHT"
            ev_summary = "  ".join(
                f"{'ON' if e['level_shift'] > 0 else 'OFF'} t={e['t_start']}s"
                for e in events
            )
            print(f"Light schedule : starts {state_label}  {ev_summary}  day_value={day_value:.0f}")
            break

# ── Parse anomaly specs ───────────────────────────────────────
anomaly_specs = []
valid_types = list(ANOMALY_TEMPLATES.keys())
for raw in args.anomaly:
    parts = raw.split(":")
    if len(parts) != 3:
        print(f"Error: --anomaly must be t_start:t_end:type, got: {raw}")
        sys.exit(1)
    t_start_str, t_end_str, atype = parts
    if atype not in valid_types:
        print(f"Error: unknown anomaly type '{atype}'. Valid: {valid_types}")
        sys.exit(1)
    try:
        t_start = float(t_start_str)
        t_end   = float(t_end_str) if t_end_str else None
    except ValueError:
        print(f"Error: t_start/t_end must be numbers, got: {raw}")
        sys.exit(1)
    anomaly_specs.append({"t_start": t_start, "t_end": t_end, "type": atype})

# ── Print summary ─────────────────────────────────────────────
print(f"Config       : {args.config}")
print(f"Domain       : {scenario.get('domain', '?')}")
print(f"Duration     : {scenario['duration_s']:.0f}s  ({scenario['duration_s']/60:.1f} min)")
print(f"Frequency    : {scenario['frequency_hz']} Hz")
if environment_config:
    indoor_tag = " (indoor)" if args.indoor else ""
    no_temp_tag = "  [temp unchanged — heater mode]" if args.no_season_temp else ""
    print(f"Season       : {args.season}{indoor_tag}  start={args.start_time}{no_temp_tag}")
    if not args.no_season_temp:
        print(f"  Temp base  : {environment_config['base_temp']:.1f}°C  ±{environment_config['amp_temp']:.1f}°C daily")
    print(f"  Hum  base  : {environment_config['base_hum']:.1f}%   ±{environment_config['amp_hum']:.1f}% daily")
if anomaly_specs:
    print(f"Anomalies    :")
    for sp in anomaly_specs:
        t_end_str = f"{sp['t_end']}s" if sp['t_end'] else "end"
        print(f"  [{sp['t_start']}s → {t_end_str}]  type={sp['type']}")

# ── Generate ──────────────────────────────────────────────────
os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
gen = SyntheticXDKGenerator(
    scenario,
    seed=args.seed,
    environment_config=environment_config,
    anomaly_specs=anomaly_specs,
    no_season_temp=args.no_season_temp,
)
df = gen.generate()
df.to_csv(args.output, index=False)

print(f"\nGenerated {len(df)} rows → {args.output}")
