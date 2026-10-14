"""
Streamlit UI for the synthetic data generator.

Run from the repo root:  streamlit run ui/app.py

Everything sensor-specific comes from a profile in core/profiles (registry.py). The UI only picks
the inputs, calls profile.generate_validated / plot / bundle, and shows the result.
"""
import os
import random
import sys
import tempfile

import pandas as pd
import streamlit as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.profiles import registry
from core.profiles.base import ERROR, FAILED, NOT_VALIDATED, PARTIAL, PASSED

st.set_page_config(page_title="Synthetic sensor data", layout="wide")
st.title("Synthetic sensor data generator")

# inputs
with st.sidebar:
    st.header("Settings")
    profiles = registry.all_profiles()
    prof = st.selectbox("Sensor", profiles, format_func=lambda p: p.label)
    scenario = st.selectbox("Scenario", prof.scenarios(), format_func=prof.scenario_label,
                            help='"Test:" scenarios force a rare event to appear on purpose.')
    help_lines = prof.scenario_help(scenario)
    if help_lines:
        st.info("\n\n".join(help_lines))
    terms = prof.glossary()
    if terms:
        with st.expander("What do these terms mean?"):
            st.markdown("\n".join(f"- **{k}**: {v}" for k, v in terms.items()))

    max_s, min_s = prof.max_duration_s(scenario), prof.min_duration_s(scenario)
    if max_s:
        hard = prof.hard_max_duration_s(scenario)
        beyond = st.checkbox(f"Allow longer than {max_s / 60:.1f} min", value=False) if hard and hard > max_s else False
        top_min = (hard if beyond else max_s) / 60
    else:
        top_min = 24 * 60.0
    default_min = min(prof.default_duration_s(scenario) / 60, top_min)
    dur_min = st.slider("Duration [min]", min_value=float(min_s / 60), max_value=float(round(top_min, 1)),
                        value=float(round(default_min, 1)), step=0.5)
    duration_s = dur_min * 60
    if max_s and duration_s > max_s:
        st.warning(prof.beyond_max_message(scenario))

    random_seed = st.checkbox("Random seed", value=False)
    seed_in = st.number_input("Seed", min_value=0, max_value=2 ** 31 - 10, value=42, step=1, disabled=random_seed)
    n_try = prof.max_attempts(scenario)
    if n_try > 1:
        st.caption(f"The gate is used as a filter: if the output fails it, seeds seed+1, seed+2, … are tried "
                   f"(at most {n_try} attempts).")
    go = st.button("Generate", type="primary", width="stretch")

# run
if go:
    seed = random.randrange(0, 2 ** 31 - 10) if random_seed else int(seed_in)
    work = tempfile.mkdtemp(prefix="synthetic_ui_")
    bar = st.progress(0.0, text="starting")
    try:
        run = prof.generate_validated(scenario, duration_s, seed, work,
                                      progress=lambda f, t: bar.progress(min(max(f, 0.0), 1.0), text=t))
        bar.progress(1.0, text="plotting real vs synthetic")
        pngs = prof.plot(scenario, run.chosen.csv_paths, run.chosen.seed, duration_s, os.path.join(work, "plots"))
        st.session_state["result"] = {"profile": prof.name, "run": run, "pngs": pngs, "zip": prof.bundle(run),
                                      "events": prof.event_summary(run.chosen.csv_paths)}
        bar.empty()
    except Exception as e:
        bar.empty()
        st.session_state.pop("result", None)
        st.error(f"Generation failed: {type(e).__name__}: {e}")

# results
res = st.session_state.get("result")
if res:
    p = registry.get(res["profile"])
    run = res["run"]
    rep = run.chosen.report
    head = (f"{p.label} · {p.scenario_label(run.scenario)} · {run.duration_s / 60:.1f} min · "
            f"seed {run.chosen.seed}")
    st.subheader(head)

    n = len(run.attempts)
    which = f"attempt {run.chosen.number} of {n} (seed {run.chosen.seed})"
    if rep.status == PASSED:
        st.success(f"{p.gate_name} PASSED" + (f" on {which}." if n > 1 or p.max_attempts(run.scenario) > 1 else "."))
    elif rep.status == FAILED:
        st.error(f"{p.gate_name} FAILED on every attempt ({n}). Showing {which}, the one with the fewest failed "
                 f"blocking checks." if n > 1 else f"{p.gate_name} FAILED.")
    elif rep.status == PARTIAL:
        (st.info if rep.passed else st.error)(rep.message + (" Passed." if rep.passed else " Failed."))
    elif rep.status == NOT_VALIDATED:
        st.warning("Not validated: " + rep.message)
    elif rep.status == ERROR:
        st.error(rep.message)

    if res.get("events"):
        st.markdown("**What happens in this data** (read from the generated CSV, times in UTC)")
        st.markdown(" · ".join(res["events"]))

    if n > 1:
        st.markdown("**Attempts**")
        st.dataframe(pd.DataFrame([{"attempt": a.number, "seed": a.seed, "result": a.report.status,
                                    "failed blocking checks": ", ".join(f"{c.sensor}/{c.name}"
                                                                       for c in a.report.failed_blocking) or "—"}
                                   for a in run.attempts]), hide_index=True, width="stretch")

    if rep.checks:
        st.markdown("**Checks** (✅ pass · ❌ fail · ⚠️ reported only, does not decide the gate)")

        def icon(c):
            return "⚠️" if c.informational else ("✅" if c.passed else "❌")

        def fmt(v):
            return f"{v:.3f}" if isinstance(v, (int, float)) else str(v)
        st.dataframe(pd.DataFrame([{"": icon(c), "sensor": c.sensor, "check": c.name, "value": fmt(c.value),
                                    "required": c.threshold,
                                    "note": (("info: within threshold. " if c.passed else "info: outside threshold. ")
                                             if c.informational else "") + c.note}
                                   for c in rep.checks]), hide_index=True, width="stretch")

    lim = p.limitations(run.scenario, run.duration_s)
    if lim:
        st.markdown("**Known limitations**")
        st.markdown("\n".join(f"- {x}" for x in lim))

    st.download_button("Download ZIP (CSV + gate_report.json + README" +
                       (" + spec + assumptions" if p.extra_files(run) else "") + ")", data=res["zip"],
                       file_name=f"{p.name}_{run.scenario.replace('/', '_')}_seed{run.chosen.seed}.zip",
                       mime="application/zip")

    if res["pngs"]:
        st.markdown(f"**{p.plot_title}**")
        for png in res["pngs"]:
            st.image(png, caption=os.path.basename(png), width="stretch")
else:
    st.info("Pick a sensor, scenario, duration and seed in the sidebar, then press Generate.")
