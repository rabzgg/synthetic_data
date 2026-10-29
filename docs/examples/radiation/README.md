# Example: adding radioactivity (a gamma dose rate)

Every file a new measurement needs, ready to copy. Each file says where it goes in its first line.

| file here | copy to |
|---|---|
| `quantities/radiation.yaml` | `configs/quantities/` (a new column, in a new group "Radiation") |
| `parts/generic_dose_rate_meter.yaml` | `configs/parts/` (the "Generic" sensor for it) |
| `worlds/outdoor_day_driver.yaml` | paste its lines under `drivers:` in `configs/worlds/outdoor_day.yaml` |
| `events/radiation_source.yaml`, `devices/dose_rate_logger.yaml`, `scenarios/radiation_check.yaml` | `configs/events/`, `configs/devices/`, `configs/scenarios/` (optional) |

Then run `python3 cli/update_docs.py`, `python3 -m pytest -q` and
`python3 cli/generate.py --scenario radiation_check --out out/radiation`. In the app (restart it) the
column "Gamma dose rate" appears in step 1, and Outdoors in step 2. `tests/test_examples.py` does all of
this in a temporary copy of the repo, so `configs/` here stays unchanged.
