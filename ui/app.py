"""
Streamlit UI for the sensor-agnostic generator. Run from the repository root:

    streamlit run ui/app.py --server.address 127.0.0.1

Three ways in:
- Start from columns (default, pre-sales): pick what the client logs, the situation, then per column a
  generic sensor or a named part; sampling, resolution and noise can be changed.
- Build a device: from parts, named, with a world and the events it can see.
- A scenario (marked in progress).
Then generate: plots, gate, labels, a data profile and a ZIP. All logic lives in core/ and
validation/; this file only collects choices and shows results (docs/UI.md, docs/PRESALES.md).
"""
import json
import os
import sys
import tempfile
import time

import pandas as pd
import streamlit as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.devices import (Device, Part, columns_spec, generic_part, list_parts, parts_measuring,  # noqa: E402
                          save_device)
from core.events import EVENTS, compatible_events, list_scenarios, load_scenario  # noqa: E402
from core.output import plot_run, profile_range, run, zip_run  # noqa: E402
from core.output.profile import NOTE as PROFILE_NOTE  # noqa: E402
from core.quantities import CATALOG  # noqa: E402
from core.world import list_presets, load_preset  # noqa: E402

TWEAKABLE = ("accuracy", "noise_sd", "t90_s", "resolution")
st.set_page_config(page_title="Synthetic sensor data", layout="wide")
# selected parts show their whole label instead of a cut-off chip
st.markdown("""<style>
[data-baseweb="tag"] {max-width: none !important; height: auto !important;}
[data-baseweb="tag"] span {max-width: none !important; overflow: visible !important; text-overflow: clip !important;
                           white-space: normal !important;}
</style>""", unsafe_allow_html=True)
st.title("Synthetic sensor data")
st.caption("Every world is labelled realism: ASSUMPTION: built from datasheets and stated assumptions, "
           "not fitted to field recordings.")


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


def column_label(q):
    """'accel_{x,y,z}_g' for a vector quantity, the column for a scalar."""
    c = CATALOG[q]
    return c.column.replace("{axis}", "{" + ",".join(c.axes) + "}") if c.vector else c.column


@st.cache_data(show_spinner=False)
def part_label(slug):
    """'Bosch BME280 → temperature_c, humidity_rh, pressure_hpa': the part and the CSV columns it writes."""
    return f"{Part.load(slug).name} → {', '.join(column_label(q) for q in Part.load(slug).quantities())}"


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


@st.cache_data(show_spinner="Finding the events this device can see…")
def events_for(world, device_yaml, mount, hours):
    import yaml
    dev = Device.from_dict(yaml.safe_load(device_yaml))
    from core.world import Mount
    rows = compatible_events(world, [(dev, Mount(mount))], hours * 3600)
    return [{"name": r["name"], "kind": r["kind"], "params": r["params"], "ok": r["ok"], "why": r["why"]} for r in rows]


def v(p):
    return p["value"] if isinstance(p, dict) and "value" in p else p


def table(df, wide: dict = None):
    """A table whose long text columns get a fixed width in pixels, so the table scrolls sideways
    instead of cutting the text."""
    cfg = {c: st.column_config.TextColumn(c, width=px) for c, px in (wide or {}).items() if c in df.columns}
    st.dataframe(df, hide_index=True, width="stretch", column_config=cfg)


def kb(n):
    return f"{n / 1024:.1f}"


