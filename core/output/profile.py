"""
profile.py — a data profile of one device file, per column: how many bits a sample needs, how big
the noise is against the resolution, how often a row repeats the one before, and how much gzip
shrinks the column as CSV text and as raw counts in binary.

It is a rough benchmark for pre-sales ("how compressible could the client's data be"), with gzip
(DEFLATE), NOT the Bitteiler algorithm. Read from the CSV and the manifest only, like the gate.

    bits                   readings: ceil(log2(span / resolution + 1)) from the sensor's range and
                           resolution; other columns: ceil(log2(distinct values seen)) (bits_from: observed)
    noise_over_resolution  the part's noise_sd / resolution (readings only); below about 0.5 a quiet
                           signal sits on one code, above 1 every row tends to differ
    repeat_fraction        rows whose value equals the row before
    csv_bytes / csv_gzip_bytes / csv_ratio          the column as CSV text, before and after gzip
                                                    (ratio = raw / gzip; higher = shrinks more)
    bin_bytes / bin_gzip_bytes / bin_ratio          readings as raw counts round(value / resolution) in
                                                    the smallest integer type that holds the sensor's range
    packed_bytes           rows × bits / 8: the counts bit-packed, before any compression
"""
import gzip
import json

import numpy as np
import pandas as pd

NOTE = ("Rough benchmark: gzip (DEFLATE, level 9) on each column alone and on the whole CSV. It is NOT "
        "the Bitteiler algorithm and says nothing about it; it gives an order of magnitude for this "
        "synthetic data.")


def _gz(b: bytes) -> int:
    return len(gzip.compress(b, compresslevel=9, mtime=0))


def _int_type(lo: int, hi: int):
    for t in (np.int8, np.uint8, np.int16, np.uint16, np.int32, np.uint32, np.int64):
        if np.iinfo(t).min <= lo and hi <= np.iinfo(t).max:
            return t
    return np.int64


def _counts(x: np.ndarray, res: float) -> np.ndarray:
    return np.round(x / res).astype(np.int64)


def profile(csv_path, manifest_path) -> dict:
    with open(manifest_path) as fh:
        man = json.load(fh)
    raw = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    with open(csv_path, "rb") as fh:
        whole = fh.read()
    dev = man["device"]
    readings = dev.get("reading_columns", {})
    back = {name: (sc, off) for c, (name, sc, off) in (dev.get("output_transforms") or {}).items()}
    n = len(raw)
    cols, bin_total, bin_gz_total = {}, 0, 0
    for c in raw.columns[2:]:
        s = raw[c]
        text = ("\n".join(s) + "\n").encode()
        e = {"rows": n, "csv_bytes": len(text), "csv_gzip_bytes": _gz(text)}
        e["csv_ratio"] = round(e["csv_bytes"] / e["csv_gzip_bytes"], 2) if e["csv_gzip_bytes"] else None
        e["repeat_fraction"] = round(float((s.values[1:] == s.values[:-1]).mean()), 4) if n > 1 else 0.0
        r = readings.get(c)
        if r:
            x = pd.to_numeric(s, errors="coerce").to_numpy(float)
            if r["raw_counts"]:
                k = x.astype(np.int64)
            else:
                sc, off = back.get(c, (1.0, 0.0))
                k = _counts((x - off) / sc, r["resolution"])
            t = _int_type(int(np.floor(r["range"][0] / r["resolution"] + 0.5)),      # the register width the
                          int(np.floor(r["range"][1] / r["resolution"] + 0.5)))      # sensor's range needs
            b = k.astype(t).tobytes()
            e.update({"kind": "reading", "quantity": r["quantity"], "part": r["part"], "generic": r["generic"],
                      "bits": r["bits"], "bits_from": "range / resolution",
                      "noise_over_resolution": round(r["noise_sd"] / r["resolution"], 3),
                      "bin_type": np.dtype(t).name, "bin_bytes": len(b), "bin_gzip_bytes": _gz(b),
                      "packed_bytes": int(np.ceil(n * r["bits"] / 8))})
            e["bin_ratio"] = round(e["bin_bytes"] / e["bin_gzip_bytes"], 2) if e["bin_gzip_bytes"] else None
            bin_total += e["bin_bytes"]
            bin_gz_total += e["bin_gzip_bytes"]
        else:
            distinct = s.nunique()
            e.update({"kind": "logic", "bits": int(np.ceil(np.log2(max(distinct, 2)))), "bits_from": "observed"})
        cols[c] = e
    return {"device": dev.get("slug"), "scenario": man["scenario"]["name"], "seed": man["seed"], "rows": n,
            "note": NOTE,
            "file": {"csv_bytes": len(whole), "csv_gzip_bytes": _gz(whole),
                     "csv_ratio": round(len(whole) / _gz(whole), 2),
                     "readings_bin_bytes": bin_total, "readings_bin_gzip_bytes": bin_gz_total,
                     "readings_bin_ratio": round(bin_total / bin_gz_total, 2) if bin_gz_total else None},
            "columns": cols}


RANGE_KEYS = ("csv_ratio", "bin_ratio", "repeat_fraction")


def profile_range(profiles: list) -> dict:
    """min..max over several seeds of the same device and scenario: {"seeds", "file": {key: [min, max]},
    "columns": {column: {key: [min, max]}}}, so a ratio is a range, not one number."""
    def span(vals):
        vals = [v for v in vals if v is not None]
        return [min(vals), max(vals)] if vals else None
    out = {"seeds": [p["seed"] for p in profiles], "note": NOTE,
           "file": {k: span([p["file"][k] for p in profiles]) for k in ("csv_ratio", "readings_bin_ratio")},
           "columns": {}}
    for c in profiles[0]["columns"]:
        out["columns"][c] = {k: span([p["columns"][c].get(k) for p in profiles if c in p["columns"]])
                             for k in RANGE_KEYS if k in profiles[0]["columns"][c]}
    return out
