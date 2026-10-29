# The UI

```bash
pip install -r requirements.txt                       # includes streamlit
streamlit run ui/app.py --server.address 127.0.0.1    # then open http://localhost:8501
```

`ui/app.py` only collects choices and shows results; generation, compatibility, plots and the ZIP come
from `core/` (`core.output.run`, `core.events.compatible_events`, `core.output.plot_run`,
`core.output.zip_run`) and the gate from `validation/auto_gate.py`.

## Four ways in

**Start from columns** (the default; pre-sales, `docs/PRESALES.md`).
1. "What does the sensor log?": pick the columns, grouped as Air (climate and gas), IMU (motion),
   Electrical, Light, Machine, Soil, Water. Each option reads "Accelerometer: accel_x,y,z_g in g".
   Under the list: "Not in the list? See docs/prompts/EXTEND.md in the repo."
2. "Where is the sensor?": the environment. Only worlds that provide every chosen column are offered.
3. "Which sensor?": per column "Generic (<class>)" or a part from a datasheet that measures it. A part's
   other quantities are not written ("Bosch BME280 (also measures humidity_rh and pressure_hpa, not written)").
4. "Sampling, resolution and noise": the logging interval, and per column resolution, RMS noise and ODR.
   A change shows "Changed noise from a to b (your value, saved as assumed)" and is stored as
   `ASSUMPTION: user tweak`. A sensor whose ODR can be set follows the logging interval, so its noise
   does too. The box "Write counts (LSB)" writes integers = value / resolution. These are the
   compensated reading in LSB, not the raw ADC code of a sensor that needs compensation (BME280).
   Next to each column: range, response time (t90, hidden when 0), bandwidth ("n/a" when none), and
   the accuracy ("zero-g offset" for an accelerometer, "zero-rate offset" for a gyroscope).
5. "Name the device, add events, generate" (sidebar "5. Device": name, mounting, duration, seed).

**Build a device.**
1. "Sensors (from datasheets)": each shows the CSV columns it writes ("Bosch BME280 (temperature_c,
   humidity_rh, pressure_hpa)"). Each sensor shows every parameter with its unit, source and typical or
   max. Accuracy, noise, t90 and resolution can be changed. A threshold alarm can be added per column.
2. Sidebar "2. Device": name and logging interval. "Save this device" writes `configs/devices/<slug>.yaml`
   (a name that exists gets a new version; presets cannot be overwritten).
3. Sidebar "3. Environment": only worlds that provide every quantity the sensors measure.
4. Sidebar "4. Run": mounting (fixed or worn), duration and seed.
5. "Events and generate".

**Example scenarios (work in progress).** Pick one of `configs/scenarios/`, a seed, and generate.
The page works, the layout is not final yet.

**Start from a real CSV (legacy).** The older per-column statistical fit (`core/generator.py`, called
through `ui/legacy.py`). A banner says: "Legacy statistical copy. Each column is fitted on its own, so
columns are not linked by physics. For potential clients without data, use Start from columns." The top
caption about datasheets is hidden on this page.
1. "The real CSV": upload one, or the example (robot arm sensor 1, XDK, 10 Hz). Text columns are left out
   and named. Data logged slower than every 2 s is refused with the interval it found.
2. "Fitted engine per column": engine names in words (for example Constant noise, Periodic motion) and what each
   means. "Download the fitted settings (JSON)" as `<csv name>_config.json`.
3. "Generate": duration in minutes and seed. Then a ZIP `<csv name>_synthetic.zip` (`<csv name>_synthetic.csv` and `<csv name>_config.json`), one plot with a panel
   per column (real dark blue, synthetic light blue, same time axis, over the synthetic duration) and the
   first 20 rows.

In both device ways the events the device can show in that environment are listed by name with one
sentence each. The building blocks of composite events (fall down, lie, stir, rise) sit under
"Building blocks (advanced)". The events it cannot show are listed with a plain reason ("This
environment has no air conditioner."). The event file's `missing` key holds that sentence. The
technical reason stays in `compatible_events(...)["detail"]`, in scenario errors and in the run notes.

## Design

The Bitteiler corporate design: the Rajdhani font and the CD colours (dark blue `#1C3661`, light
blue `#1999CC`). `.streamlit/config.toml` sets the theme and serves the font from `ui/static/fonts`
(self-hosted, so the visitor's browser makes no request to Google). The figures use
`core/output/bitteiler.mplstyle` (from bitteiler_plotstyle 0.2.0) with the same font. Rajdhani has no
µ, ², ³, √ or σ, and those characters fall back to the default font. Rajdhani is under the SIL Open
Font License (`ui/static/fonts/OFL.txt`).

## Words on screen

The screen uses plain words for the code's terms: world = environment, gate = checks, part = sensor,
`ASSUMPTION` = assumed. Slugs, dotted ids (`air.temperature_c`) and repo paths are not shown, except
the pointer to `docs/prompts/EXTEND.md`. An error shows a short sentence, with the original message
under "Details".

## Results

Per device: "<device name>: checks passed" (or failed) and every check, a figure titled "<device> in
<environment> (seed n)" (one panel per column, events shaded and named, gaps yellow, expected device
responses hatched, generic columns marked "(generic)"), the **data summary** (per column: rows, sample
rate, bits per sample, min, max, noise vs resolution, ODR and bandwidth, generic or not), the event
labels, the first 20 rows of the CSV, and one ZIP with the CSV, event labels, settings (manifest),
checks (gate) and summary of every device.

## Not in the UI (do it in the files)

- Event parameters other than the start time (the defaults are used; edit a scenario file for more).
- Several devices in one run when building a device (scenarios can hold several).
- `output_format` (other than raw counts), logic blocks other than a threshold alarm, `log: false`,
  aliases, mounting.
- New quantities, worlds and events (`docs/HOW_TO_ADD_A_WORLD.md`, `docs/HOW_TO_ADD_AN_EVENT.md`; a ready
  prompt for Claude Code is `docs/prompts/EXTEND.md`, linked under the column list in step 1).