def show_profile(path):
    with open(path) as fh:
        p = json.load(fh)
    f = p["file"]
    st.markdown(f"**Data profile** ({p['rows']} rows): whole CSV {kb(f['csv_bytes'])} kB → gzip "
                f"{kb(f['csv_gzip_bytes'])} kB (ratio {f['csv_ratio']}); readings as raw counts in binary "
                f"{kb(f['readings_bin_bytes'])} kB → gzip {kb(f['readings_bin_gzip_bytes'])} kB "
                f"(ratio {f['readings_bin_ratio']})")
    st.caption(PROFILE_NOTE + " Ratio = size before / size after gzip; higher shrinks more.")
    rows = []
    for c, e in p["columns"].items():
        rows.append({"column": c + (" (generic)" if e.get("generic") else ""), "bits/sample": e["bits"],
                     "bits from": e["bits_from"], "noise / resolution": e.get("noise_over_resolution", ""),
                     "repeats prev. row": f"{100 * e['repeat_fraction']:.1f} %",
                     "CSV kB": kb(e["csv_bytes"]), "CSV gzip kB": kb(e["csv_gzip_bytes"]), "CSV ratio": e["csv_ratio"],
                     "counts type": e.get("bin_type", ""), "counts kB": kb(e["bin_bytes"]) if "bin_bytes" in e else "",
                     "counts gzip kB": kb(e["bin_gzip_bytes"]) if "bin_gzip_bytes" in e else "",
                     "counts ratio": e.get("bin_ratio", "")})
    table(pd.DataFrame(rows).astype(str), {"column": 240})


def show_results(results):
    if all(r.get("passed") for r in results):
        st.success(f"Generated {len(results)} device file(s); every gate passed")
    else:
        st.error("At least one device failed its gate; see the table below")
    st.download_button("Download ZIP (CSV, labels, manifest, gate, profile)", data=zip_run(results),
                       file_name="synthetic_run.zip", mime="application/zip")
    for r in results:
        with open(r["gate"]) as fh:
            g = json.load(fh)
        st.subheader(f"{r['device']}: gate {'PASSED' if g['passed'] else 'FAILED'}")
        with st.spinner("Plotting…"):
            st.pyplot(plot_run(r["csv"], r["labels"], r["manifest"]))
        if r.get("profile"):
            show_profile(r["profile"])
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Gate checks**")
            table(pd.DataFrame([{"": "✅" if c["passed"] else "❌", "check": c["name"], "column": c["column"],
                                 "value": str(c["value"]), "threshold": str(c["threshold"])} for c in g["checks"]]),
                  {"column": 220, "value": 380, "threshold": 480})
        with c2:
            st.markdown("**What happened** (labels; scope expected = what the device should do)")
            table(pd.read_csv(r["labels"]), {"event": 220, "detail": 320, "start_utc": 200, "end_utc": 200})
        st.markdown("**First rows of the CSV**")
        st.dataframe(pd.read_csv(r["csv"]).head(20), hide_index=True, width="stretch")


def show_seed_range():
    last = st.session_state.get("last")
    if not last:
        return
    st.markdown("**Five seeds**: the same device and situation with seeds "
                f"{last['seed']}…{last['seed'] + 4}, so the profile is a range, not one number.")
    if st.button("Run 5 seeds", key="five_seeds"):
        profs = {}
        with st.spinner("Generating five seeds…"):
            for s in range(last["seed"], last["seed"] + 5):
                for r in run(last["scenario"], seed=s, out_dir=os.path.join(out_dir, f"seeds_{int(time.time())}_{s}"),
                             gate=False):
                    with open(r["profile"]) as fh:
                        profs.setdefault(r["device"], []).append(json.load(fh))
        st.session_state["seed_range"] = {d: profile_range(p) for d, p in profs.items()}
    for d, rng in (st.session_state.get("seed_range") or {}).items():
        span = lambda x: "" if not x else (f"{x[0]:g} … {x[1]:g}" if x[0] != x[1] else f"{x[0]:g}")
        st.markdown(f"`{d}`, seeds {rng['seeds']}: whole CSV gzip ratio {span(rng['file']['csv_ratio'])}; readings as "
                    f"raw counts {span(rng['file']['readings_bin_ratio'])}")
        table(pd.DataFrame([{"column": c, "CSV ratio": span(e.get("csv_ratio")), "counts ratio": span(e.get("bin_ratio")),
                             "repeats prev. row": span(e.get("repeat_fraction"))} for c, e in rng["columns"].items()]),
              {"column": 240})
        st.caption(PROFILE_NOTE)


