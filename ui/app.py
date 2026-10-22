"""
Streamlit UI for the sensor-agnostic generator. Run from the repository root:

    streamlit run ui/app.py --server.address 127.0.0.1

Two ways in: build a device from parts, name it, pick a world and the events it can see (the
default), or pick a scenario (marked in progress). Then generate: plots, gate, labels and a ZIP. All logic lives in core/ and validation/; this
file only collects choices and shows results.
"""
import os
import sys
import tempfile
import time

import pandas as pd
import streamlit as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.devices import Device, Part, list_devices, list_parts, save_device  # noqa: E402
from core.events import EVENTS, compatible_events, list_scenarios, load_scenario  # noqa: E402
from core.output import plot_run, run, zip_run  # noqa: E402
from core.quantities import CATALOG  # noqa: E402
from core.world import list_presets, load_preset  # noqa: E402

TWEAKABLE = ("accuracy", "noise_sd", "t90_s", "resolution")
st.set_page_config(page_title="Synthetic sensor data", layout="wide")
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


def show_results(results):
    if all(r.get("passed") for r in results):
        st.success(f"Generated {len(results)} device file(s); every gate passed")
    else:
        st.error("At least one device failed its gate; see the table below")
    st.download_button("Download ZIP (CSV, labels, manifest, gate)", data=zip_run(results),
                       file_name="synthetic_run.zip", mime="application/zip")
    for r in results:
        import json
        with open(r["gate"]) as fh:
            g = json.load(fh)
        st.subheader(f"{r['device']}: gate {'PASSED' if g['passed'] else 'FAILED'}")
        with st.spinner("Plotting…"):
            st.pyplot(plot_run(r["csv"], r["labels"], r["manifest"]))
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Gate checks**")
            st.dataframe(pd.DataFrame([{"": "✅" if c["passed"] else "❌", "check": c["name"], "column": c["column"],
                                        "value": str(c["value"]), "threshold": str(c["threshold"])}
                                       for c in g["checks"]]), hide_index=True, width="stretch")
        with c2:
            st.markdown("**What happened** (labels; scope expected = what the device should do)")
            st.dataframe(pd.read_csv(r["labels"]), hide_index=True, width="stretch")
        st.markdown("**First rows of the CSV**")
        st.dataframe(pd.read_csv(r["csv"]).head(20), hide_index=True, width="stretch")


BUILD, SCENARIO = "Build a device", "A scenario (in progress)"
mode = st.sidebar.radio("Start from", [BUILD, SCENARIO])
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

else:
    st.sidebar.markdown("**1. Parts**")
    parts = st.sidebar.multiselect("Parts (sensors from datasheets)", list_parts(),
                                   format_func=lambda s: f"{Part.load(s).name} ({s})")
    name = st.sidebar.text_input("2. Name your device", "My Device")
    interval = st.sidebar.number_input("Logging interval (s)", 1, 3600, 60)
    entries, logic = [], []
    for slug in parts:
        p = Part.load(slug)
        with st.expander(f"{p.name}: measures {', '.join(p.quantities())}"):
            st.caption(f"Datasheet: {p.datasheet}")
            ov = {}
            for q, params in p.measures.items():
                rows = [{"parameter": k, "value": str(v(x)), "unit": x.get("unit"), "source": x.get("source"),
                         "kind": x.get("kind", "")} for k, x in params.items()]
                st.markdown(f"`{q}`")
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
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
        st.info("Pick at least one part in the sidebar.")
        st.stop()
    st.sidebar.markdown("**3. World and run**")
    needed = {q for slug in parts for q in Part.load(slug).quantities()}
    worlds = [w for w in list_presets() if needed <= world_quantities(w)]
    if not worlds:
        st.error("No world provides everything this device measures (" + ", ".join(sorted(needed)) +
                 "). Add the missing drivers to a world (docs/HOW_TO_ADD_A_WORLD.md) or pick other parts.")
        st.stop()
    world = st.sidebar.selectbox("World (only those that provide what the parts measure)", worlds,
                                 format_func=lambda n: f"{world_title(n)} ({n})")
    mount = st.sidebar.radio("Mount", ["fixed", "body"], horizontal=True,
                             help="body: worn by the moving person; fixed: on a wall, shelf or post")
    hours = st.sidebar.number_input("Duration (h)", 1, 72, 8)
    seed = st.sidebar.number_input("Seed", 0, 2 ** 31 - 1, 42)
    spec = {"name": name, "parts": entries,
            "features": {"sample_interval_s": {"value": int(interval), "unit": "s", "source": "ASSUMPTION: set in the UI"}}}
    if logic:
        spec["logic"] = logic
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
    st.markdown(f"**4. Events this device can see in {world_title(world)}** "
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
        st.dataframe(pd.DataFrame([{"event": r["name"], "why not": r["why"]} for r in rows if not r["ok"]]),
                     hide_index=True, width="stretch")
    if st.button("Generate", type="primary"):
        scenario = {"name": "ui_run", "title": f"{dev.name} in {world_title(world)}", "realism": "ASSUMPTION",
                    "world": world, "duration": f"{int(hours)}h", "seed": int(seed),
                    "devices": [{"device": dev, "mount": mount}], "events": chosen}
        t0 = time.time()
        try:
            with st.spinner("Generating…"):
                st.session_state["results"] = run(scenario, seed=int(seed),
                                                  out_dir=os.path.join(out_dir, f"{dev.slug}_{seed}_{int(t0)}"))
            st.session_state["took"] = time.time() - t0
        except Exception as e:
            st.session_state.pop("results", None)
            st.error(f"Generation failed: {e}")

if st.session_state.get("results"):
    st.caption(f"took {st.session_state.get('took', 0):.1f} s")
    show_results(st.session_state["results"])
