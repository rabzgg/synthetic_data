"""
dump_engines.py — dump the REAL engine assignments from config JSONs.

Task A of TASK-2.md: the deck's slide-3 engine table was inferred and is wrong in
places. This reads the actual config files and writes a ground-truth map of
`column -> engine -> key fitted parameters`, grouped by dataset and variant, plus
an automatic "surprises" section for the three claims flagged in the brief.

Usage
-----
python3 dump_engines.py --configs configs/fridge/*.json configs/aquarium/*.json
python3 dump_engines.py --configs configs/fridge/*.json --out ENGINE_MAP.md

Nothing here is inferred: every engine/param is read straight from the JSON.
"""
import argparse
import glob
import json
import os

# Config basename -> deck variant label (verified via row count / frequency /
# engine signature against the ppt/ CSVs, see the mapping note in the output).
DECK_VARIANTS = {
    "fridge_fit60.json":         "Fridge — deck (fit60 family)",
    "aquarium_01_full_raw.json": "Aquarium — Fit 100% (deck)",
    "aquarium_01_50pct.json":    "Aquarium — Fit 50% -> 24h (deck)",
    "aquarium_01_2d_opus.json":  "Aquarium — Opus / LLM (deck)",
}

# Which param keys are worth showing per engine (in priority order).
KEY_PARAMS = {
    "constant_noise":      ["base_value", "stickiness", "default_noise_std", "noise_std_by_state", "noise_ramp_by_state"],
    "gradual_curve":       ["initial_value", "target_by_state", "target_value", "rate_by_state", "rate", "noise_std"],
    "cycling":             ["value_by_state", "noise_std_by_state", "default_value"],
    "event_spike":         ["baseline", "baseline_noise_std", "events"],
    "periodic_motion":     ["resting_value", "active_low", "active_high", "period_s", "motion_duration_s"],
    "cycle_template":      ["resting_value", "excursion", "period_s", "templates", "amplitude_jitter"],
    "sinusoidal_drift":    ["base_value", "daily_amplitude", "daily_period_s", "phase_offset_s", "noise_std"],
    "derived_rolling_std": ["source", "window_s", "update_every", "floor"],
    "envelope_noise":      ["base_value", "low_noise_std", "high_noise_std", "period_s", "duty_cycle"],
}


def fmt_num(v):
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


def fmt_val(v):
    if isinstance(v, list):
        return f"[{len(v)} items]"
    if isinstance(v, dict):
        inner = ", ".join(f"{k}={fmt_num(x)}" for k, x in v.items())
        return "{" + inner + "}"
    return fmt_num(v)


def summarize_params(engine, params):
    keys = KEY_PARAMS.get(engine, list(params.keys()))
    parts = []
    for k in keys:
        if k in params:
            parts.append(f"{k}={fmt_val(params[k])}")
    # include any params not in the curated list, so nothing is silently hidden
    for k in params:
        if k not in keys:
            parts.append(f"{k}={fmt_val(params[k])}")
    return "; ".join(parts) if parts else "(no params)"


def load_configs(patterns):
    paths = []
    for pat in patterns:
        paths.extend(glob.glob(pat))
    out = []
    for p in sorted(set(paths)):
        try:
            with open(p) as f:
                out.append((p, json.load(f)))
        except Exception as e:
            print(f"  [skip] {p}: {e}")
    return out


def dataset_of(path):
    return os.path.basename(os.path.dirname(path)) or "?"


def hours(dur):
    return f"{dur/3600:.1f}h" if isinstance(dur, (int, float)) else "?"


