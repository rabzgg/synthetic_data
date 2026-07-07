import numpy as np
import pandas as pd # type: ignore
from dataclasses import dataclass, field
from typing import Optional
import json
import copy
from scipy.signal import argrelmax # type: ignore

# ─────────────────────────────────────────────────────────────
# ENVIRONMENT PRESETS
# Keys: season → column → (base, daily_amplitude, humidity_inverse)
# temp/humidity values are in the same unit as the sensor output
# (raw XDK units: temperature in millidegrees-ish, ~24000 = 24°C × 1000)
# ─────────────────────────────────────────────────────────────
SEASON_PRESETS = {
    #              base_temp  amp_temp  base_hum  amp_hum
    "summer":      dict(base_temp=30.0, amp_temp=4.0,  base_hum=70.0, amp_hum=8.0),
    "winter":      dict(base_temp=8.0,  amp_temp=3.0,  base_hum=30.0, amp_hum=5.0),
    "spring":      dict(base_temp=18.0, amp_temp=4.0,  base_hum=60.0, amp_hum=6.0),
    "autumn":      dict(base_temp=15.0, amp_temp=3.5,  base_hum=55.0, amp_hum=6.0),
    # Indoor heated room (aquarium, lab, office): stable temp regardless of outdoor season
    "indoor_warm": dict(base_temp=25.5, amp_temp=2.5,  base_hum=60.0, amp_hum=4.0),
}

INDOOR_DAMPING = 0.35   # indoor AC damps seasonal swing to 35% of outdoor

# ─────────────────────────────────────────────────────────────
# ANOMALY TEMPLATES
# Define what each named anomaly does per column category.
# Categories: "temperature", "humidity", "pressure", "light",
#             "acceleration", "orientation", "magnetic"
# ─────────────────────────────────────────────────────────────
ANOMALY_TEMPLATES = {
    "overheat": {
        # sensor internal heat spike: temp shoots up, everything else noisy
        "temperature":   dict(target_multiplier=2.5, rate_multiplier=15.0, noise_multiplier=4.0),
        "humidity":      dict(target_multiplier=0.6, rate_multiplier=3.0,  noise_multiplier=2.0),
        "acceleration":  dict(noise_multiplier=3.0),
        "orientation":   dict(noise_multiplier=2.0),
        "magnetic":      dict(noise_multiplier=2.5),
        "pressure":      dict(noise_multiplier=1.5),
        "light":         dict(noise_multiplier=1.0),
    },
    "dropout": {
        # sensor dropout: values freeze or go near-zero
        "temperature":   dict(target_multiplier=0.0, rate_multiplier=0.0, noise_multiplier=0.1),
        "humidity":      dict(target_multiplier=0.0, rate_multiplier=0.0, noise_multiplier=0.1),
        "acceleration":  dict(noise_multiplier=0.05),
        "orientation":   dict(noise_multiplier=0.05),
        "magnetic":      dict(noise_multiplier=0.05),
        "pressure":      dict(noise_multiplier=0.05),
        "light":         dict(noise_multiplier=0.05),
    },
    "vibration_spike": {
        # mechanical vibration: acceleration/orientation go wild, env sensors unaffected
        "acceleration":  dict(noise_multiplier=8.0),
        "orientation":   dict(noise_multiplier=6.0),
        "magnetic":      dict(noise_multiplier=3.0),
        "temperature":   dict(noise_multiplier=1.0),
        "humidity":      dict(noise_multiplier=1.0),
        "pressure":      dict(noise_multiplier=1.0),
        "light":         dict(noise_multiplier=1.0),
    },
}

def _col_category(col_name: str) -> str:
    """Map column name to anomaly template category."""
    col = col_name.lower()
    if "temp" in col:            return "temperature"
    if "hum" in col:             return "humidity"
    if "press" in col:           return "pressure"
    if "light" in col:           return "light"
    if "accel" in col:           return "acceleration"
    if "orient" in col:          return "orientation"
    if "mag" in col:             return "magnetic"
    return "other"

# COMPONENT 1: TIMESTAMP GENERATOR

class TimestampGenerator:
    def __init__(self, frequency_hz: float, duration_s: float,
                 jitter_std_ms: float = 2.0,
                 gap_probability: float = 0.0002,
                 gap_max_factor: float = 10.0,
                 start_timestamp_ms: float = 20000.0):
        self.interval_ms = 1000.0 / frequency_hz
        self.duration_s = duration_s
        self.jitter_std_ms = jitter_std_ms
        self.gap_probability = gap_probability
        self.gap_max_factor = gap_max_factor
        self.start_timestamp_ms = start_timestamp_ms

    def generate(self, rng: np.random.Generator) -> np.ndarray:
        n_samples = int(self.duration_s * 1000 / self.interval_ms)
        intervals = np.full(n_samples, self.interval_ms)

        # Add jitter
        jitter = rng.normal(0, self.jitter_std_ms, n_samples)
        intervals += jitter

        # Inject occasional gaps
        gap_mask = rng.random(n_samples) < self.gap_probability
        gap_sizes = rng.uniform(3, self.gap_max_factor, n_samples) * self.interval_ms
        intervals[gap_mask] = gap_sizes[gap_mask]

        # Ensure no negative intervals
        intervals = np.maximum(intervals, self.interval_ms * 0.5)

        timestamps = np.cumsum(intervals)
        timestamps = self.start_timestamp_ms + timestamps
        return timestamps

# COMPONENT 2: STATE MACHINE

class StateMachine:

    def __init__(self, rhythm_config: Optional[dict] = None,
                 anomaly_schedule: list = None):
        self.rhythm_config = rhythm_config
        self.anomaly_schedule = anomaly_schedule or []

    def resolve_states(self, timestamps: np.ndarray,
                       rng: np.random.Generator) -> list[dict]:

        t_start = timestamps[0]
        t_seconds = (timestamps - t_start) / 1000.0
        micro_states = self._build_rhythm_timeline(t_seconds, rng)

        states = []
        for i, t in enumerate(t_seconds):
            macro = "normal"
            for anomaly in self.anomaly_schedule:
                a_start = anomaly["t_start"]
                a_end = anomaly.get("t_end")
                if t >= a_start and (a_end is None or t < a_end):
                    macro = anomaly["state"]
                    break

            micro = None
            if macro == "normal" and micro_states is not None:
                micro = micro_states[i]

            states.append({"macro": macro, "micro": micro})

        return states

    def _build_rhythm_timeline(self, t_seconds: np.ndarray,
                               rng: np.random.Generator) -> Optional[list]:
        if self.rhythm_config is None:
            return None

        phases = self.rhythm_config["phases"]
        total_duration = t_seconds[-1]
        timeline = []
        current_time = 0.0
        phase_idx = 0

        # Pre-generate phase sequence covering entire duration
        phase_segments = []
        while current_time < total_duration:
            phase = phases[phase_idx % len(phases)]
            duration = max(10, rng.normal(phase["duration_mean"],
                                          phase["duration_std"]))
            phase_segments.append({
                "name": phase["name"],
                "start": current_time,
                "end": current_time + duration
            })
            current_time += duration
            phase_idx += 1

        seg_idx = 0
        for t in t_seconds:
            while (seg_idx < len(phase_segments) - 1 and
                   t >= phase_segments[seg_idx]["end"]):
                seg_idx += 1
            timeline.append(phase_segments[seg_idx]["name"])

        return timeline

# COMPONENT 3: COLUMN ENGINES

def _segment_progress(states: list[dict]) -> np.ndarray:
    """
    For each sample, the 0..1 progress through its contiguous run of equal
    (micro or macro) state. Lets engines ramp a value across a phase (e.g.
    compressor vibration builds up over an ON cycle instead of being flat).
    """
    n = len(states)
    keys = [s["micro"] or s["macro"] for s in states]
    progress = np.zeros(n)
    start = 0
    for i in range(1, n + 1):
        if i == n or keys[i] != keys[start]:
            seg_len = i - start
            if seg_len > 1:
                progress[start:i] = np.arange(seg_len) / (seg_len - 1)
            start = i
    return progress


class ConstantNoiseEngine:

    def __init__(self, base_value: float,
                 noise_std_by_state: dict[str, float],
                 default_noise_std: float = 0.001,
                 stickiness: float = 0.0,
                 noise_ramp_by_state: dict[str, float] = None):
        self.base_value = base_value
        self.noise_std_by_state = noise_std_by_state
        self.default_noise_std = default_noise_std
        self.stickiness = stickiness  # probability of copying previous value (XDK static behavior)
        # noise_ramp_by_state[state] = total std increase across one phase:
        # std(t) = std - span/2 + span * progress
        self.noise_ramp_by_state = noise_ramp_by_state or {}

    def generate(self, states: list[dict],
                 rng: np.random.Generator) -> np.ndarray:
        n = len(states)
        values = np.full(n, float(self.base_value))
        progress = _segment_progress(states) if self.noise_ramp_by_state else None

        for i, state in enumerate(states):
            if i > 0 and self.stickiness > 0 and rng.random() < self.stickiness:
                values[i] = values[i - 1]
                continue
            key = state["micro"] or state["macro"]
            std = self.noise_std_by_state.get(key, self.default_noise_std)
            span = self.noise_ramp_by_state.get(key, 0.0)
            if span and progress is not None:
                std = max(0.0, std + span * (progress[i] - 0.5))
            values[i] += rng.normal(0, std)

        return values


class GradualCurveEngine:

    def __init__(self, initial_value: float,
                 target_by_state: dict[str, float],
                 rate_by_state: dict[str, float],
                 noise_std: float = 5.0,
                 default_target: float = None,
                 default_rate: float = 0.001,
                 ou_noise_scale: float = 0.0,
                 ou_tau_s: float = 600.0,
                 stickiness: float = 0.0,
                 quantization_step: float = 0.0,
                 drift_slope: float = 0.0,
                 drift_floor: float = None,
                 drift_ceil: float = None):
        self.initial_value = initial_value
        self.target_by_state = target_by_state
        self.rate_by_state = rate_by_state
        self.noise_std = noise_std
        self.default_target = default_target or initial_value
        self.default_rate = default_rate
        # Ornstein-Uhlenbeck (correlated) noise: adds slow wander on top of trend.
        # ou_noise_scale = amplitude as fraction of noise_std; ou_tau_s = correlation time.
        self.ou_noise_scale = ou_noise_scale
        self.ou_tau_s = ou_tau_s
        # stickiness: probability of holding the previous emitted value (XDK sensor
        # holds a reading for long stretches, then steps). quantization_step: round
        # output to this grid (e.g. 1 for integer humidity) so trend appears as stairs.
        self.stickiness = stickiness
        self.quantization_step = quantization_step
        # drift mode: pure constant slope (units/sec) with NO plateau. Use for signals
        # that keep drifting (e.g. pressure falling over days). drift_floor / drift_ceil
        # are common-sense clamps so it never runs off to absurd values.
        self.drift_slope = drift_slope
        self.drift_floor = drift_floor
        self.drift_ceil = drift_ceil

    def generate(self, states: list[dict], timestamps: np.ndarray,
                 rng: np.random.Generator) -> np.ndarray:
        n = len(states)
        values = np.zeros(n)
        current = self.initial_value
        ou = 0.0  # OU process state
        last_emitted = None  # for stickiness

        q = self.quantization_step

        for i in range(n):
            if i == 0:
                dt = 0.0
            else:
                dt = (timestamps[i] - timestamps[i - 1]) / 1000.0

            key = states[i]["micro"] or states[i]["macro"]
            target = self.target_by_state.get(key, self.default_target)
            rate = self.rate_by_state.get(key, self.default_rate)

            if self.drift_slope != 0.0:
                # Pure drift: keep moving at constant slope, no plateau. Clamp to
                # common-sense bounds so it never runs off to absurd values.
                current = current + self.drift_slope * dt
                if self.drift_floor is not None and current < self.drift_floor:
                    current = self.drift_floor
                if self.drift_ceil is not None and current > self.drift_ceil:
                    current = self.drift_ceil
            else:
                # Linear drift toward target (NOT exponential — exponential melandai near
                # target and never looks like stairs; linear keeps a steady climb).
                if current < target:
                    current = min(target, current + rate * dt)
                else:
                    current = max(target, current - rate * dt)

            # OU slow wander (correlated low-frequency noise)
            if self.ou_noise_scale > 0 and dt > 0:
                ou_std = self.noise_std * self.ou_noise_scale
                alpha = np.exp(-dt / self.ou_tau_s)
                ou = alpha * ou + np.sqrt(1 - alpha ** 2) * rng.normal(0, ou_std)

            raw = current + ou + rng.normal(0, self.noise_std)

            # Quantize to grid (e.g. integer humidity) so the smooth trend becomes steps.
            if q > 0:
                candidate = round(raw / q) * q
            else:
                candidate = raw

            # Stickiness: hold previous emitted value most of the time. This is what
            # turns a quantized climb into a real stair-step (hold, hold, hold, jump).
            if last_emitted is not None and self.stickiness > 0 and rng.random() < self.stickiness:
                values[i] = last_emitted
            else:
                values[i] = candidate
                last_emitted = candidate

        return values


