"""
legacy.py — the older statistical path for the UI page "Start from a real CSV (legacy)":
real CSV -> AutoFitter (core/generator.py) -> JSON config -> SyntheticXDKGenerator -> synthetic CSV.

The legacy engine is only called here, not merged into the sensor-agnostic generator. Each column is
fitted on its own, so columns are not linked by physics. It was built for XDK recordings at about
10 Hz: text columns are left out before fitting, and data logged slower than one row every 2 s is
refused (the fitter rounds its rate to 0 Hz and cannot generate it).
"""
import io
import json
import os
import re
import zipfile

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, "data", "arm6", "original", "sensor_1.csv.gz")

ENGINE_TEXT = {                       # engine in the JSON: (name on screen, what it means)
    "constant_noise": ("Constant noise", "a level with noise"),
    "gradual_curve": ("Gradual curve", "a slow curve"),
    "sinusoidal_drift": ("Sinusoidal drift", "a slow sine drift"),
    "periodic_motion": ("Periodic motion", "a repeating motion"),
    "event_spike": ("Event spike", "a baseline with short events"),
    "cycling": ("Cycling", "on and off cycles"),
    "cycle_template": ("Cycle template", "a repeated cycle shape"),
    "envelope_noise": ("Envelope noise", "noise with a changing size"),
    "derived_rolling_std": ("Rolling spread", "the spread of another column"),
}


class LegacyError(ValueError):
    """A CSV the legacy fit cannot handle; the message is for the screen."""


def prepare(raw: bytes, out_dir: str) -> tuple:
    """Write the numeric part of an uploaded CSV for the fitter. Returns (path, left_out_columns)."""
    try:
        df = pd.read_csv(io.BytesIO(raw), compression="gzip" if raw[:2] == b"\x1f\x8b" else None)
    except Exception as e:
        raise LegacyError(f"The file could not be read as a CSV ({type(e).__name__}).") from e
    if "timestamp" not in df.columns:
        raise LegacyError("The CSV needs a column named timestamp.")
    text = [c for c in df.columns if c != "timestamp" and not pd.api.types.is_numeric_dtype(df[c])]
    df = df.drop(columns=text)
    if len(df.columns) < 2:
        raise LegacyError("The CSV has no numeric columns to fit.")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "real_numeric.csv")
    df.to_csv(path, index=False)
    return path, text


def fit(path: str) -> dict:
    from core.generator import fit_from_real_data
    cfg = fit_from_real_data(path)
    if not cfg.get("frequency_hz"):
        step_s = float(np.median(np.diff(minutes_from_start(pd.read_csv(path)["timestamp"])))) * 60.0
        raise LegacyError(f"This CSV logs one row every {step_s:g} s. The legacy fit only works for data "
                          "logged at least every 2 s (it was built for 10 Hz recordings).")
    return cfg


def engines(cfg: dict) -> pd.DataFrame:
    rows = []
    for c, e in cfg["columns"].items():
        name, means = ENGINE_TEXT.get(e["engine"], (e["engine"].replace("_", " ").capitalize(), ""))
        rows.append({"column": c, "engine": name, "what it means": means})
    return pd.DataFrame(rows)


def generate(cfg: dict, minutes: float, seed: int) -> pd.DataFrame:
    from core.generator import SyntheticXDKGenerator
    return SyntheticXDKGenerator(dict(cfg, duration_s=float(minutes) * 60.0), seed=int(seed)).generate()


def minutes_from_start(ts: pd.Series) -> np.ndarray:
    from core.generator import AutoFitter
    ms = np.asarray(AutoFitter._timestamps_as_ms(ts), float)
    if np.nanmedian(np.diff(ms)) < 10:                  # seconds, as the fitter reads them
        ms = ms * 1000.0
    return (ms - ms[0]) / 60000.0


def plot(real_path: str, syn: pd.DataFrame, columns: list):
    """One panel per column: the real recording and the synthetic copy on the same time axis, over the
    synthetic duration (the real data after that is not drawn, so both are seen at the same scale)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from core.output.plot import INK, PALETTE, STYLE, _register_fonts
    real = pd.read_csv(real_path)
    tr, ts = minutes_from_start(real["timestamp"]), minutes_from_start(syn["timestamp"])
    end = ts[-1]
    keep = tr <= end
    _register_fonts()
    with plt.style.context([STYLE, {"font.family": ["Rajdhani", "DejaVu Sans"]}]):
        fig, axes = plt.subplots(len(columns), 1, figsize=(11, 1.5 * len(columns) + 0.9), sharex=True, squeeze=False)
        for ax, c in zip(axes[:, 0], columns):
            ax.plot(tr[keep], real[c].to_numpy()[keep], color=INK, lw=0.7, label="real")
            ax.plot(ts, syn[c], color=PALETTE[0], lw=0.7, alpha=0.85, label="synthetic")
            ax.set_ylabel(c, fontsize=11)
            ax.set_xlim(0, end)
        axes[-1, 0].set_xlabel("minutes from the start", fontsize=11)
        fig.suptitle(f"Real and synthetic, first {end:.0f} min", fontsize=15, color=INK)
        fig.legend(*axes[0, 0].get_legend_handles_labels(), loc="upper right", ncol=2, fontsize=11, frameon=False)
        fig.tight_layout(rect=(0, 0, 1, 1 - 0.5 / fig.get_figheight()))
    return fig


def base_name(filename: str) -> str:
    """The uploaded file's name without .csv / .gz, safe for file names: "sensor_1.csv.gz" -> "sensor_1"."""
    stem = os.path.basename(filename or "")
    for ext in (".gz", ".csv"):
        if stem.lower().endswith(ext):
            stem = stem[: -len(ext)]
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._") or "data"


def zip_files(syn: pd.DataFrame, cfg: dict, base: str) -> bytes:
    """<base>_synthetic.csv and <base>_config.json, named after the real CSV."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{base}_synthetic.csv", syn.to_csv(index=False))
        z.writestr(f"{base}_config.json", json.dumps(cfg, indent=2))
    return buf.getvalue()