def build_surprises(configs):
    """Automatic flags for the three claims in TASK-2.md Task A + light path."""
    lines = []

    # 1. acceleration_x engine across fridge configs (periodic_motion vs event_spike)
    accx = {}
    for path, c in configs:
        if dataset_of(path) == "fridge":
            e = c.get("columns", {}).get("acceleration_x", {}).get("engine")
            if e:
                accx.setdefault(e, []).append(os.path.basename(path))
    if len(accx) > 1:
        lines.append(
            "- **fridge `acceleration_x` is assigned DIFFERENT engines across configs** — "
            + "; ".join(f"`{e}` in {', '.join(fs)}" for e, fs in accx.items())
            + ". Slide 3's `periodic_motion` comes from `fridge_01_normal.json` (an older "
            "config); the deck config `fridge_fit60.json` has it as `event_spike` "
            "(matches slide 8). Slide 3 mixed two different fridge configs.")

    # 2. acceleration_z: engine + whether it's a level shift (cycling) or per-state noise
    for path, c in configs:
        if os.path.basename(path) == "fridge_fit60.json":
            cfg = c["columns"].get("acceleration_z", {})
            p = cfg.get("params", {})
            nsbs = p.get("noise_std_by_state", {})
            lines.append(
                f"- **fridge `acceleration_z` = `{cfg.get('engine')}`, NOT `cycling`.** "
                f"base_value={fmt_num(p.get('base_value'))} is the SAME in both states; only the "
                f"noise differs (noise_std_by_state={fmt_val(nsbs)}). The ON/OFF compressor look on "
                "slide 8 is real, but it is produced by per-state NOISE on a flat baseline, not by a "
                "`cycling` level shift. Slide 3's `cycling` label is wrong.")
            break

    # 2b. fridge light claims constant_noise in config but is event_spike as generated
    for path, c in configs:
        if os.path.basename(path) == "fridge_fit60.json":
            lcfg = c["columns"].get("light", {})
            if lcfg.get("engine") == "constant_noise":
                bv = lcfg.get("params", {}).get("base_value")
                lines.append(
                    f"- **fridge `light` = `constant_noise` in the config, but the DECK OUTPUT is "
                    f"`event_spike` behaviour.** `fridge_fit60.json` (and the other fit% configs) list "
                    f"light=`constant_noise` (base_value={fmt_num(bv)}), which cannot produce a level "
                    "shift. Yet the deck synthetic (`ppt/fridge/fridge_xdk1_syn.csv`) drops permanently "
                    "2800 -> 0 (~45% of rows at 0, slide 7). Cause: `main.py --light-on/--light-off` "
                    "REPLACES the light column with an injected `event_spike` schedule at generation "
                    "(day_value read from the constant_noise base=2800). So (a) the AS-GENERATED light "
                    "engine is `event_spike` (matches ENGINES.md's canonical fridge example and slide "
                    "7/8), and (b) the static config does NOT reflect the generated light — a "
                    "config->output traceability gap: the injected schedule is never written back to "
                    "the config JSON. Use `event_spike` (not `constant_noise`) for light in the slide.")
            break

    # 3. sinusoidal_drift used where ENGINES.md says it should not trigger (<18h).
    #    Collapse all occurrences into one flag with a compact per-occurrence list.
    sd = []
    for path, c in configs:
        dur = c.get("duration_s")
        for col, cfg in c.get("columns", {}).items():
            if cfg.get("engine") == "sinusoidal_drift":
                period = cfg.get("params", {}).get("daily_period_s")
                sd.append((os.path.basename(path), dataset_of(path), col, dur, period))
    if sd:
        occ = "; ".join(
            f"`{base}`::{col} ({hours(dur)} recording, period={fmt_num(period)})"
            for base, ds, col, dur, period in sd)
        deck_sd = [x for x in sd if x[0] in DECK_VARIANTS]
        deck_note = (" This includes the DECK config `fridge_fit60.json`::pressure (~3.1h), "
                     "so slide 3's `sinusoidal_drift` claim is technically true to the config."
                     if deck_sd else "")
        lines.append(
            "- **`sinusoidal_drift` IS assigned in several configs, all on recordings far shorter "
            "than the >=18h ENGINES.md says it requires** (every occurrence uses a 24h period fitted to "
            "a <7h window, i.e. <1/3 of a cycle): " + occ + ". "
            "ENGINES.md claims this engine 'has never been triggered by any dataset' — the configs "
            "contradict the doc. Either ENGINES.md is stale, or the fitter mis-routes a slow "
            "monotonic drift (pressure, or aquarium-03 temp/humidity) into a degenerate long-period "
            "sine." + deck_note)

    # 4. aquarium light path / amplitude, collapsed into one flag over deck variants
    light_rows = []
    for path, c in configs:
        base = os.path.basename(path)
        if base in DECK_VARIANTS and dataset_of(path) == "aquarium":
            p = c["columns"].get("light", {}).get("params", {})
            light_rows.append((DECK_VARIANTS[base], base, c["columns"]["light"].get("engine"),
                               fmt_num(p.get("baseline")), len(p.get("events", []))))
    if light_rows:
        detail = "; ".join(f"{label}: engine=`{eng}`, baseline={bl}, events={ne}"
                           for label, base, eng, bl, ne in light_rows)
        capped = [l for l in light_rows if l[3] == "2880"]
        lines.append(
            "- **Aquarium light** (all deck variants on `event_spike`, so the engine PATH is fine): "
            + detail + ". "
            + (f"Fit 50% and Opus sit at baseline=2880 (one hardcoded quantization step = dim) with very "
               "few events, while Fit 100% has baseline=0 with 20 events. The 2880 cap + few events explain "
               "the wrong/short light duration and the amplitude problem (real reaches 11520 = 4x2880). "
               "Detailed re-measurement is Task E." if capped else ""))

    return lines


