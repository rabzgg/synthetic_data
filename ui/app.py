"""
Streamlit UI for the sensor-agnostic generator. Run from the repository root:

    streamlit run ui/app.py --server.address 127.0.0.1

Four ways in:
- Start from columns (default, pre-sales): pick what the sensor logs, the environment, then per column a
  generic sensor or a named part; sampling, resolution and noise can be changed.
- Build a device: from parts, named, with a world and the events it can see.
- Example scenarios (marked work in progress).
- Start from a real CSV (legacy): the older per-column statistical fit (core/generator.py, via ui/legacy.py),
  real CSV -> fitted JSON -> synthetic CSV, plotted against the real one. Not linked by physics.
Then generate: plots, gate, labels, a data summary and a ZIP. All logic lives in core/ and
validation/; this file only collects choices and shows results (docs/UI.md, docs/PRESALES.md).
On screen the code's words are translated: world = environment, gate = checks, part = sensor,
ASSUMPTION = assumed; slugs, dotted ids and repo paths are not shown.
"""
import json
import os
import re
import sys
import tempfile
import time

import numpy as np
import pandas as pd
import streamlit as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "ui"))                 # ui/legacy.py
from core.devices import (Device, Part, PartUse, columns_spec, generic_part, list_parts,  # noqa: E402
                          parts_measuring, save_device)
from core.events import EVENTS, compatible_events, list_scenarios, load_scenario  # noqa: E402
from core.output import plot_run, run, zip_run  # noqa: E402
from core.output.plot import LABEL_TEXT, event_name  # noqa: E402
from core.quantities import CATALOG  # noqa: E402
from core.world import list_presets, load_preset  # noqa: E402

TWEAKABLE = ("accuracy", "noise_sd", "noise_density", "t90_s", "resolution", "odr_hz")
DOMAIN = {"air": "Air (climate and gas)", "body": "IMU (motion)"}            # others: the domain, capitalised
QNAME = {"body.accel_g": "Accelerometer", "body.gyro_dps": "Gyroscope", "body.mag_ut": "Magnetometer",
         "light.lux": "Light", "air.lel_pct": "Combustible gas (LEL)", "air.voc_ppm": "VOC",
         "machine.vibration_mm_s": "Vibration (RMS velocity)"}             # others: the catalog name
OFFSET = {"body.accel_g": "zero-g offset", "body.gyro_dps": "zero-rate offset", "body.mag_ut": "offset"}
PARAM = {"accuracy": "accuracy", "accuracy_pct_reading": "accuracy, % of reading", "noise_sd": "RMS noise",
         "noise_density": "noise density", "t90_s": "response time t90", "t90_down_s": "response time t90, falling",
         "resolution": "resolution", "odr_hz": "ODR", "bandwidth_hz": "bandwidth", "range": "range"}
MOUNT = {"fixed": "fixed (on a wall, shelf or machine)", "body": "worn (on a person)"}
LABEL_TYPE = {"world": "environment", "device": "device", "expected": "expected"}

st.set_page_config(page_title="Synthetic sensor data", layout="wide")
# long labels stay readable: an open dropdown list shows each option whole and scrolls sideways when it
# is wider than the list
st.markdown("""<style>
[data-testid$="Dropdown"] [role="listbox"] {overflow-x: auto !important;}
[data-testid$="Dropdown"] [role="listbox"] > [role="presentation"] > [role="presentation"],
[data-testid$="Dropdown"] [role="option"] {width: max-content !important; min-width: 100% !important;
                                           contain: none !important;}
[data-testid$="Dropdown"] [role="option"] * {white-space: nowrap !important; overflow: visible !important;
                                             text-overflow: clip !important; max-width: none !important;}
</style>""", unsafe_allow_html=True)
st.title("Synthetic sensor data")


@st.cache_data(show_spinner=False)
def scenario_info(name):
    return load_scenario(name)


@st.cache_data(show_spinner=False)
def world_title(name):
    p = load_preset(name)
    return p.get("title", name)


@st.cache_data(show_spinner=False)
def world_description(name):
    return load_preset(name).get("description", "")


@st.cache_data(show_spinner=False)
def device_name(slug):
    return Device.load(slug).name


