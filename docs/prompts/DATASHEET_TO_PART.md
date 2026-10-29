# Prompt: datasheet → part YAML

Use this with an LLM that can read the datasheet PDF. Paste everything below the line, then attach
the PDF. **Check every value against the page it cites before committing the file**; the model can
misread tables, and a wrong page number is worse than none.

---

You turn a sensor datasheet into a part file for a synthetic data generator. Output **only** one
YAML document in the format below, then a short list of what you could not find.

**Rules (all mandatory):**

1. Every value you take from the datasheet gets
   `source: "datasheet <document number and revision> p.<page> (<table or line, condition>)"`.
   The page is the page number printed on the datasheet page (or the PDF page if none is printed;
   say which). **Never write a page you did not read the value on.**
2. If the datasheet does not give a value, do not guess it. Either leave the parameter out, or, if
   the sensor clearly needs it (e.g. noise of a gas cell), give a value with
   `source: "ASSUMPTION: <reason> [USER TO VERIFY]"`.
3. Typical vs max: a value from a **Typ** column gets `kind: typical`; from a **Min/Max** column
   (or stated as a guaranteed limit) `kind: max`. Applies to accuracy, accuracy_pct_reading,
   drift_per_hour, cross_axis_pct, misalignment_deg. If both are given, use the max and mention the
   typical in the source text.
4. Keep the datasheet's own units in `unit` (e.g. `Pa`, `mg`, `%RH/year`, `LSB/g`); conversion is
   done by the generator.
5. Prefer the datasheet's wording through `from_datasheet` rules when it is not already a model
   parameter: `range`, `range_symmetric`, `resolution`, `sensitivity_lsb`, `bits` (needs `span`),
   `accuracy`, `accuracy_pct_reading`, `accuracy_pct_fs` (needs `full_scale`), `accuracy_sum`,
   `accuracy_max`, `accuracy_typical`, `noise_rms`, `noise_pp`, `noise_density` (needs
   `bandwidth_hz` or `odr_hz`), `repeatability`, `t90`, `t63`, `t50`, `recovery_t90`, `drift`,
   `hysteresis_pm`, `hysteresis`, `deadband`, `bandwidth`, `odr`, `cross_axis`, `misalignment`,
   `mounting_euler`, `temperature_coefficient`, `cross_gas`.
6. One `measures` entry per physical quantity. Quantity ids must come from this list:
   `<PASTE THE ids FROM configs/quantities/*.yaml>`. If the sensor measures something not in the
   list, say so at the end instead of inventing an id.
7. When a parameter depends on a setting (range, bandwidth, oversampling), state which setting you
   chose in the source text, and list the other settings under `notes`.

**Format:**

```yaml
name: <maker> <model>
datasheet: "<document number>, revision <x>"
measures:
  - quantity: <id from the list>
    params:
      range: {value: [<low>, <high>], unit: "<unit>", source: "datasheet <doc> p.<n> (<condition>)"}
      resolution: {value: <x>, unit: "<unit>", source: "datasheet <doc> p.<n>"}
    from_datasheet:
      - {rule: <rule>, value: <x>, unit: "<unit>", kind: typical|max, source: "datasheet <doc> p.<n> (<condition>)"}
notes:
  - "<settings not modelled, conditions, anything left out>"
```

**After the YAML**, list: values the datasheet does not give; values you were unsure how to read
(with page); settings you had to choose.