def run_and_generate(spec, worlds, default_mount="fixed", default_hours=8, step=3):
    """World, mount, duration, seed, the device, its events and Generate: shared by the columns and the
    parts way in. Returns nothing; results go to st.session_state."""
    if not worlds:
        return
    world = st.session_state.get("world_choice")
    st.sidebar.markdown(f"**{step}. Run**")
    mount = st.sidebar.radio("Mount", ["fixed", "body"], index=["fixed", "body"].index(default_mount), horizontal=True,
                             help="body: worn by the moving person; fixed: on a wall, shelf or post", key="mount")
    hours = st.sidebar.number_input("Duration (h)", 1, 72, default_hours, key="hours")
    seed = st.sidebar.number_input("Seed", 0, 2 ** 31 - 1, 42, key="seed")
    try:
        dev = Device.from_dict(spec)
    except Exception as e:
        st.error(f"This device cannot be built: {e}")
        st.stop()
    st.markdown(f"**{dev.name}** (`{dev.slug}`): columns " + ", ".join(f"`{c}`" for c in dev.output_columns()))
    if st.button("Save this device to configs/devices"):
        try:
            saved = save_device(spec)
            st.success(f"Saved {saved.name} version {saved.version} as {os.path.relpath(saved.path, ROOT)}")
        except Exception as e:
            st.error(str(e))
    import yaml
    rows = events_for(world, yaml.safe_dump(spec), mount, int(hours))
    ok = [r for r in rows if r["ok"]]
    st.markdown(f"**Events this device can see in {world_title(world)}** "
                f"({len(ok)} of {len(rows)}; the others are listed with the reason below)")
    chosen = []
    for r in ok:
        c1, c2, c3 = st.columns([3, 2, 5])
        if c1.checkbox(r["name"], key=f"ev/{r['name']}"):
            at = c2.number_input("start (min)", 0, int(hours) * 60, int(hours) * 20, key=f"at/{r['name']}")
            entry = {k: v(p) for k, p in r["params"].items()}
            entry["at"] = int(at) * 60
            chosen.append({r["kind"]: entry})
        c3.caption(EVENTS[r["kind"]].description)
    with st.expander("Events this device cannot see, and why"):
        table(pd.DataFrame([{"event": r["name"], "why not": r["why"]} for r in rows if not r["ok"]]),
              {"event": 260, "why not": 1400})
    if st.button("Generate", type="primary", key="generate"):
        scenario = {"name": "ui_run", "title": f"{dev.name} in {world_title(world)}", "realism": "ASSUMPTION",
                    "world": world, "duration": f"{int(hours)}h", "seed": int(seed),
                    "devices": [{"device": dev, "mount": mount}], "events": chosen}
        t0 = time.time()
        try:
            with st.spinner("Generating…"):
                st.session_state["results"] = run(scenario, seed=int(seed),
                                                  out_dir=os.path.join(out_dir, f"{dev.slug}_{seed}_{int(t0)}"))
            st.session_state["took"] = time.time() - t0
            st.session_state["last"] = {"scenario": scenario, "seed": int(seed)}
            st.session_state.pop("seed_range", None)
        except Exception as e:
            st.session_state.pop("results", None)
            st.error(f"Generation failed: {e}")


def pick_world(needed, label):
    worlds = [w for w in list_presets() if needed <= world_quantities(w)]
    if not worlds:
        st.error(f"No world provides everything this device measures ({', '.join(sorted(needed))}). Add the missing "
                 "drivers to a world (docs/HOW_TO_ADD_A_WORLD.md) or pick other columns or parts.")
        st.stop()
    world = st.selectbox(label, worlds, format_func=lambda n: f"{world_title(n)} ({n})", key="world_choice")
    st.caption(world_description(world))
    return worlds


COLUMNS, BUILD, SCENARIO = "Start from columns", "Build a device", "A scenario (in progress)"
mode = st.sidebar.radio("Start from", [COLUMNS, BUILD, SCENARIO])
out_dir = st.session_state.setdefault("out_dir", tempfile.mkdtemp(prefix="synthetic_ui_"))

