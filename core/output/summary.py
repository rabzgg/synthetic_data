"""
summary.py — a neutral summary of one device file, per column, read from the CSV and the manifest
only (like the gate): what the synthetic dataset of a client looks like before their real CSV exists.

    rows                   rows in the file
    sample_rate_hz         1 / the device's sample interval
    unit                   the column's unit as written ("counts" for raw counts)
    min, max               of the values as written (numeric columns)
    bits                   readings: ceil(log2(span / resolution + 1)) from the sensor's range and resolution
    noise_over_resolution  readings: the part's noise sd at the ODR in use / its resolution
    odr_hz, bandwidth_hz   readings: the output data rate and bandwidth in use (their sources are in the manifest)
    generic                readings: true when the column comes from a generic part (every value an ASSUMPTION)
"""
import json

import numpy as np
import pandas as pd


def _v(p):
    return p["value"] if isinstance(p, dict) and "value" in p else p


def summary(csv_path, manifest_path) -> dict:
    with open(manifest_path) as fh:
        man = json.load(fh)
    df = pd.read_csv(csv_path)
    dev = man["device"]
    rate = 1.0 / float(_v(dev["features"].get("sample_interval_s", {"value": 1})))
    readings = dev.get("reading_columns", {})
    cols = {}
    for c in df.columns[2:]:
        x = df[c]
        e = {"rows": int(len(x)), "sample_rate_hz": round(rate, 6)}
        num = pd.api.types.is_numeric_dtype(x)
        if num and len(x):
            e["min"], e["max"] = float(np.nanmin(x)), float(np.nanmax(x))
        r = readings.get(c)
        if r:
            e.update({"kind": "reading", "quantity": r["quantity"], "unit": "counts" if r["raw_counts"] else r["unit"],
                      "part": r["part"], "generic": r["generic"], "bits": r["bits"],
                      "noise_over_resolution": round(r["noise_sd"] / r["resolution"], 3),
                      "odr_hz": r.get("odr_hz"), "bandwidth_hz": r.get("bandwidth_hz")})
        else:
            e["kind"] = "logic"
            if not num:
                e["values"] = sorted(map(str, pd.unique(x.dropna())))[:20]
        cols[c] = e
    return {"device": dev.get("slug"), "scenario": man["scenario"]["name"], "seed": man["seed"], "rows": int(len(df)),
            "sample_rate_hz": round(rate, 6), "columns": cols}