class CyclingEngine:

    def __init__(self, value_by_state: dict[str, float],
                 noise_std_by_state: dict[str, float],
                 transition_spike: Optional[dict] = None,
                 default_value: float = 0.0,
                 default_noise_std: float = 0.001,
                 ramp_by_state: dict[str, float] = None):
        self.value_by_state = value_by_state
        self.noise_std_by_state = noise_std_by_state
        self.transition_spike = transition_spike
        self.default_value = default_value
        self.default_noise_std = default_noise_std
        # ramp_by_state[state] = total value increase across one phase:
        # value(t) = base - span/2 + span * progress
        self.ramp_by_state = ramp_by_state or {}

    def generate(self, states: list[dict],
                 rng: np.random.Generator) -> np.ndarray:
        n = len(states)
        values = np.zeros(n)
        progress = _segment_progress(states) if self.ramp_by_state else None

        prev_state_key = None
        for i, state in enumerate(states):
            key = state["micro"] or state["macro"]
            base = self.value_by_state.get(key, self.default_value)
            std = self.noise_std_by_state.get(key, self.default_noise_std)
            span = self.ramp_by_state.get(key, 0.0)
            if span and progress is not None:
                base = base + span * (progress[i] - 0.5)

            # Transition spike at state boundaries
            if (self.transition_spike and prev_state_key is not None
                    and key != prev_state_key):
                spike_mag = self.transition_spike.get("magnitude", 0)
                spike_dur = self.transition_spike.get("duration_samples", 3)
                if spike_mag > 0:
                    # Apply decaying spike for next few samples
                    spike = spike_mag * rng.normal(1, 0.3)
                    values[i] = base + spike
                    prev_state_key = key
                    continue

            values[i] = base + rng.normal(0, std)
            prev_state_key = key

        return values


class EventSpikeEngine:
    def __init__(self, baseline: float, baseline_noise_std: float,
                 events: list[dict] = None):
        self.baseline = baseline
        self.baseline_noise_std = baseline_noise_std
        self.events = events or []

    def generate(self, timestamps: np.ndarray,
                 rng: np.random.Generator) -> np.ndarray:
        t_start_abs = timestamps[0]
        t_seconds = (timestamps - t_start_abs) / 1000.0
        n = len(timestamps)
        values = np.full(n, float(self.baseline))

        current_baseline = self.baseline
        sorted_events = sorted(self.events, key=lambda e: e["t_start"])

        for event in sorted_events:
            ev_start = event["t_start"]
            ev_dur = event.get("duration", 1.0)
            ev_mag = event.get("magnitude", 0.1)
            ev_shift = event.get("level_shift", 0.0)
            ev_type = event.get("type", "decaying")

            # Find affected samples
            mask = (t_seconds >= ev_start) & (t_seconds < ev_start + ev_dur)
            indices = np.where(mask)[0]

            if len(indices) == 0:
                # Still apply level shift for samples after event
                post_mask = t_seconds >= ev_start + ev_dur
                current_baseline += ev_shift
                values[post_mask] = current_baseline
                continue

            for idx in indices:
                t_rel = t_seconds[idx] - ev_start  # time within event
                progress = t_rel / ev_dur  # 0 to 1

                if ev_type == "impulse":
                    spike = ev_mag * (1.0 if progress < 0.2 else 0.0)
                elif ev_type == "sustained":
                    spike = ev_mag
                elif ev_type == "decaying":
                    spike = ev_mag * np.exp(-3.0 * progress)
                else:
                    spike = ev_mag

                spike *= rng.normal(1.0, 0.15)  # add randomness
                values[idx] = current_baseline + spike

            current_baseline += ev_shift
            post_mask = t_seconds >= ev_start + ev_dur
            # Only update samples not yet claimed by future events
            for j in np.where(post_mask)[0]:
                if values[j] == self.baseline or values[j] == current_baseline - ev_shift:
                    values[j] = current_baseline

        # Add baseline noise everywhere
        values += rng.normal(0, self.baseline_noise_std, n)
        return values


class PeriodicMotionEngine:

    def __init__(self, resting_value: float, active_low: float, active_high: float,
                 period_s: float, period_jitter_s: float = 1.0,
                 motion_duration_s: float = 6.0,
                 rest_duration_s: float = 12.0,
                 quaternion_flip: bool = False,
                 noise_std: float = 0.005,
                 noise_std_active: float = 0.02,
                 drift_rate: float = 0.0,
                 drift_direction: float = 0.0,
                 plateau_fraction: float = 0.0,
                 step_value_fraction: float = 0.0):
        
        self.resting_value = resting_value
        self.active_low = active_low
        self.active_high = active_high
        self.period_s = period_s
        self.period_jitter_s = period_jitter_s
        self.motion_duration_s = motion_duration_s
        self.rest_duration_s = rest_duration_s if rest_duration_s > 0 else (period_s - motion_duration_s)
        self.quaternion_flip = quaternion_flip
        self.noise_std = noise_std
        self.noise_std_active = noise_std_active
        self.drift_rate = drift_rate
        self.drift_direction = drift_direction
        self.plateau_fraction = max(0.0, min(0.85, plateau_fraction))
        self.step_value_fraction = max(0.0, min(0.85, step_value_fraction))

    def generate(self, timestamps: np.ndarray,
                 rng: np.random.Generator) -> np.ndarray:
        t_seconds = (timestamps - timestamps[0]) / 1000.0
        n = len(timestamps)

        # Pre-compute drift offset for each timestamp.
        # Use a soft saturation (tanh-like) instead of hard cap so drift continues
        # gently throughout the experiment, just slowing down rather than stopping.
        max_drift_magnitude = (self.active_high - self.active_low) * 0.20
        raw_drift = self.drift_rate * t_seconds
        # tanh saturates smoothly: small drift → linear, large drift → asymptote
        drift_offset = max_drift_magnitude * np.tanh(raw_drift / max_drift_magnitude) if max_drift_magnitude > 0 else raw_drift

        values = np.full(n, float(self.resting_value))
        is_active = np.zeros(n, dtype=bool)

        # Determine dominant excursion direction: whichever side (above/below
        # resting) has the larger range drives the motion target.
        excursion_down = (self.resting_value - self.active_low) > (self.active_high - self.resting_value)
        motion_target = self.active_low if excursion_down else self.active_high

        # Build motion segments
        current_t = rng.uniform(0, self.rest_duration_s * 0.5)

        while current_t < t_seconds[-1]:
            current_t += self.rest_duration_s + rng.normal(0, self.period_jitter_s * 0.3)
            motion_start = current_t
            motion_end = current_t + self.motion_duration_s + rng.normal(0, self.period_jitter_s * 0.3)
            motion_end = min(motion_end, t_seconds[-1])

            if motion_start >= t_seconds[-1]:
                break

            mask = (t_seconds >= motion_start) & (t_seconds < motion_end)
            indices = np.where(mask)[0]
            if len(indices) == 0:
                current_t = motion_end
                continue

            # Build phase boundary table for this motion segment.
            # Supports: optional mid-step on rise/fall + flat plateau at peak.
            #
            # With step_value_fraction > 0 (7-phase):
            #   rise-1 | step-hold | rise-2 | plateau | fall-1 | step-hold | fall-2
            # Without step (3-phase):
            #   rise | plateau | fall
            step_hold = 0.10 if self.step_value_fraction > 0 else 0.0
            plateau = self.plateau_fraction
            if self.step_value_fraction > 0:
                seg = max(0.01, (1.0 - plateau - 2 * step_hold) / 4.0)
                t1 = seg                       # end rise-1
                t2 = t1 + step_hold            # end step-hold-1
                t3 = t2 + seg                  # end rise-2
                t4 = t3 + plateau              # end peak-hold
                t5 = t4 + seg                  # end fall-1
                t6 = t5 + step_hold            # end step-hold-2
                step_level = self.resting_value + self.step_value_fraction * (motion_target - self.resting_value)
            else:
                rise_frac = (1.0 - plateau) / 2.0
                hold_end = rise_frac + plateau

            for i, idx in enumerate(indices):
                progress = i / max(len(indices) - 1, 1)

                if self.step_value_fraction > 0:
                    if progress < t1:
                        p = progress / t1
                        val = self.resting_value + (step_level - self.resting_value) * np.sin(p * np.pi / 2)
                    elif progress < t2:
                        val = step_level
                    elif progress < t3:
                        p = (progress - t2) / seg
                        val = step_level + (motion_target - step_level) * np.sin(p * np.pi / 2)
                    elif progress < t4:
                        val = motion_target
                    elif progress < t5:
                        p = (progress - t4) / seg
                        val = motion_target - (motion_target - step_level) * np.sin(p * np.pi / 2)
                    elif progress < t6:
                        val = step_level
                    else:
                        fall_frac = 1.0 - t6
                        p = (progress - t6) / fall_frac if fall_frac > 0 else 1.0
                        val = step_level - (step_level - self.resting_value) * np.sin(p * np.pi / 2)
                elif self.plateau_fraction > 0:
                    if progress < rise_frac:
                        p = progress / rise_frac if rise_frac > 0 else 1.0
                        val = self.resting_value + (motion_target - self.resting_value) * np.sin(p * np.pi / 2)
                    elif progress < hold_end:
                        val = motion_target
                    else:
                        fall_progress = (progress - hold_end) / rise_frac if rise_frac > 0 else 1.0
                        if self.quaternion_flip and not excursion_down:
                            if fall_progress < 0.1:
                                val = self.active_low
                            else:
                                ramp = (fall_progress - 0.1) / 0.9
                                val = self.active_low + (self.resting_value - self.active_low) * np.sin(ramp * np.pi / 2)
                        else:
                            val = motion_target - (motion_target - self.resting_value) * np.sin(fall_progress * np.pi / 2)
                else:
                    if progress < 0.5:
                        p = progress * 2
                        val = self.resting_value + (motion_target - self.resting_value) * np.sin(p * np.pi / 2)
                    else:
                        p = (progress - 0.5) * 2
                        if self.quaternion_flip and not excursion_down:
                            if p < 0.1:
                                val = self.active_low
                            else:
                                ramp = (p - 0.1) / 0.9
                                val = self.active_low + (self.resting_value - self.active_low) * np.sin(ramp * np.pi / 2)
                        else:
                            val = motion_target - (motion_target - self.resting_value) * np.sin(p * np.pi / 2)

                values[idx] = val
                is_active[idx] = True

            current_t = motion_end

        # Apply drift to all values
        values += drift_offset

        # Apply noise: very flat for rest (sticky), moderate for active.
        # Real XDK rest periods often show identical consecutive values for long
        # stretches because the sensor output doesn't update unless motion occurs.
        # We model this with very high stickiness (0.95) — only 5% of rest samples
        # get fresh noise, the rest copy from previous sample exactly.
        for i in range(n):
            if is_active[i]:
                values[i] += rng.normal(0, self.noise_std_active)
            else:
                if i > 0 and not is_active[i-1] and rng.random() < 0.95:
                    # Stick exactly to previous sample (creates flat plateaus)
                    values[i] = values[i-1]
                else:
                    values[i] += rng.normal(0, self.noise_std)

        # Clamp to reasonable range
        margin = (self.active_high - self.active_low) * 0.1
        clip_low = self.active_low - margin
        clip_high = self.active_high + margin
        values = np.clip(values, clip_low, clip_high)

        return values