if mode == SCENARIO:
    st.info("In progress: the scenario page works, but its layout and options are still being finished.")
    names = list_scenarios()
    sc = st.sidebar.selectbox("Scenario", names, format_func=lambda n: f"{scenario_info(n).get('title', n)}  ({n})")
    info = scenario_info(sc)
    seed = st.sidebar.number_input("Seed", 0, 2 ** 31 - 1, int(info.get("seed", 42)))
    st.markdown(f"**{info.get('title', sc)}**: {info.get('description', '')}")
    st.markdown(f"World: `{info['world']}` ({world_title(info['world'])}) · duration {info.get('duration')} · "
                "devices: " + ", ".join(f"`{d['device']}` ({d.get('mount', 'body')})" for d in info.get("devices", [])))
    st.markdown("Events: " + ", ".join(f"`{next(iter(e))}`" for e in info.get("events", [])))
    if st.sidebar.button("Generate", type="primary"):
        t0 = time.time()
        with st.spinner("Generating…"):
            st.session_state["results"] = run(sc, seed=int(seed), out_dir=os.path.join(out_dir, f"{sc}_{seed}"))
        st.session_state["took"] = time.time() - t0
        st.session_state["last"] = {"scenario": sc, "seed": int(seed)}
        st.session_state.pop("seed_range", None)

elif mode == COLUMNS:
    st.markdown("#### 1. What does the client log?")
    st.caption("Pick the columns, grouped by domain. A vector quantity is three columns (x, y, z).")
    domains = {}
    for q in CATALOG:
        domains.setdefault(q.split(".")[0], []).append(q)
    picked = []
    grid = st.columns(4)
    for i, (dom, qs) in enumerate(domains.items()):
        picked += grid[i % 4].multiselect(dom, qs, key=f"cols/{dom}",
                                          format_func=lambda q: f"{column_label(q)} ({CATALOG[q].unit}) · {CATALOG[q].name}")
    if not picked:
        st.info("Pick at least one column above.")
        st.stop()
    st.markdown("#### 2. In which situation?")
    worlds = pick_world(set(picked), "Situation (only worlds that provide every chosen column)")
    st.markdown("#### 3. Which sensor per column?")
    st.caption("Generic is a typical sensor of its class, every value an ASSUMPTION; pick a named part when the "
               "client names one (its other quantities are not logged).")
    choice, ov = {}, {}
    for q in picked:
        def fmt(s, q=q):
            if s == "generic":
                return f"Generic (default): {part_info(generic_of(q))['cls']}"
            others = [column_label(x) for x in part_info(s)["quantities"] if x not in picked]
            return part_info(s)["name"] + (f" (also measures {', '.join(others)} (not logged))" if others else "")
        c1, c2 = st.columns([2, 5])
        c1.markdown(f"`{column_label(q)}` ({CATALOG[q].unit})")
        choice[q] = c2.selectbox(f"Sensor for {column_label(q)}", ["generic"] + named_parts(q), format_func=fmt,
                                 key=f"part/{q}", label_visibility="collapsed")
    st.markdown("#### 4. Sampling, resolution and noise")
    body = any(CATALOG[q].vector for q in picked)
    interval = st.number_input("Sample interval (s)", min_value=0.04, max_value=3600.0, value=0.04 if body else 60.0,
                               step=0.01 if body else 1.0, format="%g", key="interval",
                               help="0.04 s = 25 Hz, the finest step of the worlds' motion")
    raw = st.checkbox("Write raw counts (integer register / ADC codes, round(reading / resolution))", key="raw")
    for q in picked:
        slug = generic_of(q) if choice[q] == "generic" else choice[q]
        m = Part.load(slug).models()[q]
        unit = CATALOG[q].unit
        c0, c1, c2, c3 = st.columns([2, 2, 2, 4])
        c0.markdown(f"`{column_label(q)}`" + (" (generic)" if choice[q] == "generic" else ""))
        res = c1.number_input(f"resolution ({unit})", value=float(m.resolution), format="%g", key=f"res/{q}/{slug}")
        noise = c2.number_input(f"noise sd ({unit})", value=float(m.noise_sd), format="%g", min_value=0.0,
                                key=f"noise/{q}/{slug}")
        c3.caption(f"range {m.range} {unit} · t90 {m.t90_s:g} s · ODR {m.odr_hz or '—'} Hz · "
                   f"error bound ±{float(m.error_bound(0)):g} {unit}" +
                   (f" + {m.hard('accuracy_pct_reading'):g} % of reading" if m.accuracy_pct_reading else ""))
        for k, new, old in (("resolution", res, m.resolution), ("noise_sd", noise, m.noise_sd)):
            if abs(new - old) > 1e-12 * max(1.0, abs(old)):
                ov.setdefault(q, {})[k] = {"value": new, "unit": unit}
                c3.caption(f"changed: {k} {old:g} → {new:g} (ASSUMPTION: user tweak)")
    st.markdown("#### 5. Name, events, generate")
    st.sidebar.markdown("**Device**")
    name = st.sidebar.text_input("Name your device", "Client device", key="name")
    try:
        spec = columns_spec(choice, name=name, sample_interval_s=float(interval), overrides=ov, raw_counts=raw)
    except Exception as e:
        st.error(f"This device cannot be built: {e}")
        st.stop()
    run_and_generate(spec, worlds, "body" if body else "fixed", 1 if body else 8, step=2)

