# The UI

```bash
pip install -r requirements.txt                       # includes streamlit
streamlit run ui/app.py --server.address 127.0.0.1    # then open http://localhost:8501
```

`ui/app.py` only collects choices and shows results; generation, compatibility, plots and the ZIP come
from `core/` (`core.output.run`, `core.events.compatible_events`, `core.output.plot_run`,
`core.output.zip_run`) and the gate from `validation/auto_gate.py`.

## Two ways in

**A scenario.** Pick one of `configs/scenarios/`, a seed, and generate.

**Build a device.**
1. Pick parts (sensors from datasheets). Each part shows every parameter with its unit, source and
   kind; accuracy, noise, t90 and resolution can be changed (a change is marked "ASSUMPTION: user
   tweak"). A threshold alarm can be added per measured quantity.
2. Name the device and set the logging interval. "Save" writes `configs/devices/<slug>.yaml`
   (a name that exists gets a new version; presets cannot be overwritten).
3. Pick a world: only worlds that provide every quantity the parts measure are offered. Pick the
   mount (worn on the body or fixed), duration and seed.
4. The events this device can see in that world are listed with one sentence each; the others are
   listed with the reason. Tick events and set their start.
5. Generate.

## Results

Per device: the gate verdict and every check, a figure (one panel per column, events shaded, gaps
yellow, expected device responses hatched), the labels, the first rows of the CSV, and one ZIP with
the CSV, labels, manifest and gate of every device.

## Not in the UI (do it in the files)

- Event parameters other than the start time (the defaults are used; edit a scenario file for more).
- Several devices in one run when building a device (scenarios can hold several).
- `output_format`, logic blocks other than a threshold alarm, `log: false`, aliases, mounting.
- New quantities, worlds and events (`docs/HOW_TO_ADD_A_WORLD.md`, `docs/HOW_TO_ADD_AN_EVENT.md`).
