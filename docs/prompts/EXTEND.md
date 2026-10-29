# Prompt: add something the generator does not have yet

For anyone at Bitteiler who needs a column, a sensor, an environment or an event that the app does
not offer yet.

1. Fill in the form below.
2. Open Claude Code in the repository root.
3. Paste everything below the line. Attach the datasheet PDF if you have one.

The app only pictures what a client's sensor data will look like. Nothing about compression belongs
in it.

---

## My request (fill in)

- **What is measured:** <for example nitrogen dioxide in the air>
- **Unit:** <the unit the client's CSV uses, for example ppm>
- **Column name in the client's CSV (if known):** <for example no2_ppm>
- **Logging interval or sampling rate (if known):** <for example every 60 s, or 25 Hz>
- **Sensor model (if known):** <maker and model, or "not named yet">
- **Datasheet (if known):** <link or PDF path, or "none">
- **Where the sensor is (environment):** <the place, what happens there over a day, fixed or worn>
- **Events the client expects to see:** <one line each>
- **Anything else:** <alarm levels the client uses, other columns in the same file>

## Instructions for Claude Code

You extend a synthetic sensor data generator. Almost everything in it is YAML. Work in this order
and do not skip a step.

1. **Read first:** `README.md`, `configs/README.md` and the README in each `configs/` folder, `docs/ARCHITECTURE.md`, `docs/HOW_TO_ADD_A_SENSOR.md`,
   `docs/HOW_TO_ADD_A_WORLD.md`, `docs/HOW_TO_ADD_AN_EVENT.md`, `docs/PRESALES.md` and
   `docs/prompts/DATASHEET_TO_PART.md`.
2. **Check what already exists before writing anything.** Look in `configs/quantities/`,
   `configs/parts/`, `configs/worlds/`, `configs/events/`, `configs/devices/` and
   `configs/scenarios/`.
   A quantity counts as existing when it is the same physical thing, even if the client's unit or
   column name differs. Other units go in `configs/units.yaml`. Vendor column names go in the device
   (section 3b of `docs/HOW_TO_ADD_A_SENSOR.md`).
   Show me a table with three columns: what I asked for, what exists (file), what is missing.
3. **Add only what is missing, as YAML, following the HOW_TO_ADD guides:**
   - a new quantity: an entry in `configs/quantities/<domain>.yaml`
   - every new quantity also gets exactly one generic part: `configs/parts/generic_<name>.yaml`
     (section 3c of `docs/HOW_TO_ADD_A_SENSOR.md`). All its values are assumed, and each says what
     it is anchored on. It is no better than the best datasheet part for that quantity. It gets a
     row in the generic table of `docs/PRESALES.md` and a fixture line in `FIXTURES` at the top of
     `tests/test_quantities.py` (test data, not engine code)
   - a named sensor with a datasheet: a part file following the rules of
     `docs/prompts/DATASHEET_TO_PART.md`
   - a new environment: `configs/worlds/<name>.yaml` with `realism: ASSUMPTION`. It must provide
     every quantity the request needs
   - a new event: `configs/events/<kind>.yaml`. First check whether an existing event can do it
     with a new parameter value or a new entry in its `choices`
   - one scenario that puts the new pieces together: `configs/scenarios/<name>.yaml`. Add its
     name to the `SCENARIOS` list at the top of `validation/run_all_scenarios.py` so the five-seed
     check covers it
4. **Numbers.** Every number is `{value, unit, source}`.
   - A value from the datasheet: `source: "datasheet <document number, revision> p.<page>, <table or
     condition>"`. Only write a page you read the value on.
   - If the PDF cannot be opened, do not guess. Write `ASSUMPTION: <reason> [USER TO VERIFY]` and
     tell me which PDF and which value to check.
   - Every other value: `source: "ASSUMPTION: <reason>"`, saying what it is anchored on.
   - Never change a check threshold, an existing part or an existing world to make a check pass.
5. **Python only when YAML cannot do it:** a new relation between quantities, a new primitive or
   effect operation, a new kind of body motion, or a new logic block.
   **Stop and ask me before writing any Python.** Say what is needed, why YAML cannot do it, and
   which files would change. Then wait for my yes.
6. **Check:**
   - `python3 -m pytest` is green
   - `python3 validation/run_all_scenarios.py` passes everything, including the new scenario
   - `python3 cli/generate.py --scenario <new scenario> --out out/<name>`, then look at the plot
   - `python3 cli/events_doc.py && python3 cli/parameter_mapping.py` to regenerate the docs
7. **Report:**
   - every file added or changed, one line each on what it holds
   - every assumed value and what it is anchored on
   - every datasheet value with its page, and what the datasheet did not give
   - the last lines of the pytest and run_all_scenarios output
   - anything you could not do, and why

   Do not merge to main. Do not touch files that the request does not need.

---

## Example (filled in): NO2 in a basement car park

- **What is measured:** nitrogen dioxide (NO2) in the air
- **Unit:** ppm
- **Column name in the client's CSV (if known):** no2_ppm
- **Logging interval or sampling rate (if known):** every 60 s
- **Sensor model (if known):** not named yet, so use a generic one
- **Datasheet (if known):** none
- **Where the sensor is (environment):** an underground car park, two levels below the street.
  The sensor is fixed on a concrete column at about 1.8 m.
  Exhaust fans run on a timer during opening hours. They switch to full speed on a gas alarm.
  Most cars come in between 7 and 9 and leave between 16 and 18. Little traffic at night.
- **Events the client expects to see:**
  - the morning and evening traffic peaks
  - a fan failure, so that NO2 builds up for an hour or two
  - a car left idling near the sensor for a few minutes
  - the sensor dropping out or getting stuck
- **Anything else:** the client also logs CO in the same file. No alarm levels given yet.

**What a good answer finds for this example** (to check Claude Code's work):

- Already there: `air.co_ppm` with `generic_co_cell`, the events `gas_release`, `sensor_fault` and
  `connection_loss`, and the "Start from columns" page that builds the device.
- Missing: the quantity `air.no2_ppm`, a generic NO2 part (an electrochemical cell), a car park
  environment, and a fan failure.
- The traffic peaks belong to the environment as a `schedule` driver. They are not an event.
- The fans are a named signal in the environment. A fan failure is then an event aimed at that
  signal, like `compressor_failure` in the fridge.
- The idling car can be `gas_release` with `no2` added to its `choices`.
- No Python is expected. One thing worth mentioning: the oxygen relation does not list NO2
  (`GASES` in `core/world/world.py`). At a few ppm that changes O2 by about 0.0001 %vol. That is far
  below the resolution of any O2 sensor, so it can stay as it is.