class SinusoidalDriftEngine:
    """
    Realistic environmental column (temperature, humidity).
    Generates: base + daily_sine(t) + noise
    During anomaly states: shifts base value + scales noise.
    anomaly_state_effects: {state_name: {"value_shift": x, "noise_multiplier": y}}
    """

    def __init__(self, base_value: float,
                 daily_amplitude: float = 3.0,
                 daily_period_s: float = 86400.0,
                 phase_offset_s: float = 0.0,
                 noise_std: float = 50.0,
                 anomaly_state_effects: dict = None):
        self.base_value = base_value
        self.daily_amplitude = daily_amplitude
        self.daily_period_s = daily_period_s
        self.phase_offset_s = phase_offset_s
        self.noise_std = noise_std
        self.anomaly_state_effects = anomaly_state_effects or {}

    def generate(self, timestamps: np.ndarray, states: list[dict],
                 rng: np.random.Generator) -> np.ndarray:
        t_seconds = (timestamps - timestamps[0]) / 1000.0
        omega = 2 * np.pi / self.daily_period_s
        sine = self.daily_amplitude * np.sin(omega * (t_seconds + self.phase_offset_s) - np.pi / 2)
        values = self.base_value + sine

        for i, state in enumerate(states):
            effects = self.anomaly_state_effects.get(state["macro"], {})
            noise_mult = effects.get("noise_multiplier", 1.0)
            value_shift = effects.get("value_shift", 0.0)
            values[i] += value_shift + rng.normal(0, self.noise_std * noise_mult)

        return values