def column_label(q):
    """'accel_x,y,z_g' for a vector quantity, the column for a scalar."""
    c = CATALOG[q]
    return c.column.replace("{axis}", ",".join(c.axes)) if c.vector else c.column


def qname(q):
    return QNAME.get(q, CATALOG[q].name)


def lower_first(s):
    """'air temperature', but 'VOC' and 'pH' stay as they are."""
    return s if s[:2].isupper() or s[:1].islower() else s[:1].lower() + s[1:]


def and_join(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def num(x):
    """A number with a real minus sign."""
    return f"{x:g}".replace("-", "−")


@st.cache_data(show_spinner=False)
def part_label(slug):
    """'Bosch BME280 (temperature_c, humidity_rh, pressure_hpa)': the sensor and the CSV columns it writes."""
    return f"{Part.load(slug).name} ({', '.join(column_label(q) for q in Part.load(slug).quantities())})"


@st.cache_data(show_spinner=False)
def part_info(slug):
    p = Part.load(slug)
    return {"name": p.name, "cls": p.cls, "quantities": p.quantities()}


@st.cache_data(show_spinner=False)
def generic_of(q):
    return generic_part(q)


@st.cache_data(show_spinner=False)
def named_parts(q):
    return parts_measuring(q)


@st.cache_data(show_spinner=False)
def world_quantities(name):
    from core.world import World
    return set(World(name, 60, 1).quantities())


@st.cache_data(show_spinner="Checking which events fit")
def events_for(world, device_yaml, mount, hours):
    import yaml
    dev = Device.from_dict(yaml.safe_load(device_yaml))
    from core.world import Mount
    rows = compatible_events(world, [(dev, Mount(mount))], hours * 3600, building_blocks=True)
    return [{"name": r["name"], "title": r["title"], "kind": r["kind"], "params": r["params"], "ok": r["ok"],
             "why": r["why"], "detail": r["detail"], "block": EVENTS[r["kind"]].building_block} for r in rows]


def v(p):
    return p["value"] if isinstance(p, dict) and "value" in p else p


def param_label(k):
    return PARAM.get(k, k.replace("_", " "))


def show_value(x):
    """A parameter value in words: '0 to 100' for a range, '2000/523, 1000/116' for pairs."""
    if isinstance(x, (list, tuple)):
        if all(isinstance(y, (list, tuple)) for y in x):
            return ", ".join("/".join(f"{z:g}" if isinstance(z, (int, float)) else str(z) for z in y) for y in x)
        if len(x) == 2 and all(isinstance(y, (int, float)) for y in x):
            return f"{num(x[0])} to {num(x[1])}"
        return ", ".join(f"{y:g}" if isinstance(y, (int, float)) else str(y) for y in x)
    return str(x)


def screen(text):
    """Source and check texts for the screen: no capitals for assumptions, no semicolons, ranges as 'a to b'."""
    s = str(text if text is not None else "")
    s = re.sub(r"(\d)\s*(?:…|\.\.)\s*(?=[\d−-])", r"\1 to ", s)                 # 0…65 °C, 0..65: 0 to 65
    return s.replace("[USER TO VERIFY]", "not verified yet").replace("ASSUMPTION", "assumed").replace("; ", ", ")


def check_text(x):
    """A check's result or limit in words: lists joined, event ids as event names."""
    s = ", ".join(map(str, x)) if isinstance(x, (list, tuple)) else str(x)
    for kind in sorted(EVENTS, key=len, reverse=True):
        s = re.sub(rf"\b{kind}\b", EVENTS[kind].name.lower(), s)
    return screen(s)


def fail(message, err):
    """A short message, and the original error under Details."""
    st.error(message)
    with st.expander("Details"):
        st.text(str(err))


def table(df, wide: dict = None):
    """A table whose long text columns get a fixed width in pixels, so the table scrolls sideways
    instead of cutting the text."""
    cfg = {c: st.column_config.TextColumn(c, width=px) for c, px in (wide or {}).items() if c in df.columns}
    st.dataframe(df, hide_index=True, width="stretch", column_config=cfg)


def show_summary(path):
    with open(path) as fh:
        p = json.load(fh)
    st.markdown(f"**Data summary**: {p['rows']} rows at {p['sample_rate_hz']:g} Hz")
    rows = []
    for c, e in p["columns"].items():
        rows.append({"column": c, "unit": e.get("unit", ""), "rows": e["rows"], "sample rate (Hz)": e["sample_rate_hz"],
                     "bits per sample": e.get("bits", ""), "min": e.get("min", ""), "max": e.get("max", ""),
                     "noise vs resolution": e.get("noise_over_resolution", ""),
                     "ODR (Hz)": e.get("odr_hz") or "", "bandwidth (Hz)": e.get("bandwidth_hz") or "",
                     "generic": {True: "yes", False: "no"}.get(e.get("generic"), "")})
    table(pd.DataFrame(rows).astype(str), {"column": 240})


def show_labels(path):
    lab = pd.read_csv(path, dtype=LABEL_TEXT).fillna({c: "" for c in LABEL_TEXT})
    table(pd.DataFrame({"event": [event_name(e) for e in lab["event"]], "detail": lab["detail"],
                        "type": [LABEL_TYPE.get(s, s) for s in lab["scope"]],
                        "start (UTC)": lab["start_utc"], "end (UTC)": lab["end_utc"]}),
          {"event": 220, "detail": 320, "start (UTC)": 200, "end (UTC)": 200})


def show_results(results):
    if all(r.get("passed") for r in results):
        st.success("Done. All checks passed.")
    else:
        st.error("At least one check failed (see the table below)")
    st.download_button("Download as ZIP (CSV, event labels, settings, checks, summary)", data=zip_run(results),
                       file_name="synthetic_run.zip", mime="application/zip")
    for r in results:
        with open(r["gate"]) as fh:
            g = json.load(fh)
        with open(r["manifest"]) as fh:
            name = json.load(fh)["device"]["name"]
        st.subheader(f"{name}: checks {'passed' if g['passed'] else 'failed'}")
        with st.spinner("Plotting"):
            st.pyplot(plot_run(r["csv"], r["labels"], r["manifest"]))
        if r.get("summary"):
            show_summary(r["summary"])
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Checks**")
            table(pd.DataFrame([{"": "✅" if c["passed"] else "❌", "check": c["name"].replace("_", " "),
                                 "column": "all" if c["column"] == "*" else c["column"],
                                 "result": check_text(c["value"]), "limit": check_text(c["threshold"])}
                                for c in g["checks"]]),
                  {"column": 220, "result": 380, "limit": 480})
        with c2:
            st.markdown("**Event labels** (expected = what the device should show)")
            show_labels(r["labels"])
        st.markdown("**First 20 rows**")
        st.dataframe(pd.read_csv(r["csv"]).head(20), hide_index=True, width="stretch")


def event_choice(r, hours, chosen):
    c1, c2, c3 = st.columns([3, 2, 5])
    if c1.checkbox(r["title"], key=f"ev/{r['name']}"):
        at = c2.number_input("start (min)", 0, int(hours) * 60, int(hours) * 20, key=f"at/{r['name']}")
        entry = {k: v(p) for k, p in r["params"].items()}
        entry["at"] = int(at) * 60
        chosen.append({r["kind"]: entry})
    c3.caption(EVENTS[r["kind"]].description)


def run_and_generate(spec, worlds, default_mount="fixed", default_hours=8, sidebar_title=None, main_title=None):
    """Mounting, duration, seed, the device, its events and Generate: shared by the columns and the
    sensors way in. Returns nothing; results go to st.session_state."""
    if not worlds:
        return
    world = st.session_state.get("world_choice")
    if sidebar_title:
        st.sidebar.markdown(sidebar_title)
    mount = st.sidebar.radio("Mounting", ["fixed", "body"], index=["fixed", "body"].index(default_mount),
                             format_func=MOUNT.get, key="mount")
    hours = st.sidebar.number_input("Duration (h)", 1, 72, default_hours, key="hours")
    seed = st.sidebar.number_input("Seed", 0, 2 ** 31 - 1, 42, key="seed",
                                   help="Same seed = same data. Change it to get another version of the same setup.")
    if main_title:
        st.markdown(main_title)
    try:
        dev = Device.from_dict(spec)
    except Exception as e:
        fail("This device does not work yet. Check the sensors and values above.", e)
        st.stop()
    st.markdown(f"**{dev.name}** writes these columns: " + ", ".join(f"`{c}`" for c in dev.output_columns()))
    if st.button("Save this device"):
        try:
            saved = save_device(spec)
            st.success(f"Saved {saved.name} (version {saved.version})")
        except Exception as e:
            fail("Could not save this device.", e)
    import yaml
    rows = events_for(world, yaml.safe_dump(spec), mount, int(hours))
    main = [r for r in rows if not r["block"]]
    ok = [r for r in main if r["ok"]]
    st.markdown(f"**Events this device can show in {world_title(world)}** ({len(ok)} of {len(main)})")
    chosen = []
    for r in ok:
        event_choice(r, hours, chosen)
    blocks = [r for r in rows if r["block"] and r["ok"]]
    if blocks:
        with st.expander("Building blocks (advanced)"):
            for r in blocks:
                event_choice(r, hours, chosen)
    with st.expander("Events this device cannot show (and why)"):
        table(pd.DataFrame([{"event": r["title"], "why not": r["why"]} for r in main if not r["ok"]]),
              {"event": 260, "why not": 900})
    if st.button("Generate", type="primary", key="generate"):
        scenario = {"name": "ui_run", "title": f"{dev.name} in {world_title(world)}", "realism": "ASSUMPTION",
                    "world": world, "duration": f"{int(hours)}h", "seed": int(seed),
                    "devices": [{"device": dev, "mount": mount}], "events": chosen}
        t0 = time.time()
        try:
            with st.spinner("Generating data"):
                st.session_state["results"] = run(scenario, seed=int(seed),
                                                  out_dir=os.path.join(out_dir, f"{dev.slug}_{seed}_{int(t0)}"))
            st.session_state["took"] = time.time() - t0
        except Exception as e:
            st.session_state.pop("results", None)
            fail("Generation failed.", e)


def pick_world(needed, label):
    worlds = [w for w in list_presets() if needed <= world_quantities(w)]
    if not worlds:
        best = max(list_presets(), key=lambda w: len(needed & world_quantities(w)))
        lacks = and_join(column_label(q) for q in sorted(needed - world_quantities(best)))
        st.error(f"None of the environments has all of these columns yet. The closest is {world_title(best)}, "
                 f"which has no {lacks}. Pick other columns, or see docs/prompts/EXTEND.md to add them.")
        st.stop()
    world = st.selectbox(label, worlds, format_func=world_title, key="world_choice")
    st.caption(world_description(world))
    return worlds


COLUMNS, BUILD, SCENARIO = "Start from columns", "Build a device", "Example scenarios (work in progress)"
LEGACY = "Start from a real CSV (legacy)"
mode = st.sidebar.radio("Start from", [COLUMNS, BUILD, SCENARIO, LEGACY])
if mode != LEGACY:
    st.caption("The goal is to preview what a client's sensor data will look like before the real CSV exists. "
               "Every value comes from a datasheet or a written assumption. Nothing is fitted to real recordings yet.")
out_dir = st.session_state.setdefault("out_dir", tempfile.mkdtemp(prefix="synthetic_ui_"))


@st.cache_data(show_spinner=False)
def legacy_fit(raw: bytes):
    import legacy
    path, left_out = legacy.prepare(raw, tempfile.mkdtemp(prefix="legacy_", dir=out_dir))
    return path, left_out, legacy.fit(path)


if mode == LEGACY:
    import legacy
    st.info("Legacy statistical copy. Each column is fitted on its own, so columns are not linked by physics.  \n"
            "For potential clients without data, use Start from columns.")
    st.markdown("#### 1. The real CSV")
    source = st.radio("CSV", ["Upload a CSV", "Example: robot arm sensor 1 (XDK, 10 Hz)"],
                      key="legacy_source", label_visibility="collapsed")
    if source == "Upload a CSV":
        up = st.file_uploader("CSV file", type=["csv", "gz"], key="legacy_upload")
        raw = up.getvalue() if up else None
    else:
        with open(legacy.EXAMPLE, "rb") as fh:
            raw = fh.read()
    st.caption("It needs a column named timestamp (milliseconds, seconds, or a date and time). "
               "Columns with text are left out. Data logged slower than every 2 s is not supported.")
    if raw is None:
        st.stop()
    try:
        with st.spinner("Fitting each column"):
            real_path, left_out, cfg = legacy_fit(raw)
    except legacy.LegacyError as e:
        st.error(str(e))
        st.stop()
    except Exception as e:
        fail("The legacy fit failed on this CSV.", e)
        st.stop()
    st.markdown("#### 2. Fitted engine per column")
    real = pd.read_csv(real_path)
    st.caption(f"{len(real)} rows, about {cfg['frequency_hz']:g} Hz, "
               f"{cfg['duration_s'] / 60:.0f} min recorded." +
               (f" Left out (text): {and_join(left_out)}." if left_out else ""))
    table(legacy.engines(cfg), {"column": 220, "what it means": 320})
    st.download_button("Download the fitted settings (JSON)", data=json.dumps(cfg, indent=2),
                       file_name="fitted_config.json", mime="application/json", key="legacy_json")
    st.markdown("#### 3. Generate")
    c1, c2 = st.columns(2)
    minutes = c1.number_input("Duration (min)", min_value=1, max_value=1440, value=10, key="legacy_minutes")
    seed = c2.number_input("Seed", 0, 2 ** 31 - 1, 42, key="legacy_seed",
                           help="Same seed = same data. Change it to get another version.")
    if st.button("Generate", type="primary", key="legacy_generate"):
        t0 = time.time()
        with st.spinner("Generating data"):
            st.session_state["legacy"] = {"syn": legacy.generate(cfg, minutes, seed), "cfg": cfg, "real": real_path}
        st.session_state["took"] = time.time() - t0
    res = st.session_state.get("legacy")
    if res and res["real"] == real_path:
        syn = res["syn"]
        st.caption(f"Generated {len(syn)} rows in {st.session_state.get('took', 0):.1f} s")
        st.download_button("Download as ZIP (synthetic CSV, fitted settings)", data=legacy.zip_files(syn, res["cfg"]),
                           file_name="legacy_synthetic.zip", mime="application/zip", key="legacy_zip")
        with st.spinner("Plotting"):
            st.pyplot(legacy.plot(real_path, syn, list(res["cfg"]["columns"])))
        st.markdown("**First 20 rows**")
        st.dataframe(syn.head(20), hide_index=True, width="stretch")
    st.stop()

if mode == SCENARIO:
    st.info("This page works, the layout is not final yet.")
    names = list_scenarios()
    sc = st.sidebar.selectbox("Scenario", names, format_func=lambda n: scenario_info(n).get("title", n))
    info = scenario_info(sc)
    seed = st.sidebar.number_input("Seed", 0, 2 ** 31 - 1, int(info.get("seed", 42)),
                                   help="Same seed = same data. Change it to get another version of the same setup.")
    st.markdown(f"**{info.get('title', sc)}**: {info.get('description', '')}")
    duration = re.sub(r"(\d)([a-z]+)$", r"\1 \2", str(info.get("duration")))
    st.markdown(f"Environment: {world_title(info['world'])}. Duration: {duration}.")
    st.markdown("Devices: " + ", ".join(f"{device_name(d['device'])} ({MOUNT[d.get('mount', 'body')].split(' ')[0]})"
                                        for d in info.get("devices", [])))
    st.markdown("Events: " + ", ".join(event_name(next(iter(e))) for e in info.get("events", [])))
    if st.sidebar.button("Generate", type="primary"):
        t0 = time.time()
        with st.spinner("Generating data"):
            st.session_state["results"] = run(sc, seed=int(seed), out_dir=os.path.join(out_dir, f"{sc}_{seed}"))
        st.session_state["took"] = time.time() - t0

elif mode == COLUMNS:
    st.markdown("#### 1. What does the sensor log?")
    st.caption("Pick the columns the client's sensor writes. Accelerometer, gyroscope and magnetometer come as "
               "three columns each (x, y, z).")
    domains = {}
    for q in CATALOG:
        domains.setdefault(q.split(".")[0], []).append(q)
    picked = []
    grid = st.columns(2)                                  # two wide boxes a row: the chosen columns stay readable
    for i, (dom, qs) in enumerate(domains.items()):
        picked += grid[i % 2].multiselect(DOMAIN.get(dom, dom.capitalize()), qs, key=f"cols/{dom}",
                                          format_func=lambda q: f"{qname(q)}: {column_label(q)} in {CATALOG[q].unit}")
    st.caption("Not in the list? See docs/prompts/EXTEND.md in the repo.")
    if not picked:
        st.info("Pick at least one column above.")
        st.stop()
    st.markdown("#### 2. Where is the sensor?")
    worlds = pick_world(set(picked), "Environment")
    st.markdown("#### 3. Which sensor?")
    st.caption("Pick the sensor if the client named one. If not, keep Generic (a typical sensor of that type, all "
               "values assumed). A sensor that also measures other things only writes the columns you picked.")
    choice, ov = {}, {}
    for q in picked:
        def fmt(s, q=q):
            if s == "generic":
                return f"Generic ({part_info(generic_of(q))['cls']})"
            others = [column_label(x) for x in part_info(s)["quantities"] if x not in picked]
            return part_info(s)["name"] + (f" (also measures {and_join(others)}, not written)" if others else "")
        c1, c2 = st.columns([2, 5])
        c1.markdown(f"**{qname(q)}** `{column_label(q)}`")
        choice[q] = c2.selectbox(f"Sensor for {column_label(q)}", ["generic"] + named_parts(q), format_func=fmt,
                                 key=f"part/{q}", label_visibility="collapsed")
    st.markdown("#### 4. Sampling, resolution and noise")
    body = any(CATALOG[q].vector for q in picked)
    interval = st.number_input("Logging interval (s)", min_value=0.001, max_value=3600.0, value=0.04 if body else 60.0,
                               step=0.01 if body else 1.0, format="%g", key="interval",
                               help="0.04 s = 25 Hz. If the sensor lets you set its ODR, the ODR follows this "
                                    "interval and so does the noise.")
    raw = st.checkbox("Write counts (LSB) instead of physical units (integer = value / resolution)", key="raw")
    for q in picked:
        slug = generic_of(q) if choice[q] == "generic" else choice[q]
        use = PartUse(Part.load(slug))
        use.follow_sample_rate(float(interval))
        m = use.models()[q]                                  # at this logging interval
        unit = CATALOG[q].unit
        c0, c1, c2, c3, c4 = st.columns([2, 2, 2, 2, 4])
        c0.markdown(f"`{column_label(q)}`" + (" (generic)" if choice[q] == "generic" else ""))
        k = f"{q}/{slug}/{interval}"
        res = c1.number_input(f"resolution ({unit})", value=float(m.resolution), format="%g", key=f"res/{k}")
        noise = c2.number_input(f"RMS noise ({unit})", value=float(m.noise_sd), format="%g", min_value=0.0,
                                key=f"noise/{k}")
        odr = c3.number_input("ODR (Hz)", value=float(m.odr_hz or 0.0), format="%g", min_value=0.0, key=f"odr/{k}",
                              help="ODR = output data rate. Type a value to fix it, otherwise it follows the logging "
                                   "interval (lower ODR = narrower bandwidth = less noise). Sensors with a fixed ODR "
                                   "do not change.")
        lo, hi = float(np.min(m.bounds[0])), float(np.max(m.bounds[1]))
        facts = [f"Range {num(lo)} to {num(hi)} {unit}"]
        if m.t90_s:
            facts.append(f"response time (t90) {m.t90_s:g} s")
        facts.append(f"bandwidth {m.bandwidth_hz:g} Hz" if m.bandwidth_hz else "bandwidth n/a")
        facts.append("ODR follows the logging interval" if q in use.rate else "fixed ODR")
        facts.append(f"{OFFSET.get(q, 'accuracy')} ±{float(m.error_bound(0)):g} {unit}" +
                     (f" + {m.hard('accuracy_pct_reading'):g} % of reading" if m.accuracy_pct_reading else ""))
        c4.caption(", ".join(facts))
        for name_, new, old, u_ in (("resolution", res, m.resolution, unit), ("noise_sd", noise, m.noise_sd, unit),
                                    ("odr_hz", odr, m.odr_hz or 0.0, "Hz")):
            if abs(new - old) > 1e-9 * max(1.0, abs(old)):
                ov.setdefault(q, {})[name_] = {"value": new, "unit": u_}
                c4.caption(f"Changed {dict(noise_sd='noise').get(name_, param_label(name_))} from {old:g} to {new:g} "
                           "(your value, saved as assumed)")
    st.markdown("#### 5. Name the device, add events, generate")
    st.sidebar.markdown("**5. Device**")
    name = st.sidebar.text_input("Name your device", "Client device", key="name")
    try:
        spec = columns_spec(choice, name=name, sample_interval_s=float(interval), overrides=ov, raw_counts=raw)
    except Exception as e:
        fail("This device does not work yet. Check the sensors and values above.", e)
        st.stop()
    run_and_generate(spec, worlds, "body" if body else "fixed", 1 if body else 8)

else:
    st.markdown("#### 1. Sensors")
    parts = st.multiselect("Sensors (from datasheets)", list_parts(), format_func=part_label)
    st.sidebar.markdown("**2. Device**")
    name = st.sidebar.text_input("Name your device", "My Device")
    interval = st.sidebar.number_input("Logging interval (s)", 1, 3600, 60)
    entries, logic = [], []
    for slug in parts:
        p = Part.load(slug)
        with st.expander(part_label(slug)):
            st.caption(f"Generic sensor: {p.cls}. All values are assumed." if p.generic_for else
                       f"Datasheet: {p.datasheet}")
            ov = {}
            for q, params in p.measures.items():
                rows = [{"parameter": param_label(k), "value": show_value(v(x)), "unit": x.get("unit"),
                         "source": screen(x.get("source")), "typical or max": x.get("kind", "")}
                        for k, x in params.items()]
                st.markdown(f"**{qname(q)}** `{column_label(q)}`")
                table(pd.DataFrame(rows), {"value": 160, "source": 900})
                for k in TWEAKABLE:
                    if k in params and isinstance(v(params[k]), (int, float)):
                        new = st.number_input(f"{column_label(q)}: {param_label(k)} ({params[k]['unit']})",
                                              value=float(v(params[k])), format="%g", key=f"{slug}/{q}/{k}")
                        if new != float(v(params[k])):
                            ov.setdefault(q, {})[k] = {"value": new, "unit": params[k]["unit"]}
                            st.caption(f"Changed {param_label(k)} from {v(params[k]):g} to {new:g} "
                                       "(your value, saved as assumed)")
                if not CATALOG[q].vector and st.checkbox(f"Alarm on {lower_first(qname(q))}", key=f"al/{slug}/{q}"):
                    c1, c2 = st.columns(2)
                    when = c1.selectbox("When", ["above", "below"], key=f"w/{slug}/{q}")
                    level = c2.number_input(f"Level ({CATALOG[q].unit})", value=0.0, format="%g", key=f"l/{slug}/{q}")
                    logic.append({"block": "threshold_alarm", "input": q, "when": when,
                                  "output": f"{CATALOG[q].column.split('_')[0]}_alarm_{when}",
                                  "level": {"value": level, "unit": CATALOG[q].unit, "source": "ASSUMPTION: set in the UI"}})
            entries.append(dict({"part": slug}, **({"overrides": ov} if ov else {})))
    if not parts:
        st.info("Pick at least one sensor above.")
        st.stop()
    needed = {q for slug in parts for q in Part.load(slug).quantities()}
    st.sidebar.markdown("**3. Environment**")
    with st.sidebar:
        worlds = pick_world(needed, "Environment")
    spec = {"name": name, "parts": entries,
            "features": {"sample_interval_s": {"value": int(interval), "unit": "s", "source": "ASSUMPTION: set in the UI"}}}
    if logic:
        spec["logic"] = logic
    run_and_generate(spec, worlds, "fixed", 8, sidebar_title="**4. Run**", main_title="#### 5. Events and generate")

if st.session_state.get("results"):
    st.caption(f"Generated in {st.session_state.get('took', 0):.1f} s")
    show_results(st.session_state["results"])
