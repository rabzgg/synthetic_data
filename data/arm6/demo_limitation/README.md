# Demo of a limitation: synthetic data from only 10 minutes of input

**This is not a usable dataset.** It shows what happens when the real input is shorter than the
synthetic output.

Sensor → arm-link mapping: **[USER TO VERIFY]**.

- **Input:** the first 10 min of the six recordings, from their common start. The bank is built
  from that window only: 15 cycles of 37 s.
- **Output:** `synthetic_10min_input/sensor_k_seed42.csv.gz`, 60 min per sensor (seed 42), same
  engine and settings as `../synthetic/`.
- **Plots:** `plots/` (real first 60 min vs this output).

**What goes wrong.**
- One hour is built from 15 real cycles, repeated.
- The real data keeps changing slowly over the hour (XDK heading drift, sub-degree tilt, accel
  and mag variation). The synthetic data stops changing after minute 10, which the orientation
  panels of the plots show.
- A classifier separates it from real data easily: C2ST 0.87–0.90, against 0.54–0.64 for
  `../synthetic/`.
- The physics gate fails 12 checks (`results/joint_template/arm6/demo_limitation_10min_gate.log`, removed from the tree, in git history at 34b07df):
  - mag_world on sensor_1 and sensor_5;
  - omega p99 on sensor_3 and sensor_6;
  - copy on sensor_4 (13 %);
  - activity correlation on 7 sensor pairs.

**Rule that follows:** generate at most as much synthetic time as there is real input.