class CycleTemplateEngine:

    def __init__(self, templates: list, resting_value: float, excursion: float,
                 period_s: float, period_jitter_s: float = 1.0,
                 amplitude_jitter: float = 0.05,
                 noise_std: float = 0.001, drift_rate: float = 0.0):
        self.templates = [np.array(t, dtype=float) for t in templates]
        self.resting_value = resting_value
        self.excursion = excursion
        self.period_s = period_s
        self.period_jitter_s = period_jitter_s
        self.amplitude_jitter = amplitude_jitter
        self.noise_std = noise_std
        self.drift_rate = drift_rate

    def generate(self, timestamps: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        t_seconds = (timestamps - timestamps[0]) / 1000.0
        n = len(timestamps)
        total_dur = t_seconds[-1]

        values = np.full(n, float(self.resting_value))

        # Slow baseline drift
        max_drift = abs(self.excursion) * 0.15
        raw_drift = self.drift_rate * t_seconds
        drift = max_drift * np.tanh(raw_drift / max_drift) if max_drift > 0 else raw_drift

        # Lay down cycle templates end-to-end
        current_t = rng.uniform(0, self.period_s * 0.2)

        while current_t < total_dur:
            # Pick a random template
            tmpl = self.templates[int(rng.integers(0, len(self.templates)))]
            t_norm = np.linspace(0, 1, len(tmpl))

            # Per-cycle duration jitter
            dur = max(1.0, self.period_s + rng.normal(0, self.period_jitter_s))

            # Per-cycle amplitude jitter
            amp_scale = 1.0 + rng.normal(0, self.amplitude_jitter)

            cycle_end = current_t + dur
            mask = (t_seconds >= current_t) & (t_seconds < cycle_end)
            indices = np.where(mask)[0]

            if len(indices) > 0:
                positions = (t_seconds[indices] - current_t) / dur
                interp_vals = np.interp(positions, t_norm, tmpl)
                values[indices] = self.resting_value + self.excursion * amp_scale * interp_vals

            current_t = cycle_end

        values += drift
        values += rng.normal(0, self.noise_std, n)
        return values


class EnvelopeNoiseEngine:
    # Alternates noise amplitude between low/high phases on a cyclical schedule.
    # Models compressor duty cycling: ON phase = high vibration, OFF phase = quiet.

    def __init__(self, base_value: float,
                 low_noise_std: float,
                 high_noise_std: float,
                 period_s: float,
                 period_jitter_s: float = 0.0,
                 duty_cycle: float = 0.5,
                 envelope_shape: str = "square"):
        self.base_value = base_value
        self.low_noise_std = low_noise_std
        self.high_noise_std = high_noise_std
        self.period_s = period_s
        self.period_jitter_s = period_jitter_s
        self.duty_cycle = max(0.0, min(1.0, duty_cycle))
        self.envelope_shape = envelope_shape

    def generate(self, timestamps: np.ndarray,
                 rng: np.random.Generator) -> np.ndarray:
        t_seconds = (timestamps - timestamps[0]) / 1000.0
        n = len(timestamps)
        total_dur = float(t_seconds[-1]) if n > 0 else 0.0

        # Per-sample noise std driven by envelope
        std_arr = np.full(n, self.low_noise_std)
        current_t = 0.0
        while current_t < total_dur:
            period = max(1.0, self.period_s + rng.normal(0, self.period_jitter_s))
            on_dur = period * self.duty_cycle
            on_end = current_t + on_dur
            cycle_end = current_t + period

            if self.envelope_shape == "sine":
                mask = (t_seconds >= current_t) & (t_seconds < cycle_end)
                idx = np.where(mask)[0]
                if len(idx) > 0:
                    phase = (t_seconds[idx] - current_t) / period
                    # sine ramp between low and high
                    w = 0.5 * (1.0 - np.cos(2 * np.pi * phase))
                    std_arr[idx] = self.low_noise_std + (self.high_noise_std - self.low_noise_std) * w
            else:
                on_mask = (t_seconds >= current_t) & (t_seconds < on_end)
                std_arr[on_mask] = self.high_noise_std

            current_t = cycle_end

        return self.base_value + rng.normal(0.0, 1.0, n) * std_arr


# COMPONENT 4: SENSOR REALISM LAYER

class SensorRealism:

    def __init__(self, quantization_step: Optional[float] = None,
                 clip_min: Optional[float] = None,
                 clip_max: Optional[float] = None,
                 settling_samples: int = 0,
                 settling_noise_factor: float = 5.0):
        self.quantization_step = quantization_step
        self.clip_min = clip_min
        self.clip_max = clip_max
        self.settling_samples = settling_samples
        self.settling_noise_factor = settling_noise_factor

    def apply(self, values: np.ndarray,
              rng: np.random.Generator) -> np.ndarray:
        result = values.astype(float).copy()

        # Initial settling (higher noise in first N samples)
        if self.settling_samples > 0:
            settle_noise = rng.normal(0, self.settling_noise_factor,
                                      self.settling_samples)
            n_settle = min(self.settling_samples, len(result))
            result[:n_settle] += settle_noise[:n_settle]

        # Quantization
        if self.quantization_step and self.quantization_step > 0:
            result = np.round(result / self.quantization_step) * self.quantization_step

        # Clipping
        if self.clip_min is not None:
            result = np.maximum(result, self.clip_min)
        if self.clip_max is not None:
            result = np.minimum(result, self.clip_max)

        return result

# MAIN GENERATOR

class SyntheticXDKGenerator:

    def __init__(self, scenario: dict, seed: int = 42,
                 environment_config: dict = None,
                 anomaly_specs: list = None,
                 no_season_temp: bool = False):
        self.scenario = scenario
        self.rng = np.random.default_rng(seed)
        self.environment_config = environment_config or {}
        self.anomaly_specs = anomaly_specs or []
        self.no_season_temp = no_season_temp

    def generate(self) -> pd.DataFrame:
        s = self.scenario

        # Step 1: Timestamps
        ts_gen = TimestampGenerator(
            frequency_hz=s["frequency_hz"],
            duration_s=s["duration_s"],
            jitter_std_ms=s.get("jitter_std_ms", 2.0),
            gap_probability=s.get("gap_probability", 0.0002),
            start_timestamp_ms=s.get("start_timestamp_ms", 20000.0)
        )
        timestamps = ts_gen.generate(self.rng)

        # Step 2: State machine — merge config anomalies + CLI anomaly_specs
        merged_anomalies = list(s.get("anomalies", []))
        for i, spec in enumerate(self.anomaly_specs):
            merged_anomalies.append({
                "t_start": spec["t_start"],
                "t_end":   spec.get("t_end"),
                "state":   f"cli_anomaly_{i}_{spec['type']}",
            })
        sm = StateMachine(
            rhythm_config=s.get("rhythm"),
            anomaly_schedule=merged_anomalies
        )
        states = sm.resolve_states(timestamps, self.rng)

        # Step 3: Generate each column
        data = {"timestamp": timestamps.astype(int)}

        if "sensor_id" in s:
            data["sensor_id"] = np.full(len(timestamps), s["sensor_id"])

        for col_name, col_config in s["columns"].items():
            col_config = self._apply_anomaly_to_config(col_name, col_config)
            engine = self._build_engine(col_name, col_config)

            if isinstance(engine, SinusoidalDriftEngine):
                raw = engine.generate(timestamps, states, self.rng)
            elif isinstance(engine, GradualCurveEngine):
                raw = engine.generate(states, timestamps, self.rng)
            elif isinstance(engine, (EventSpikeEngine, PeriodicMotionEngine, CycleTemplateEngine, EnvelopeNoiseEngine)):
                raw = engine.generate(timestamps, self.rng)
                # Inject anomaly noise on top for engines that don't use state machine
                raw = self._inject_anomaly_noise(col_name, raw, timestamps, states)
            else:
                raw = engine.generate(states, self.rng)

            realism_config = col_config.get("realism", {})
            if realism_config:
                realism = SensorRealism(**realism_config)
                raw = realism.apply(raw, self.rng)

            data[col_name] = raw

        df = pd.DataFrame(data)

        # Gated logging: the real XDK only records while vibrating, so
        # compressor-OFF periods are timestamp gaps, not rows. Reproduce that
        # by dropping OFF rows except a short lead/tail around each ON phase.
        gated = s.get("gated_logging") or {}
        if gated.get("enabled"):
            keep_lead_s = gated.get("keep_lead_s", 45.0)
            keep_tail_s = gated.get("keep_tail_s", 45.0)
            t_sec = (timestamps - timestamps[0]) / 1000.0
            micro = np.array([st["micro"] or "" for st in states])
            keep = micro != "phase_off"

            # Re-admit the tail after an ON phase and the lead into the next
            off_runs = []
            start = None
            for i in range(len(micro)):
                if micro[i] == "phase_off" and start is None:
                    start = i
                elif micro[i] != "phase_off" and start is not None:
                    off_runs.append((start, i))
                    start = None
            if start is not None:
                off_runs.append((start, len(micro)))

            for run_start, run_end in off_runs:
                seg_t = t_sec[run_start:run_end]
                keep[run_start:run_end] |= (seg_t - seg_t[0]) < keep_tail_s
                keep[run_start:run_end] |= (seg_t[-1] - seg_t) < keep_lead_s

            df = df[keep].reset_index(drop=True)

        return df

    def _apply_anomaly_to_config(self, col_name: str, col_config: dict) -> dict:
        """Inject anomaly template effects into state-aware engine configs."""
        if not self.anomaly_specs:
            return col_config

        category = _col_category(col_name)
        col_config = copy.deepcopy(col_config)
        params = col_config.get("params", {})

        for i, spec in enumerate(self.anomaly_specs):
            state_key = f"cli_anomaly_{i}_{spec['type']}"
            template = ANOMALY_TEMPLATES.get(spec["type"], {})
            effects = template.get(category, {})

            # gradual_curve: override target and rate
            if col_config["engine"] == "gradual_curve":
                target_map = params.setdefault("target_by_state", {})
                rate_map   = params.setdefault("rate_by_state", {})
                base_target = params.get("default_target", list(target_map.values())[0] if target_map else 0)
                base_rate   = params.get("default_rate",   list(rate_map.values())[0]   if rate_map   else 0.001)
                target_map[state_key] = base_target * effects.get("target_multiplier", 1.0)
                rate_map[state_key]   = base_rate   * effects.get("rate_multiplier",   1.0)

            # constant_noise: override noise std
            if col_config["engine"] == "constant_noise":
                std_map = params.setdefault("noise_std_by_state", {})
                base_std = params.get("default_noise_std", 0.001)
                std_map[state_key] = base_std * effects.get("noise_multiplier", 1.0)

        col_config["params"] = params
        return col_config

    def _inject_anomaly_noise(self, col_name: str, raw: np.ndarray,
                               timestamps: np.ndarray, states: list[dict]) -> np.ndarray:
        """Add anomaly-driven noise to engines that don't use state machine."""
        if not self.anomaly_specs:
            return raw

        category = _col_category(col_name)
        t_start_abs = timestamps[0]
        t_seconds = (timestamps - t_start_abs) / 1000.0
        result = raw.copy()
        baseline_std = float(np.std(raw)) if np.std(raw) > 0 else 1.0

        for i, spec in enumerate(self.anomaly_specs):
            template = ANOMALY_TEMPLATES.get(spec["type"], {})
            effects = template.get(category, {})
            mult = effects.get("noise_multiplier", 1.0) - 1.0  # extra noise on top
            if mult <= 0:
                continue

            ev_start = spec["t_start"]
            ev_end   = spec.get("t_end", t_seconds[-1])
            mask = (t_seconds >= ev_start) & (t_seconds < ev_end)
            if mask.sum() == 0:
                continue

            extra = self.rng.normal(0, baseline_std * mult, mask.sum())
            result[mask] += extra

        return result

    def _build_sinusoidal_effects(self, category: str, base_value: float) -> dict:
        """Build per-state effects for SinusoidalDriftEngine from anomaly specs."""
        effects = {}
        for i, spec in enumerate(self.anomaly_specs):
            state_key = f"cli_anomaly_{i}_{spec['type']}"
            template = ANOMALY_TEMPLATES.get(spec["type"], {})
            cat_effects = template.get(category, {})
            effects[state_key] = {
                "value_shift":       base_value * (cat_effects.get("target_multiplier", 1.0) - 1.0),
                "noise_multiplier":  cat_effects.get("noise_multiplier", 1.0),
            }
        return effects

    def _build_engine(self, col_name: str, config: dict):
        engine_type = config["engine"]
        params = config["params"]

        # Override with environment config for weather-sensitive columns
        if engine_type in ("gradual_curve", "constant_noise") and self.environment_config:
            env = self.environment_config
            category = _col_category(col_name)
            if category == "temperature" and "base_temp" in env and not self.no_season_temp:
                base = env["base_temp"] * 1000
                return SinusoidalDriftEngine(
                    base_value=base,
                    daily_amplitude=env["amp_temp"] * 1000,
                    daily_period_s=86400.0,
                    phase_offset_s=env.get("phase_offset_s", 0.0),
                    noise_std=params.get("noise_std", 50.0),
                    anomaly_state_effects=self._build_sinusoidal_effects(category, base),
                )
            if category == "humidity" and "base_hum" in env:
                base = env["base_hum"]
                return SinusoidalDriftEngine(
                    base_value=base,
                    daily_amplitude=-env["amp_hum"],  # inverse of temp
                    daily_period_s=86400.0,
                    phase_offset_s=env.get("phase_offset_s", 0.0),
                    noise_std=params.get("noise_std", 0.5),
                    anomaly_state_effects=self._build_sinusoidal_effects(category, base),
                )

        if engine_type == "sinusoidal_drift":
            return SinusoidalDriftEngine(**params)
        elif engine_type == "constant_noise":
            return ConstantNoiseEngine(**params)
        elif engine_type == "gradual_curve":
            return GradualCurveEngine(**params)
        elif engine_type == "cycling":
            return CyclingEngine(**params)
        elif engine_type == "event_spike":
            return EventSpikeEngine(**params)
        elif engine_type == "periodic_motion":
            return PeriodicMotionEngine(**params)
        elif engine_type == "cycle_template":
            return CycleTemplateEngine(**params)
        elif engine_type == "envelope_noise":
            return EnvelopeNoiseEngine(**params)
        else:
            raise ValueError(f"Unknown engine type: {engine_type}")

# COMPONENT 5: AUTO-FITTER (fit_from_real_data)

class AutoFitter:
    # Columns that are metadata, not sensor readings
    META_COLUMNS = {'timestamp', 'sensor_id', 'voltage'}
    # Columns known to be environmental (use gradual_curve if trending)
    ENVIRONMENTAL = {'temperature', 'humidity'}
    # Columns known to be stable (pressure)
    STABLE = {'pressure'}
    # Groups that should share state-detection (acceleration axes)
    ACCEL_COLS = {'acceleration_x', 'acceleration_y', 'acceleration_z'}
    ORIENT_COLS = {'orientation_x', 'orientation_y', 'orientation_z', 'orientation_w'}

    def __init__(self, filepath: str, encoding: str = 'utf-8'):
        try:
            self.df = pd.read_csv(filepath, encoding=encoding)
        except UnicodeDecodeError:
            self.df = pd.read_csv(filepath, encoding='latin-1')

        self.filepath = filepath
        self.sensor_columns = [
            c for c in self.df.columns if c not in self.META_COLUMNS
        ]

    def fit(self, domain_hints: dict = None) -> dict:
        hints = domain_hints or {}
        df = self.df

        # --- Step 1: Timestamp analysis ---
        ts_stats = self._analyze_timestamps()

        # --- Step 2: Detect cycling in acceleration (check if environment has rhythm) ---
        rhythm_config, cycling_states = self._detect_rhythm()

        # --- Step 2b: Detect gated logging ---
        # If a sizeable share of the recording window is >60s timestamp gaps,
        # the device only logs while active (XDK stops recording when the
        # compressor is off). The generator then drops OFF rows the same way.
        gated_logging = None
        if rhythm_config is not None:
            t_all = (df['timestamp'].values - df['timestamp'].values[0]) / 1000.0
            dt = np.diff(t_all)
            gap_total_s = float(dt[dt > 60.0].sum())
            gap_fraction = gap_total_s / max(t_all[-1], 1e-9)
            if gap_fraction > 0.15:
                gated_logging = {
                    "enabled": True,
                    "keep_lead_s": 45.0,
                    "keep_tail_s": 45.0,
                    "_gap_fraction": round(gap_fraction, 3),
                }

        # --- Step 3: Build column configs ---
        columns = {}
        for col in self.sensor_columns:
            if col == 'timestamp':
                continue
            config = self._fit_column(col, cycling_states)
            if config is not None:
                columns[col] = config

        # --- Step 4: Build anomaly schedule from hints ---
        anomalies = []
        if "anomaly_times" in hints:
            for i, (t_start, t_end) in enumerate(hints["anomaly_times"]):
                anomalies.append({
                    "t_start": t_start,
                    "t_end": t_end,
                    "state": f"anomaly_{i}"
                })

        # --- Step 5: Assemble scenario ---
        scenario = {
            "domain": hints.get("domain", "auto_fitted"),
            "sensor_position": hints.get("sensor_position", "unknown"),
            "frequency_hz": ts_stats["frequency_hz"],
            "duration_s": ts_stats["duration_s"],
            "jitter_std_ms": ts_stats["jitter_std_ms"],
            "gap_probability": ts_stats["gap_probability"],
            "rhythm": rhythm_config,
            "gated_logging": gated_logging,
            "anomalies": anomalies,
            "columns": columns,
        }

        # Add sensor_id if present
        if 'sensor_id' in df.columns:
            scenario["sensor_id"] = int(df['sensor_id'].iloc[0])

        # --- Step 6: Pre-populate anomaly state mappings
        self._populate_anomaly_states(scenario)

        # --- Step 7: If user provided anomaly_times, fit anomaly params from actual data ---
        if "anomaly_times" in hints:
            self._fit_anomaly_params_from_data(scenario, hints["anomaly_times"])

        return scenario

    def _fit_anomaly_params_from_data(self, scenario: dict,
                                       anomaly_times: list):
        df = self.df
        ts = df['timestamp'].values
        t_seconds = (ts - ts[0]) / 1000.0

        # Build normal vs anomaly masks
        anomaly_mask = np.zeros(len(df), dtype=bool)
        for t_start, t_end in anomaly_times:
            if t_end is None:
                t_end = t_seconds[-1] + 1
            anomaly_mask |= (t_seconds >= t_start) & (t_seconds < t_end)
        normal_mask = ~anomaly_mask

        if anomaly_mask.sum() < 10 or normal_mask.sum() < 10:
            return

        for col, cfg in scenario.get("columns", {}).items():
            if col not in df.columns:
                continue
            data = df[col].values

            params = cfg.get("params", {})
            engine = cfg["engine"]

            # For constant_noise: track noise_std per state
            if engine == "constant_noise":
                std_map = params.get("noise_std_by_state", {})
                normal_std = float(np.std(data[normal_mask]))
                anomaly_std = float(np.std(data[anomaly_mask]))

                if "normal" not in std_map:
                    std_map["normal"] = normal_std
                for i in range(5):
                    std_map[f"anomaly_{i}"] = anomaly_std
                params["noise_std_by_state"] = std_map

    def _populate_anomaly_states(self, scenario: dict):
        anomaly_states = set()
        for a in scenario.get("anomalies", []):
            anomaly_states.add(a["state"])

        # Only populate if there are actual anomalies defined
        if not anomaly_states:
            return

        for col, cfg in scenario.get("columns", {}).items():
            params = cfg.get("params", {})

            # Handle noise_std_by_state
            std_map = params.get("noise_std_by_state", {})
            if std_map and "phase_off" in std_map:
                quiet_val = std_map["phase_off"]
                for state in anomaly_states:
                    if state not in std_map:
                        std_map[state] = quiet_val

            # Handle target_by_state (gradual_curve)
            target_map = params.get("target_by_state", {})
            if target_map:
                # For anomaly, target is typically ambient/default
                default_target = params.get("default_target",
                    list(target_map.values())[-1] if target_map else 0)
                for state in anomaly_states:
                    if state not in target_map:
                        target_map[state] = default_target

            # Handle rate_by_state (gradual_curve)
            rate_map = params.get("rate_by_state", {})
            if rate_map:
                default_rate = params.get("default_rate",
                    list(rate_map.values())[-1] if rate_map else 0.001)
                for state in anomaly_states:
                    if state not in rate_map:
                        rate_map[state] = default_rate

    # TIMESTAMP ANALYSIS

    def _analyze_timestamps(self) -> dict:
        ts = self.df['timestamp']
        diffs = ts.diff().dropna().values
        median_interval = np.median(diffs)

        # Auto-detect timestamp unit: if median diff < 10, it's in seconds.
        # Real XDK ms timestamps give diffs of 50-1000. Unix-second timestamps
        # give diffs of 0.05-1.0.
        if median_interval < 10:
            # Seconds — convert to milliseconds internally
            ts_ms = ts * 1000.0
            self.df['timestamp'] = ts_ms
            diffs = ts_ms.diff().dropna().values
            median_interval = np.median(diffs)
            self._timestamp_was_seconds = True
        else:
            self._timestamp_was_seconds = False

        duration_s = (self.df['timestamp'].iloc[-1] - self.df['timestamp'].iloc[0]) / 1000.0
        frequency_hz = round(1000.0 / median_interval)

        # Jitter: std of intervals excluding large gaps
        normal_diffs = diffs[diffs < median_interval * 3]
        jitter_std = float(np.std(normal_diffs)) if len(normal_diffs) > 0 else 2.0

        # Gap probability
        n_gaps = np.sum(diffs > median_interval * 3)
        gap_prob = float(n_gaps / len(diffs)) if len(diffs) > 0 else 0.0002

        return {
            "frequency_hz": frequency_hz,
            "duration_s": duration_s,
            "median_interval_ms": float(median_interval),
            "jitter_std_ms": jitter_std,
            "gap_probability": gap_prob,
        }

    # RHYTHM DETECTION (cycling pattern in acceleration)

    def _detect_rhythm(self) -> tuple:
        accel_cols = [c for c in self.ACCEL_COLS if c in self.df.columns]
        if not accel_cols:
            return None, None

        # Try every accel axis; pick the one with the strongest bimodal envelope,
        # not just the highest std. A noisy axis with startup transients can beat
        # a clean cycling axis on std, but will lose on bimodality ratio.
        best = None
        for col in accel_cols:
            attempt = self._detect_rhythm_on_column(col)
            if attempt is None:
                continue
            if best is None or attempt["ratio"] > best["ratio"]:
                best = attempt

        if best is None:
            return None, None

        return best["rhythm_config"], best["state_labels"]

    def _detect_rhythm_on_column(self, col: str) -> Optional[dict]:
        data = self.df[col].values
        ts_stats = self._analyze_timestamps()
        window = max(50, int(ts_stats["frequency_hz"] * 30))
        rolling_std = pd.Series(data).rolling(window, center=True).std().dropna().values

        if len(rolling_std) < 100:
            return None

        # Otsu threshold: minimize intra-class variance to split into ON/OFF clusters.
        sorted_vals = np.sort(rolling_std)
        n_rs = len(sorted_vals)
        best_threshold = 0
        best_variance = float('inf')
        for pct in range(10, 90, 2):
            t = np.percentile(sorted_vals, pct)
            low = sorted_vals[sorted_vals <= t]
            high = sorted_vals[sorted_vals > t]
            if len(low) < 10 or len(high) < 10:
                continue
            w_low = len(low) / n_rs
            w_high = len(high) / n_rs
            var = w_low * np.var(low) + w_high * np.var(high)
            if var < best_variance:
                best_variance = var
                best_threshold = t

        low_cluster = rolling_std[rolling_std <= best_threshold]
        high_cluster = rolling_std[rolling_std > best_threshold]
        low_mean = np.mean(low_cluster) if len(low_cluster) > 0 else 0
        high_mean = np.mean(high_cluster) if len(high_cluster) > 0 else 0

        # XDK accel is coarsely quantized (e.g. acceleration_z only ever reads
        # 0.9 or 1.0), so the OFF-phase rolling std never drops near zero and the
        # ON/OFF ratio lands well under 2. The duration checks below (>=3 cycles
        # of >=30s each side, duration_ratio <= 10) are the real false-positive
        # guard, so a softer gate here is safe.
        ratio = high_mean / (low_mean + 1e-10)
        if ratio < 1.5:
            return None

        full_rolling = pd.Series(data).rolling(window, center=True).std().values
        nan_mask = np.isnan(full_rolling)
        state_labels = np.where(
            nan_mask, "unknown",
            np.where(full_rolling > best_threshold, "phase_on", "phase_off")
        )

        # Brief threshold crossings inside a phase (rolling std dipping for a
        # few seconds mid-ON) slice one long block into many short segments,
        # which drags duration_mean down and blows duration_std up. Smooth the
        # per-sample chatter before measuring.
        state_labels = self._smooth_state_labels(
            state_labels, ts_stats["median_interval_ms"], min_seg_s=120.0
        )

        # Phase durations must be measured in wall-clock time, not sample
        # counts: the XDK stops logging while the compressor is off, so the
        # OFF phases exist mostly as 10+ minute timestamp gaps with no rows.
        t_sec = (self.df['timestamp'].values - self.df['timestamp'].values[0]) / 1000.0
        on_durations, off_durations = self._measure_phase_durations(
            state_labels, t_sec
        )
        if len(on_durations) < 3 or len(off_durations) < 3:
            return None

        on_mean = np.mean(on_durations)
        off_mean = np.mean(off_durations)
        duration_ratio = max(on_mean, off_mean) / (min(on_mean, off_mean) + 1e-10)
        if duration_ratio > 10:
            return None

        # Cap duration_std at half the mean: the StateMachine draws
        # normal(mean, std) clamped at 10s, so an std >= mean makes a large
        # share of draws collapse to 10s micro-phases and the synthetic
        # cycles far faster than the real appliance.
        rhythm_config = {
            "phases": [
                {
                    "name": "phase_on",
                    "duration_mean": float(on_mean),
                    "duration_std": float(min(np.std(on_durations), on_mean * 0.5)),
                },
                {
                    "name": "phase_off",
                    "duration_mean": float(off_mean),
                    "duration_std": float(min(np.std(off_durations), off_mean * 0.5)),
                },
            ],
            "_detection_info": {
                "detected_on_column": col,
                "on_noise_level": float(high_mean),
                "off_noise_level": float(low_mean),
                "threshold": float(best_threshold),
                "n_on_cycles": len(on_durations),
                "n_off_cycles": len(off_durations),
                "bimodality_ratio": float(ratio),
            }
        }
        return {"rhythm_config": rhythm_config, "state_labels": state_labels, "ratio": ratio}

    def _smooth_state_labels(self, labels: np.ndarray, interval_ms: float,
                             min_seg_s: float = 90.0) -> np.ndarray:
        """
        Clean up label flicker with a centered rolling majority vote.

        The raw per-sample threshold crossing flickers constantly inside a
        phase (a visually solid 12-min ON block is really dense on/off
        chatter), so run-based merging can't recover the true blocks. A
        majority vote over ~2x min_seg_s turns the chatter into the clean
        block structure visible in the rolling-RMS plot.
        """
        win = max(3, int(min_seg_s * 2 * 1000.0 / interval_ms))
        binary = pd.Series(np.where(
            labels == "phase_on", 1.0,
            np.where(labels == "phase_off", 0.0, np.nan)
        ))
        frac = binary.rolling(win, center=True, min_periods=1).mean().values
        return np.where(
            np.isnan(frac), "unknown",
            np.where(frac > 0.5, "phase_on", "phase_off")
        )

    def _measure_phase_durations(self, state_labels: np.ndarray,
                                  t_sec: np.ndarray,
                                  gap_off_s: float = 60.0) -> tuple:
        """
        Measure how long each ON and OFF phase lasts, in wall-clock seconds.

        Logging gaps longer than gap_off_s count as OFF phases: the XDK only
        records while vibrating, so compressor-OFF periods show up as long
        timestamp gaps rather than as labeled samples.
        """
        # Build (label, start_t, end_t) segments, splitting at logging gaps
        segments = []
        cur_label, cur_start = None, None
        prev_t = None
        for label, t in zip(state_labels, t_sec):
            if prev_t is not None and (t - prev_t) > gap_off_s:
                if cur_label is not None:
                    segments.append([cur_label, cur_start, prev_t])
                segments.append(["phase_off", prev_t, t])
                cur_label = None
            if label != cur_label:
                if cur_label is not None:
                    segments.append([cur_label, cur_start, t])
                cur_label, cur_start = label, t
            prev_t = t
        if cur_label is not None:
            segments.append([cur_label, cur_start, prev_t])

        # Merge adjacent segments with the same label (gap-OFF next to
        # labeled-OFF is one continuous OFF phase)
        merged = []
        for seg in segments:
            if merged and merged[-1][0] == seg[0]:
                merged[-1][2] = seg[2]
            else:
                merged.append(seg)

        on_durations, off_durations = [], []
        for label, start, end in merged:
            duration_s = end - start
            if duration_s > 30:  # ignore phases shorter than 30 seconds
                if label == "phase_on":
                    on_durations.append(duration_s)
                elif label == "phase_off":
                    off_durations.append(duration_s)

        return on_durations, off_durations

    # -----------------------------------------------------------------
    # PER-COLUMN FITTING
    # -----------------------------------------------------------------

    def _fit_column(self, col: str, cycling_states) -> Optional[dict]:
        data = self.df[col].values
        n = len(data)

        if n < 10:
            return None

        # Basic stats
        std_val = float(np.nanstd(data))
        start_val = float(np.nanmean(data[:min(50, n)]))
        end_val = float(np.nanmean(data[max(0, n-50):]))

        # --- Check 0a: Stable columns (pressure) FIRST ---
        # Must come before the relative_std static check: pressure has a large absolute
        # value (~98000 Pa) so its relative_std (~7e-5) wrongly triggers the static guard
        # and produces a noise=0 flat line.
        if col in self.STABLE:
            return self._fit_stable_signal(col, data)

        # --- Check 0: Static column (sensor not moving, XDK repeats same value) ---
        # Use the stable tail (skip first 10% which may contain settling transient)
        stable = data[max(1, n // 10):]
        stable_std = float(np.std(stable))
        stable_mean = float(np.median(stable))
        relative_std = stable_std / (abs(stable_mean) + 1e-10)
        if stable_std < 1e-4 or relative_std < 1e-4:
            print(f"[Static] {col}: stable_std={stable_std:.2e}, using sticky constant")
            return {
                "engine": "constant_noise",
                "params": {
                    "base_value": stable_mean,
                    "noise_std_by_state": {},
                    "default_noise_std": 0.0,
                    "stickiness": 0.99,
                }
            }

        # --- Check 0c: Environmental sinusoidal (day/night U-shape or ∩-shape) ---
        # Require ≥18h of data: shorter windows can't distinguish a true daily cycle
        # from fast-rise-then-plateau (which triggers false ∩-shape reversal detection).
        if col in self.ENVIRONMENTAL:
            ts_env = self.df['timestamp'].values
            duration_h = (ts_env[-1] - ts_env[0]) / (1000.0 * 3600.0)
            if duration_h >= 18.0 and self._has_reversal(data, start_val, end_val):
                return self._fit_sinusoidal(col, data)

        # --- Check 1: Trending (gradual_curve) ---
        if self._is_trending(col, data, start_val, end_val, std_val):
            return self._fit_gradual_curve(col, data, start_val, cycling_states)

        # --- Check 2: Responds to cycling? (priority over event detection) ---
        if cycling_states is not None:
            state_aware = self._fit_state_aware(col, data, cycling_states)
            if state_aware is not None:
                return state_aware

        # --- Check 3: Periodic motion (must come BEFORE events) ---
        if self._is_periodic_motion(data):
            return self._fit_cycle_template(col, data)

        # --- Check 4: Event spikes ---
        if self._has_events(data):
            return self._fit_event_spike(col, data)

        # --- Default: constant_noise ---
        return self._fit_constant_noise(col, data, cycling_states)

    # ----- Pattern detection helpers -----

    def _is_trending(self, col: str, data: np.ndarray,
                     start_val: float, end_val: float, std_val: float) -> bool:
        """Column is trending if start-to-end change is large relative to noise."""
        if col in self.STABLE:
            return False

        change = abs(end_val - start_val)
        # For environmental columns (temp, humidity), lower threshold
        if col in self.ENVIRONMENTAL:
            return change > std_val * 0.5 and change > abs(start_val) * 0.02
        # For all other columns, require very strong trend
        # (orientation/acceleration should NOT be detected as trending)
        return change > std_val * 3.0 and change > abs(mean_val := np.mean(data)) * 0.1

    def _has_events(self, data: np.ndarray) -> bool:
        """Detect if column has discrete spike events."""
        diffs = np.abs(np.diff(data))
        median_diff = np.median(diffs)
        if median_diff == 0:
            median_diff = np.mean(diffs) + 1e-10

        # Count large jumps (>10x median diff)
        n_jumps = np.sum(diffs > median_diff * 10)
        # Events = rare but significant jumps (between 0.01% and 5% of data)
        ratio = n_jumps / len(diffs)
        return 0.0001 < ratio < 0.05

    def _is_periodic_motion(self, data: np.ndarray) -> bool:
        """
        Detect repetitive motion pattern (robot arm joint, pendulum).
        
        Pattern: dominant resting peak + repeated excursions to extremes.
        Resting can be either centered or at one edge of range.
        """
        n = len(data)
        if n < 200:
            return False

        hist, edges = np.histogram(data, bins=30)
        peak_bin = np.argmax(hist)
        peak_count = hist[peak_bin]
        resting_value = (edges[peak_bin] + edges[peak_bin + 1]) / 2
        mode_fraction = peak_count / n

        data_range = np.max(data) - np.min(data)
        if data_range < 0.05:
            return False

        # Far extreme distance from resting value
        far_extreme_dist = max(
            abs(resting_value - np.max(data)),
            abs(resting_value - np.min(data))
        )

        centered = data - resting_value
        crossings = np.where(np.diff(np.sign(centered)))[0]
        if len(crossings) < 6:
            return False

        intervals = np.diff(crossings)
        regularity = np.std(intervals) / (np.mean(intervals) + 1e-10)

        return (
            mode_fraction > 0.15 and
            far_extreme_dist > data_range * 0.3 and
            regularity < 1.5 and
            len(crossings) >= 6
        )

    def _has_reversal(self, data: np.ndarray,
                      start_val: float, end_val: float) -> bool:
        """True if smoothed data has a U-shape or ∩-shape: extreme in middle
        that is clearly offset from both endpoints (day/night cycle indicator)."""
        n = len(data)
        if n < 500:
            return False
        window = max(100, n // 20)
        smoothed = pd.Series(data).rolling(window, center=True,
                                           min_periods=window // 2).mean().values
        valid = smoothed[~np.isnan(smoothed)]
        if len(valid) < 10:
            return False
        data_range = float(np.max(valid) - np.min(valid))
        if data_range < 1e-6:
            return False
        threshold = data_range * 0.1
        mid_s, mid_e = n // 6, 5 * n // 6
        mid = smoothed[mid_s:mid_e]
        ep_start = float(np.nanmean(smoothed[:max(1, n // 10)]))
        ep_end   = float(np.nanmean(smoothed[max(0, 9 * n // 10):]))
        ep_min = min(ep_start, ep_end)
        ep_max = max(ep_start, ep_end)
        if np.nanmin(mid) < ep_min - threshold:   # U-shape: cold trough in middle
            return True
        if np.nanmax(mid) > ep_max + threshold:   # ∩-shape: warm peak in middle
            return True
        return False

    def _fit_sinusoidal(self, col: str, data: np.ndarray) -> dict:
        """Fit SinusoidalDriftEngine to a column that shows a diurnal U/∩ pattern.
        Automatically derives phase_offset_s from where the extreme falls in the recording."""
        n = len(data)
        ts = self.df['timestamp'].values
        t_seconds = (ts - ts[0]) / 1000.0

        window = max(100, n // 20)
        smoothed = pd.Series(data).rolling(window, center=True,
                                           min_periods=window // 2).mean().values
        valid = smoothed[~np.isnan(smoothed)]
        s_max = float(np.nanmax(valid))
        s_min = float(np.nanmin(valid))
        base_value = (s_max + s_min) / 2.0
        amplitude  = (s_max - s_min) / 2.0

        ep_start = float(np.nanmean(smoothed[:max(1, n // 10)]))
        ep_end   = float(np.nanmean(smoothed[max(0, 9 * n // 10):]))
        ep_mean  = (ep_start + ep_end) / 2.0

        if ep_mean >= base_value:
            # U-shape: trough in middle → min when sin(...)=-1
            # sin(ω(t_min + φ) - π/2) = -1  →  ω(t_min + φ) = 0  →  φ = -t_min
            extreme_idx = int(np.nanargmin(smoothed))
            phase_offset_s = -float(t_seconds[extreme_idx])
        else:
            # ∩-shape: peak in middle → max when sin(...)=1
            # sin(ω(t_max + φ) - π/2) = 1  →  ω(t_max + φ) = π  →  φ = 43200 - t_max
            extreme_idx = int(np.nanargmax(smoothed))
            phase_offset_s = float(86400.0 / 2.0 - t_seconds[extreme_idx])

        omega = 2.0 * np.pi / 86400.0
        sine  = amplitude * np.sin(omega * (t_seconds + phase_offset_s) - np.pi / 2)
        residual  = data - (base_value + sine)
        noise_std = float(np.nanstd(residual))

        realism_cfg = self._get_realism(col, data)
        if realism_cfg and realism_cfg.get("quantization_step"):
            noise_std = min(noise_std, float(realism_cfg["quantization_step"]) * 0.3)

        config = {
            "engine": "sinusoidal_drift",
            "params": {
                "base_value":       float(base_value),
                "daily_amplitude":  float(amplitude),
                "daily_period_s":   86400.0,
                "phase_offset_s":   float(phase_offset_s),
                "noise_std":        noise_std,
            }
        }
        if realism_cfg:
            config["realism"] = realism_cfg
        return config

    def _fit_stable_signal(self, col: str, data: np.ndarray) -> dict:
        """Pressure-like: not trending, but not flat — real HF noise + potential slow drift."""
        n = len(data)
        base_value = float(np.median(data))
        noise_std  = float(np.std(np.diff(data)) / np.sqrt(2))
        noise_std  = max(noise_std, 1.0)

        window = max(50, n // 10)
        smoothed = pd.Series(data).rolling(window, center=True,
                                           min_periods=window // 2).mean().values
        valid_s = smoothed[~np.isnan(smoothed)]
        slow_range = float(np.max(valid_s) - np.min(valid_s)) if len(valid_s) > 0 else 0.0

        start_v = float(np.nanmean(data[:max(1, n // 10)]))
        end_v   = float(np.nanmean(data[max(0, 9 * n // 10):]))

        if slow_range > noise_std * 5:
            if self._has_reversal(data, start_v, end_v):
                return self._fit_sinusoidal(col, data)
            else:
                # Monotonic trend (e.g. pressure drifting). Use pure-drift mode:
                # constant slope (sign follows the data — falls if data falls, rises
                # if data rises), with a common-sense clamp so it never runs to absurd
                # values. This replaces the old far_target exponential trick, which
                # made the signal flatten out instead of keep drifting.
                ts = self.df['timestamp'].values
                duration_s = float((ts[-1] - ts[0]) / 1000.0)
                if duration_s < 1.0:
                    duration_s = 1.0
                drift_slope = (end_v - start_v) / duration_s  # sign = direction, from data
                span = abs(end_v - start_v)

                realism_cfg = self._get_realism(col, data)
                params = {
                    "initial_value": float(start_v),
                    "target_by_state": {"normal": float(start_v)},
                    "rate_by_state": {"normal": 0.0},
                    "noise_std": noise_std,
                    "default_target": float(start_v),
                    "default_rate": 0.0,
                    "drift_slope": float(drift_slope),
                    "ou_noise_scale": 3.0,
                    "ou_tau_s": 900.0,
                }
                # Clamp follows the drift direction (4x observed span beyond start).
                if drift_slope < 0:
                    params["drift_floor"] = float(start_v - 4.0 * span)
                elif drift_slope > 0:
                    params["drift_ceil"] = float(start_v + 4.0 * span)

                cfg = {"engine": "gradual_curve", "params": params}
                if realism_cfg:
                    cfg["realism"] = realism_cfg
                return cfg

        config = {
            "engine": "constant_noise",
            "params": {
                "base_value": base_value,
                "noise_std_by_state": {},
                "default_noise_std": noise_std,
            }
        }
        realism_cfg = self._get_realism(col, data)
        if realism_cfg:
            config["realism"] = realism_cfg
        return config

    def _fit_periodic_motion(self, col: str, data: np.ndarray) -> dict:
        n = len(data)

        # Step 1: Resting value from histogram mode
        hist, edges = np.histogram(data, bins=30)
        peak_bin = np.argmax(hist)
        resting_value = float((edges[peak_bin] + edges[peak_bin + 1]) / 2)

        # Step 2: Active range — use 2nd/98th percentile to capture peaks
        # while still rejecting outlier noise spikes
        active_low = float(np.percentile(data, 2))
        active_high = float(np.percentile(data, 98))

        # Setup timestamps
        ts = self.df['timestamp'].values
        t_seconds = (ts - ts[0]) / 1000.0
        total_dur = t_seconds[-1]

        # Step 3: Period via autocorrelation — robust to complex waveform shapes
        # that fool zero-crossing counting (e.g. signals with shoulders/plateaus).
        range_above = float(np.percentile(data, 98) - resting_value)
        range_below = float(resting_value - np.percentile(data, 2))
        total_range = range_above + range_below
        is_bidirectional = (
            range_above > total_range * 0.2 and
            range_below > total_range * 0.2
        )

        centered = data - np.mean(data)
        corr = np.correlate(centered, centered, mode='full')
        corr = corr[n - 1:]           # keep lags 0..n-1
        corr = corr / corr[0]         # normalise to 1 at lag 0

        # Find first trough then first peak after it — that peak lag = 1 period
        min_period_samples = max(10, n // 50)
        max_period_samples = n // 2
        search = corr[min_period_samples:max_period_samples]
        if len(search) > 3:
            # First local maximum in autocorrelation = dominant period
            peaks = argrelmax(search, order=max(3, min_period_samples // 4))[0]
            if len(peaks) > 0:
                period_samples = peaks[0] + min_period_samples
            else:
                period_samples = int(np.argmax(search)) + min_period_samples

            # Distinguish two cases where autocorr finds half the true period:
            #   Case A: asymmetric single-peak (shoulder/plateau) within one cycle
            #           → autocorr finds T/2, true period is T → should double
            #   Case B: genuine double-peak (two separate excursions per cycle)
            #           → autocorr finds T/2 correctly → should NOT double
            #
            # Discriminator: count distinct excursion episodes (contiguous runs
            # where signal leaves resting zone). If expected_periods >> episodes,
            # it means each episode spans ~2 apparent periods → true period = 2×.
            rest_thr = (active_high - active_low) * 0.15
            episode_mask = np.abs(data - resting_value) >= rest_thr
            n_episodes = max(1, int(np.sum(np.diff(episode_mask.astype(int)) > 0)))
            n_expected = n / period_samples  # number of periods at current estimate

            double_samples = 2 * period_samples
            if (double_samples < len(corr) and
                    corr[double_samples] > 0.3 and
                    n_expected > n_episodes * 1.5):
                period_samples = double_samples

            period_s = period_samples * (total_dur / n)
        else:
            period_s = 20.0

        period_s = max(12.5, min(period_s, total_dur / 3))

        # Step 4: Quaternion flip detection
        diffs = np.diff(data)
        flip_threshold = 0.8 * (active_high - active_low)
        n_flips = np.sum(np.abs(diffs) > flip_threshold)
        quaternion_flip = n_flips > 5

        # Step 5: Noise estimation
        # Identify rest mask (samples within 20% of range from resting)
        rest_threshold = (active_high - active_low) * 0.15
        rest_mask = np.abs(data - resting_value) < rest_threshold
        active_mask = ~rest_mask

        if rest_mask.sum() > 50:
            # Real noise during rest = std of consecutive diffs / sqrt(2)
            # This is robust to drift, captures only the high-frequency wiggle
            rest_data = data[rest_mask]
            rest_diffs = np.diff(rest_data)
            noise_std_rest = float(np.std(rest_diffs) / np.sqrt(2))
            # Floor it so we don't get unrealistically tiny noise
            noise_std_rest = max(noise_std_rest, 0.0005)
        else:
            noise_std_rest = float(np.std(data) * 0.05)

        if active_mask.sum() > 50:
            active_data = data[active_mask]
            noise_std_active = float(np.std(np.diff(active_data))) * 0.5
        else:
            noise_std_active = noise_std_rest * 3

        # Step 6: Drift estimation from rest values over time
        # Linear fit on rest samples → drift_rate is slope (per second)
        if rest_mask.sum() > 100:
            rest_times = t_seconds[rest_mask]
            rest_values = data[rest_mask]
            # Linear regression
            try:
                slope, intercept = np.polyfit(rest_times, rest_values, 1)
                drift_rate = float(slope)
                # Update resting_value to be value at t=0 (intercept)
                resting_value_corrected = float(intercept)
            except Exception:
                drift_rate = 0.0
                resting_value_corrected = resting_value
        else:
            drift_rate = 0.0
            resting_value_corrected = resting_value

        # Motion duration heuristic
        motion_duration_s = period_s * 0.35
        rest_duration_s = period_s - motion_duration_s

        # Plateau + step fraction estimation from active sample distribution.
        excursion_down = (resting_value - active_low) > (active_high - resting_value)
        motion_target_val = active_low if excursion_down else active_high
        plateau_fraction = 0.3
        step_value_fraction = 0.0

        if active_mask.sum() > 100:
            active_data_vals = data[active_mask]
            excursion = abs(motion_target_val - resting_value)
            if excursion > 1e-6:
                # Normalize active samples: 0 = resting, 1 = peak
                norm = np.clip((active_data_vals - resting_value) / (motion_target_val - resting_value), 0, 1)

                # Plateau: fraction of active time near peak (top 25%)
                plateau_fraction = float(np.clip(np.mean(norm > 0.75), 0.0, 0.8))

                # Intermediate step: look for a secondary cluster in [0.2, 0.75]
                mid_mask = (norm >= 0.2) & (norm <= 0.75)
                if mid_mask.sum() > 20:
                    ah, ae = np.histogram(norm[mid_mask], bins=10, range=(0.2, 0.75))
                    # Only flag a step if the secondary cluster is meaningful (>15% of active)
                    if ah.max() > len(active_data_vals) * 0.15:
                        best_bin = np.argmax(ah)
                        step_value_fraction = float((ae[best_bin] + ae[best_bin + 1]) / 2)
                        step_value_fraction = float(np.clip(step_value_fraction, 0.2, 0.8))

        config = {
            "engine": "periodic_motion",
            "params": {
                "resting_value": resting_value_corrected,
                "active_low": active_low,
                "active_high": active_high,
                "period_s": period_s,
                "period_jitter_s": period_s * 0.1,
                "motion_duration_s": motion_duration_s,
                "rest_duration_s": rest_duration_s,
                "quaternion_flip": bool(quaternion_flip),
                "noise_std": noise_std_rest,
                "noise_std_active": noise_std_active,
                "drift_rate": drift_rate,
                "drift_direction": 0.0,
                "plateau_fraction": plateau_fraction,
                "step_value_fraction": step_value_fraction,
            }
        }

        print(f"[DEBUG] {col}: plateau={plateau_fraction:.2f}, step={step_value_fraction:.2f}, active_low={active_low:.4f}, active_high={active_high:.4f}")

        realism = self._get_realism(col, data)
        if realism:
            config["realism"] = realism

        return config

    # ----- Engine fitting functions -----

    def _fit_cycle_template(self, col: str, data: np.ndarray) -> dict:
        """
        Extract real cycle templates from data for template-based generation.
        Falls back to periodic_motion if too few cycles are found.
        """
        from scipy.signal import argrelmax
        from scipy.interpolate import interp1d

        n = len(data)
        ts = self.df['timestamp'].values
        t_seconds = (ts - ts[0]) / 1000.0
        total_dur = t_seconds[-1]

        # --- Resting value and range ---
        hist, edges = np.histogram(data, bins=30)
        peak_bin = np.argmax(hist)
        resting_value = float((edges[peak_bin] + edges[peak_bin + 1]) / 2)
        active_low = float(np.percentile(data, 2))
        active_high = float(np.percentile(data, 98))
        excursion_down = (resting_value - active_low) > (active_high - resting_value)
        motion_target = active_low if excursion_down else active_high
        excursion = float(motion_target - resting_value)

        # --- Period via autocorrelation ---
        centered = data - np.mean(data)
        corr = np.correlate(centered, centered, mode='full')[n - 1:]
        if corr[0] != 0:
            corr = corr / corr[0]
        min_p = max(10, n // 50)
        max_p = n // 2
        search = corr[min_p:max_p]
        if len(search) > 3:
            peaks = argrelmax(search, order=max(3, min_p // 4))[0]
            period_samples = (peaks[0] + min_p) if len(peaks) > 0 else (int(np.argmax(search)) + min_p)
            # Episode-count check for half-period doubling
            rest_thr = abs(excursion) * 0.15
            episode_mask = np.abs(data - resting_value) >= rest_thr
            n_episodes = max(1, int(np.sum(np.diff(episode_mask.astype(int)) > 0)))
            n_expected = n / period_samples
            double_samples = 2 * period_samples
            if double_samples < len(corr) and corr[double_samples] > 0.3 and n_expected > n_episodes * 1.5:
                period_samples = double_samples
            period_s = float(np.clip(period_samples * (total_dur / n), 5.0, total_dur / 3))
        else:
            period_s = 20.0

        # --- Drift ---
        rest_threshold = abs(excursion) * 0.15
        rest_mask = np.abs(data - resting_value) < rest_threshold
        drift_rate = 0.0
        if rest_mask.sum() > 100:
            try:
                slope, intercept = np.polyfit(t_seconds[rest_mask], data[rest_mask], 1)
                drift_rate = float(slope)
                resting_value = float(intercept)
            except Exception:
                pass

        # --- Noise ---
        if rest_mask.sum() > 50:
            rest_diffs = np.diff(data[rest_mask])
            noise_std = float(max(np.std(rest_diffs) / np.sqrt(2), 0.0005))
        else:
            noise_std = float(np.std(data) * 0.02)

        # --- Extract cycle templates ---
        episode_mask = np.abs(data - resting_value) >= rest_threshold
        episode_starts = np.where(np.diff(episode_mask.astype(int)) > 0)[0]

        TEMPLATE_LEN = 200  # normalize all templates to this length

        templates = []
        if len(episode_starts) >= 4:
            for i in range(len(episode_starts) - 1):
                s = episode_starts[i]
                e = episode_starts[i + 1]
                seg_len = e - s
                # Skip cycles that are too short or too long (outliers)
                expected_samples = period_samples
                if seg_len < expected_samples * 0.5 or seg_len > expected_samples * 2.0:
                    continue
                segment = data[s:e]
                # Normalize amplitude: 0 = resting, 1 = peak excursion
                if abs(excursion) > 1e-6:
                    norm = (segment - resting_value) / excursion
                else:
                    norm = np.zeros(len(segment))
                norm = np.clip(norm, -0.5, 1.5)
                # Resample to standard length
                x_old = np.linspace(0, 1, len(norm))
                x_new = np.linspace(0, 1, TEMPLATE_LEN)
                try:
                    f = interp1d(x_old, norm, kind='linear')
                    templates.append(f(x_new).tolist())
                except Exception:
                    continue

        # Fall back to periodic_motion if too few templates
        if len(templates) < 5:
            return self._fit_periodic_motion(col, data)

        config = {
            "engine": "cycle_template",
            "params": {
                "templates": templates,
                "resting_value": resting_value,
                "excursion": excursion,
                "period_s": period_s,
                "period_jitter_s": period_s * 0.08,
                "amplitude_jitter": 0.06,
                "noise_std": noise_std,
                "drift_rate": drift_rate,
            }
        }
        print(f"[CycleTemplate] {col}: {len(templates)} templates, period={period_s:.1f}s, excursion={excursion:.4f}")

        realism = self._get_realism(col, data)
        if realism:
            config["realism"] = realism

        return config

    def _fit_constant_noise(self, col: str, data: np.ndarray,
                             cycling_states) -> dict:
        """Fit constant_noise engine parameters."""
        # Use stable tail (skip first 10%) to avoid settling spike inflating std
        n = len(data)
        stable = data[max(1, n // 10):]
        base_value = float(np.median(stable))
        noise_std  = float(np.std(stable))

        noise_std_by_state = {}
        if cycling_states is not None:
            valid_mask = (cycling_states != "unknown")
            for state_name in ["phase_on", "phase_off"]:
                mask = (cycling_states == state_name) & valid_mask
                if mask.sum() > 10:
                    noise_std_by_state[state_name] = float(np.std(data[mask]))

        config = {
            "engine": "constant_noise",
            "params": {
                "base_value": base_value,
                "noise_std_by_state": noise_std_by_state,
                "default_noise_std": noise_std,
            }
        }

        # Add realism for known column types
        realism = self._get_realism(col, data)
        if realism:
            config["realism"] = realism

        return config

    def _fit_state_aware(self, col: str, data: np.ndarray,
                          cycling_states) -> Optional[dict]:
        """
        Check if this column has meaningfully different behavior in ON vs OFF.
        If the std ratio between phases is > 1.5, it's state-aware.
        """
        valid_mask = (cycling_states != "unknown")
        on_mask = (cycling_states == "phase_on") & valid_mask
        off_mask = (cycling_states == "phase_off") & valid_mask

        if on_mask.sum() < 50 or off_mask.sum() < 50:
            return None

        on_std = float(np.std(data[on_mask]))
        off_std = float(np.std(data[off_mask]))
        on_mean = float(np.mean(data[on_mask]))
        off_mean = float(np.mean(data[off_mask]))

        # Compressor vibration builds up over an ON cycle (rolling_std ramps
        # ~0.02 -> 0.04 across a phase in the real data), so also measure how
        # much the mean and the std drift from the start to the end of the
        # average ON run.
        value_ramp_on, noise_ramp_on = self._measure_on_phase_ramp(
            data, cycling_states
        )

        # Level shifts by phase (e.g. rolling_std sits at ~0.012 in OFF and
        # ~0.035 in ON): a shared base_value would park both phases at the
        # global mean, so use the cycling engine with a mean per state.
        pooled_std = max(on_std, off_std) + 1e-10
        mean_shift = abs(on_mean - off_mean)
        if mean_shift > pooled_std * 0.5:
            params = {
                "value_by_state": {
                    "phase_on": on_mean,
                    "phase_off": off_mean,
                },
                "noise_std_by_state": {
                    "phase_on": on_std,
                    "phase_off": off_std,
                },
                "default_value": float(np.mean(data)),
                "default_noise_std": float(np.std(data)),
            }
            if abs(value_ramp_on) > on_std * 0.5:
                params["ramp_by_state"] = {"phase_on": value_ramp_on}
            return {
                "engine": "cycling",
                "params": params,
                **({"realism": r} if (r := self._get_realism(col, data)) else {}),
            }

        ratio = max(on_std, off_std) / (min(on_std, off_std) + 1e-10)
        if ratio < 1.5:
            return None

        config = {
            "engine": "constant_noise",
            "params": {
                "base_value": float(np.mean(data)),
                "noise_std_by_state": {
                    "phase_on": on_std,
                    "phase_off": off_std,
                },
                "default_noise_std": float(np.std(data)),
            }
        }
        if abs(noise_ramp_on) > on_std * 0.15:
            config["params"]["noise_ramp_by_state"] = {"phase_on": noise_ramp_on}

        realism = self._get_realism(col, data)
        if realism:
            config["realism"] = realism

        return config

    def _measure_on_phase_ramp(self, data: np.ndarray,
                               cycling_states) -> tuple:
        """
        Average start-to-end drift of mean and std within phase_on runs.
        Returns (value_span, noise_span): how much the mean / std grow from
        the first third to the last third of a typical ON phase.

        Runs are split at logging gaps: with gated logging, consecutive
        samples on either side of a 12-minute gap belong to different ON
        phases even though their labels are adjacent in the array.
        """
        t_sec = (self.df['timestamp'].values - self.df['timestamp'].values[0]) / 1000.0
        runs = []
        start = None
        for i, lab in enumerate(cycling_states):
            gap_break = (start is not None and i > 0
                         and (t_sec[i] - t_sec[i - 1]) > 60.0)
            if gap_break:
                runs.append((start, i))
                start = i if lab == "phase_on" else None
                continue
            if lab == "phase_on" and start is None:
                start = i
            elif lab != "phase_on" and start is not None:
                runs.append((start, i))
                start = None
        if start is not None:
            runs.append((start, len(cycling_states)))

        # Compare the first 10% of a phase against its 60-90% plateau: the
        # vibration ramps up and levels off there before dropping at the end,
        # so head-vs-tail thirds systematically underestimate the swing.
        value_spans, noise_spans = [], []
        for s, e in runs:
            if (t_sec[e - 1] - t_sec[s]) < 300:  # need >=5 min for stable stats
                continue
            seg = data[s:e]
            head = seg[:max(30, len(seg) // 10)]
            plateau = seg[int(len(seg) * 0.6):int(len(seg) * 0.9)]
            if len(plateau) < 30:
                continue
            value_spans.append(float(np.mean(plateau) - np.mean(head)))
            noise_spans.append(float(np.std(plateau) - np.std(head)))

        if len(value_spans) < 2:
            return 0.0, 0.0
        return float(np.median(value_spans)), float(np.median(noise_spans))

    def _fit_gradual_curve(self, col: str, data: np.ndarray,
                            start_val: float, cycling_states) -> dict:
        """
        Fit LINEAR drift parameters (engine uses linear, not exponential).

        rate is now in units-per-second (climb speed), computed simply as
        total_change / duration. This produces a steady climb that, combined with
        stickiness + quantization, yields a realistic stair-step instead of an
        exponential curve that flattens near the target.
        """
        n = len(data)
        ts = self.df['timestamp'].values
        t_seconds = (ts - ts[0]) / 1000.0
        duration_s = float(t_seconds[-1]) if t_seconds[-1] > 0 else 1.0

        # Target = average of the final 10% (where the signal ends up).
        target = float(np.mean(data[int(n * 0.9):]))

        # Linear rate = total change / duration (units per second).
        total_change = abs(target - start_val)
        rate = total_change / duration_s if duration_s > 0 else 0.0

        # Noise: residual after removing rolling-mean trend.
        rolling = pd.Series(data).rolling(min(100, n // 5), center=True).mean()
        residual = data - rolling.values
        noise_std = float(np.nanstd(residual))

        # --- Auto-detect stickiness & quantization from the real data ---
        # Stickiness = fraction of consecutive-identical samples. A sticky XDK column
        # (humidity, mag) holds its reading for long stretches. We feed that fraction
        # straight into the engine so the synthetic output holds values the same way.
        diffs_raw = np.diff(data)
        sticky_frac = float(np.mean(diffs_raw == 0)) if len(diffs_raw) else 0.0

        realism_check = self._get_realism(col, data)
        q_step = 0.0
        if realism_check and realism_check.get("quantization_step"):
            q_step = float(realism_check["quantization_step"])

        # Only treat as a stair-step column when it's genuinely quantized & sticky.
        # (Large-step columns like light go through event_spike, not here.)
        use_stairs = (sticky_frac > 0.2 and 0 < q_step <= 2.0)
        stickiness = sticky_frac if use_stairs else 0.0
        quant_for_engine = q_step if use_stairs else 0.0

        # --- Detect pure drift vs approach-then-plateau ---
        # Pure drift (e.g. pressure falling for days): the signal keeps moving in one
        # direction with NO plateau. Approach-plateau (e.g. humidity 60->68 then holds):
        # the last chunk flattens out. We compare the slope of the first half vs the
        # last 20%. If the last 20% is still moving at a similar rate, it's drifting.
        drift_slope = 0.0
        drift_floor = None
        drift_ceil = None
        if not use_stairs and n > 200:
            seg = max(50, n // 5)
            early = float(np.mean(data[:seg]))
            mid   = float(np.mean(data[n//2 - seg//2 : n//2 + seg//2]))
            late  = float(np.mean(data[-seg:]))
            t_early = float(np.mean(t_seconds[:seg]))
            t_late  = float(np.mean(t_seconds[-seg:]))
            overall_slope = (late - early) / (t_late - t_early + 1e-9)
            # last-20% slope
            late_seg = max(50, n // 5)
            la = float(np.mean(data[-late_seg:]))
            lb = float(np.mean(data[-2*late_seg:-late_seg])) if 2*late_seg < n else mid
            ta = float(np.mean(t_seconds[-late_seg:]))
            tb = float(np.mean(t_seconds[-2*late_seg:-late_seg])) if 2*late_seg < n else t_early
            late_slope = (la - lb) / (ta - tb + 1e-9)
            # If still moving in the last 20% at >40% of overall slope -> pure drift.
            if abs(overall_slope) > 1e-6 and abs(late_slope) > 0.4 * abs(overall_slope):
                drift_slope = overall_slope
                # common-sense clamp: allow it to keep going but not run off forever.
                # bound = 3x the observed total change beyond the data range.
                span = abs(late - early)
                if drift_slope < 0:
                    drift_floor = early - 4.0 * span
                else:
                    drift_ceil = early + 4.0 * span

        # If cycling is detected, differentiate targets per phase
        target_by_state = {"normal": target}
        rate_by_state = {"normal": rate}

        if cycling_states is not None:
            valid = (cycling_states != "unknown")
            for phase in ["phase_on", "phase_off"]:
                mask = (cycling_states == phase) & valid
                if mask.sum() > 50:
                    # Check trend direction in each phase
                    phase_data = data[mask]
                    phase_diffs = np.diff(phase_data)
                    avg_change = np.mean(phase_diffs)
                    if avg_change < 0:
                        # Cooling during this phase
                        target_by_state[phase] = target - abs(target - start_val) * 0.1
                    else:
                        target_by_state[phase] = target + abs(target - start_val) * 0.1
                    rate_by_state[phase] = rate

        config = {
            "engine": "gradual_curve",
            "params": {
                "initial_value": start_val,
                "target_by_state": target_by_state,
                "rate_by_state": rate_by_state,
                "noise_std": noise_std,
                "default_target": target,
                "default_rate": rate,
                "stickiness": stickiness,
                "quantization_step": quant_for_engine,
            }
        }

        # Pure-drift columns (pressure): override with constant slope + clamp, and add
        # OU wander so the drift looks natural (wobbly) rather than a straight ramp.
        if drift_slope != 0.0:
            config["params"]["drift_slope"] = drift_slope
            if drift_floor is not None:
                config["params"]["drift_floor"] = drift_floor
            if drift_ceil is not None:
                config["params"]["drift_ceil"] = drift_ceil
            config["params"]["ou_noise_scale"] = 3.0
            config["params"]["ou_tau_s"] = 900.0

        realism = self._get_realism(col, data)
        if realism:
            config["realism"] = realism

        return config

    def _fit_event_spike(self, col: str, data: np.ndarray) -> dict:
        """
        Detect and parameterize discrete spike events.
        """
        diffs = np.abs(np.diff(data))
        median_diff = np.median(diffs)
        if median_diff == 0:
            median_diff = np.mean(diffs) + 1e-10
        threshold = median_diff * 10

        # Find event start points
        jump_indices = np.where(diffs > threshold)[0]

        # Group nearby jumps into events (within 20 samples = same event)
        events = []
        if len(jump_indices) > 0:
            ts = self.df['timestamp'].values
            t_seconds = (ts - ts[0]) / 1000.0

            event_groups = []
            current_group = [jump_indices[0]]
            for idx in jump_indices[1:]:
                if idx - current_group[-1] < 20:
                    current_group.append(idx)
                else:
                    event_groups.append(current_group)
                    current_group = [idx]
            event_groups.append(current_group)

            for group in event_groups:
                start_idx = group[0]
                end_idx = group[-1]
                t_start = float(t_seconds[start_idx])
                duration = float(t_seconds[end_idx] - t_seconds[start_idx]) + 0.5

                # Magnitude
                event_data = data[start_idx:end_idx+5]
                baseline_before = float(np.mean(data[max(0,start_idx-20):start_idx]))
                magnitude = float(np.max(np.abs(event_data - baseline_before)))

                # Level shift?
                if end_idx + 20 < len(data):
                    baseline_after = float(np.mean(data[end_idx+5:end_idx+25]))
                    level_shift = float(baseline_after - baseline_before)
                else:
                    level_shift = 0.0

                events.append({
                    "t_start": t_start,
                    "duration": max(0.5, duration),
                    "magnitude": magnitude,
                    "level_shift": level_shift if abs(level_shift) > median_diff * 3 else 0.0,
                    "type": "decaying",
                })

        # Baseline from stable periods
        stable_mask = diffs < threshold
        if stable_mask.sum() > 10:
            baseline = float(np.mean(data[:-1][stable_mask]))
            baseline_noise = float(np.std(data[:-1][stable_mask]))
        else:
            baseline = float(np.mean(data))
            baseline_noise = float(np.std(data)) * 0.1

        config = {
            "engine": "event_spike",
            "params": {
                "baseline": baseline,
                "baseline_noise_std": baseline_noise,
                "events": events,
            }
        }

        realism = self._get_realism(col, data)
        if realism:
            config["realism"] = realism

        return config

    # ----- Realism estimation -----

    def _get_realism(self, col: str, data: np.ndarray) -> Optional[dict]:
        """Estimate sensor realism parameters from the data."""
        realism = {}

        # Detect quantization step
        unique_diffs = np.unique(np.abs(np.diff(data)))
        unique_diffs = unique_diffs[unique_diffs > 0]
        if len(unique_diffs) > 0:
            min_step = unique_diffs[0]
            # Check if most diffs are multiples of this step
            if min_step > 0.5:  # only for clearly quantized data
                remainders = np.mod(unique_diffs[:20], min_step)
                if np.mean(remainders < min_step * 0.1) > 0.7:
                    realism["quantization_step"] = float(min_step)

        # Fine quantization: XDK accel reads only a handful of levels
        # (acceleration_z is literally {0.9, 1.0}). The min_step > 0.5 guard
        # above misses steps like 0.1, so also treat a column with very few
        # distinct values as quantized at the smallest level spacing.
        if "quantization_step" not in realism and len(data) > 1000:
            uniques = np.unique(data[~np.isnan(data)])
            if 2 <= len(uniques) <= 25:
                level_gaps = np.diff(uniques)
                realism["quantization_step"] = float(np.min(level_gaps))
                # The sensor only ever emits these levels, so keep the
                # synthetic within the observed range too.
                realism["clip_min"] = float(uniques[0])
                realism["clip_max"] = float(uniques[-1])

        # Column-specific overrides based on known XDK behavior
        if col == 'temperature':
            realism.setdefault("quantization_step", 10)
            realism["settling_samples"] = 10
            realism["settling_noise_factor"] = float(np.std(data) * 0.5)
        elif col == 'humidity':
            realism["quantization_step"] = 1
            realism["clip_min"] = 0
            realism["clip_max"] = 100
        elif col == 'pressure':
            realism["quantization_step"] = 1
        elif col == 'light':
            realism["quantization_step"] = 2880
            realism["clip_min"] = 0
        elif col == 'rolling_std':
            # A rolling std can never be negative
            realism["clip_min"] = 0

        return realism if realism else None


def fit_from_real_data(filepath: str, domain_hints: dict = None,
                       encoding: str = 'utf-8') -> dict:
    fitter = AutoFitter(filepath, encoding=encoding)
    return fitter.fit(domain_hints)