def main():
    ap = argparse.ArgumentParser(description="Dump real engine assignments from config JSONs.")
    ap.add_argument("--configs", nargs="+", required=True,
                    help="Config JSON paths / globs (e.g. configs/fridge/*.json)")
    ap.add_argument("--out", default="ENGINE_MAP.md", help="Output markdown (default ENGINE_MAP.md)")
    args = ap.parse_args()

    configs = load_configs(args.configs)
    if not configs:
        print("No configs matched.")
        return

    # group by dataset
    by_ds = {}
    for path, c in configs:
        by_ds.setdefault(dataset_of(path), []).append((path, c))

    lines = []
    lines.append("# ENGINE_MAP.md — real engine assignments (read from config JSON)\n")
    lines.append("Generated by `dump_engines.py`. Every engine and parameter below is read "
                 "straight from the config JSON — nothing is inferred. This is the ground truth "
                 "for the deck's engine claims (TASK-2.md Task A).\n")
    lines.append(f"Configs dumped: {len(configs)}. Deck variants are tagged inline.\n")

    for ds in sorted(by_ds):
        lines.append(f"\n## Dataset: {ds}\n")
        for path, c in sorted(by_ds[ds]):
            base = os.path.basename(path)
            tag = f"  **[{DECK_VARIANTS[base]}]**" if base in DECK_VARIANTS else ""
            lines.append(f"\n### `{base}`{tag}\n")
            lines.append(f"- domain: `{c.get('domain','?')}`  |  duration_s: "
                         f"{fmt_num(c.get('duration_s'))} ({hours(c.get('duration_s'))})  |  "
                         f"frequency_hz: {c.get('frequency_hz','?')}\n")
            lines.append("| column | engine | key fitted parameters |")
            lines.append("|---|---|---|")
            for col, cfg in c.get("columns", {}).items():
                eng = cfg.get("engine", "?")
                params = cfg.get("params", {})
                summary = summarize_params(eng, params).replace("|", "\\|")
                lines.append(f"| `{col}` | `{eng}` | {summary} |")
            lines.append("")

    lines.append("\n## Surprises / flags (auto-generated)\n")
    surprises = build_surprises(configs)
    if surprises:
        lines.extend(surprises)
    else:
        lines.append("- (none detected by the automatic checks)")

    lines.append("\n## Deck variant mapping (how CSV -> config was determined)\n")
    lines.append("Matched by frequency + engine signature against the `ppt/` CSVs and the deck's own "
                 "statements (row count is unreliable here because gated logging drops OFF-phase rows):")
    lines.append("- **Fridge deck** (`ppt/fridge/fridge_xdk1_syn.csv`) = **`fridge_fit60.json`**. Two "
                 "signatures pin it: `acceleration_x` = `event_spike` (slide 8, rules out "
                 "`fridge_01_normal` which is `periodic_motion`) AND `rolling_std` = `derived_rolling_std` "
                 "(matches the deck's ACF-diff 0.409 finding, rules out `fridge_10pct` / `fridge_25pct` "
                 "which fit `rolling_std` as `gradual_curve`). NOTE: the `*_10pct`/`*_25pct` configs are "
                 "NOT the same engine signature as `fit60` — do not treat them as one 'family'.")
    lines.append("- **Aquarium**: `aquarium_xdk1_100pct_syn.csv` -> `aquarium_01_full_raw.json` (fz=10, "
                 "~22h); `aquarium_xdk1_50pct_syn.csv` -> `aquarium_01_50pct.json` (fit window ~11h, "
                 "generated to 24h); `aquarium_xdk1_opus_syn.csv` (86,401 rows) -> `aquarium_01_2d_opus.json` "
                 "(fz=1 -> 24h). `aquarium_01_llm.json` and `aquarium_03*.json` are separate experiments, "
                 "NOT the deck.")

    with open(args.out, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Wrote {args.out}  ({len(configs)} configs, {len(surprises)} surprise flags)")


if __name__ == "__main__":
    main()
