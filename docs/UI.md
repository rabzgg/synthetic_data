# The UI

```bash
pip install -r requirements.txt                       # includes streamlit
streamlit run ui/app.py --server.address 127.0.0.1    # then open http://localhost:8501
```

`ui/app.py` only collects choices and shows results; generation, compatibility, plots and the ZIP come
from `core/` (`core.output.run`, `core.events.compatible_events`, `core.output.plot_run`,
`core.output.zip_run`) and the gate from `validation/auto_gate.py`.

## Three ways in

**Start from columns** (the default; pre-sales, `docs/PRESALES.md`).
1. Pick the columns the sensor logs, grouped by domain, each with its unit.
2. Pick the situation: only worlds that provide every chosen column.
3. Per column: "Generic (default): <class>" or a part from a datasheet that measures it; a part's
   other quantities are not logged ("also measures X (not logged)").
4. Sample interval, and per column resolution, noise and ODR (a change is marked "ASSUMPTION: user
   tweak"; a sensor whose rate can be set follows the sample interval, so its noise does too);
   optionally raw counts (integer register / ADC codes).
5. Name, mount, duration, seed, the events it can see, Generate, Save.

**Build a device.**
1. Pick parts (sensors from datasheets); the list shows each part with the CSV columns it writes
   (e.g. "Bosch BME280 → temperature_c, humidity_rh, pressure_hpa"). Each part shows every parameter with its unit, source and
   kind; accuracy, noise, t90 and resolution can be changed (a change is marked "ASSUMPTION: user
   tweak"). A threshold alarm can be added per measured quantity.
2. Name the device and set the logging interval. "Save" writes `configs/devices/<slug>.yaml`
   (a name that exists gets a new version; presets cannot be overwritten).
3. Pick a world: only worlds that provide every quantity the parts measure are offered. Pick the
   mount (worn on the body or fixed), duration and seed.
4. The events this device can see in that world are listed with one sentence each; the others are
   listed with the reason. Tick events and set their start.
5. Generate.

**A scenario (in progress).** Pick one of `configs/scenarios/`, a seed, and generate. It works; its
layout and options are still being finished, so the page is marked in progress.

## Results

Per device: the gate verdict and every check, a figure (one panel per column, events shaded, gaps
yellow, expected device responses hatched, generic columns marked "(generic)"), the **data summary**
(per column: rows, sample rate, bits per sample, min, max, noise / resolution, ODR and bandwidth,
generic or not), the labels, the first rows of the CSV, and one ZIP with the CSV, labels, manifest,
gate and summary of every device.

## Not in the UI (do it in the files)

- Event parameters other than the start time (the defaults are used; edit a scenario file for more).
- Several devices in one run when building a device (scenarios can hold several).
- `output_format` (other than raw counts), logic blocks other than a threshold alarm, `log: false`,
  aliases, mounting.
- New quantities, worlds and events (`docs/HOW_TO_ADD_A_WORLD.md`, `docs/HOW_TO_ADD_AN_EVENT.md`; a ready
  prompt for Claude Code is `docs/prompts/EXTEND.md`, linked under the column list in step 1).