else:
    st.markdown("#### 1. Parts")
    parts = st.multiselect("Parts (sensors from datasheets) → the columns they write", list_parts(),
                           format_func=part_label)
    st.sidebar.markdown("**2. Device**")
    name = st.sidebar.text_input("Name your device", "My Device")
    interval = st.sidebar.number_input("Logging interval (s)", 1, 3600, 60)
    entries, logic = [], []
    for slug in parts:
        p = Part.load(slug)
        with st.expander(f"{p.name}: measures {', '.join(p.quantities())}"):
            st.caption(f"Datasheet: {p.datasheet}" + (f" · generic: {p.cls}" if p.generic_for else ""))
            ov = {}
            for q, params in p.measures.items():
                rows = [{"parameter": k, "value": str(v(x)), "unit": x.get("unit"), "source": x.get("source"),
                         "kind": x.get("kind", "")} for k, x in params.items()]
                st.markdown(f"`{q}`")
                table(pd.DataFrame(rows), {"value": 160, "source": 900})
                for k in TWEAKABLE:
                    if k in params and isinstance(v(params[k]), (int, float)):
                        new = st.number_input(f"{q} · {k} ({params[k]['unit']})", value=float(v(params[k])),
                                              format="%g", key=f"{slug}/{q}/{k}")
                        if new != float(v(params[k])):
                            ov.setdefault(q, {})[k] = {"value": new, "unit": params[k]["unit"]}
                            st.caption(f"changed: {k} {v(params[k])} → {new} (ASSUMPTION: user tweak)")
                if not CATALOG[q].vector and st.checkbox(f"Alarm on {CATALOG[q].name}", key=f"al/{slug}/{q}"):
                    c1, c2 = st.columns(2)
                    when = c1.selectbox("When", ["above", "below"], key=f"w/{slug}/{q}")
                    level = c2.number_input(f"Level ({CATALOG[q].unit})", value=0.0, format="%g", key=f"l/{slug}/{q}")
                    logic.append({"block": "threshold_alarm", "input": q, "when": when,
                                  "output": f"{CATALOG[q].column.split('_')[0]}_alarm_{when}",
                                  "level": {"value": level, "unit": CATALOG[q].unit, "source": "ASSUMPTION: set in the UI"}})
            entries.append(dict({"part": slug}, **({"overrides": ov} if ov else {})))
    if not parts:
        st.info("Pick at least one part above.")
        st.stop()
    needed = {q for slug in parts for q in Part.load(slug).quantities()}
    st.sidebar.markdown("**3. World**")
    with st.sidebar:
        worlds = pick_world(needed, "World (only those that provide what the parts measure)")
    spec = {"name": name, "parts": entries,
            "features": {"sample_interval_s": {"value": int(interval), "unit": "s", "source": "ASSUMPTION: set in the UI"}}}
    if logic:
        spec["logic"] = logic
    run_and_generate(spec, worlds, "fixed", 8, step=4)

if st.session_state.get("results"):
    st.caption(f"took {st.session_state.get('took', 0):.1f} s")
    show_results(st.session_state["results"])
    show_seed_range()
