"""
xdk.py — Bosch XDK profile. Wraps the existing generator and gates without changing them.

Scenarios are discovered from configs/:
  * joint-template scenario = a config folder holding <sensor>_joint.json files (robot_arm_6,
    robot_arm). Every sensor is generated with the same seed and duration, which gives them one
    shared cycle schedule, exactly as cli/run_robot_arm_joint.sh does. The full physics gate
    (per-sensor + cross-sensor, thresholds from gate_thresholds.json next to the bank) validates
    them, and it is used as a filter: up to MAX_ATTEMPTS seeds.
  * per-column scenario = any other config JSON (configs/<folder>/<name>.json), one sensor file.
    No physics gate exists for these; only the quaternion validity check, which needs no real
    recording, is run (when the output has orientation columns).

Generation calls cli/main.py in a subprocess with the same arguments as the CLI path, so a file
from the UI is byte-identical to one from the command line.
"""
import glob
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

from .base import ERROR, NOT_VALIDATED, PARTIAL, GateCheck, GateReport, SensorProfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAX_ATTEMPTS = 5
# Copies of the real recordings shipped with the repo (byte-identical to the files the banks were
# built from). Used when the bank's own real path is not present, e.g. in a fresh clone.
REAL_FALLBACK = [os.path.join(ROOT, "data", "arm6", "original", "{sensor}.csv.gz")]
GATE_SPAN_S = 3600.0          # gate thresholds are derived for 60-min outputs vs real first 60 min
MIN_JOINT_DURATION_S = 600.0  # shorter outputs leave the gate's C2ST without enough windows
ARM_LABELS = {"robot_arm_6": "Robot arm, six sensors (joint template)",
              "robot_arm": "Robot arm, sensor_1-3 (joint template, three-sensor bank)"}


def _run_main(config, output, duration_s, seed):
    cmd = [sys.executable, os.path.join(ROOT, "cli", "main.py"), "--config", config, "--output", output,
           "--duration", str(duration_s), "--seed", str(seed), "--no-physics-gate"]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"generation failed for {os.path.basename(config)}:\n{r.stderr[-2000:]}")
    return output


class XDKProfile(SensorProfile):
    name = "xdk"
    label = "Bosch XDK"

    def __init__(self, configs_root: str = None):
        self.configs_root = configs_root or os.path.join(ROOT, "configs")
        self._banks = {}

    # scenario discovery
    def _joint_configs(self, scenario):
        return sorted(glob.glob(os.path.join(self.configs_root, scenario, "*_joint.json")))

    def is_joint(self, scenario: str) -> bool:
        return "/" not in scenario and bool(self._joint_configs(scenario))

    def scenarios(self) -> list:
        joint, legacy = [], []
        for d in sorted(os.listdir(self.configs_root)):
            p = os.path.join(self.configs_root, d)
            if not os.path.isdir(p):
                continue
            if self._joint_configs(d):
                joint.append(d)
            for f in sorted(glob.glob(os.path.join(p, "*.json"))):
                b = os.path.basename(f)
                if b.endswith("_joint.json") or b == "gate_thresholds.json":
                    continue
                legacy.append(f"{d}/{b[:-5]}")
        joint.sort(key=lambda s: (s != "robot_arm_6", s))
        return joint + legacy

    def scenario_label(self, scenario: str) -> str:
        if self.is_joint(scenario):
            return ARM_LABELS.get(scenario, f"{scenario} (joint template)")
        return f"{scenario} (per-column generator, no physics gate)"

    def bank(self, scenario):
        if scenario not in self._banks:
            from core.joint_template import JointBank
            cfg = self._joint_configs(scenario)[0]
            with open(cfg) as fh:
                bank_file = json.load(fh)["motion"]["bank"]
            self._banks[scenario] = JointBank(os.path.join(os.path.dirname(cfg), bank_file))
        return self._banks[scenario]

    def sensors(self, scenario) -> list:
        if self.is_joint(scenario):
            return [os.path.basename(c)[:-len("_joint.json")] for c in self._joint_configs(scenario)]
        return [scenario.split("/")[1]]

    # durations
    def max_duration_s(self, scenario):
        return float(self.bank(scenario).recording_s) if self.is_joint(scenario) else None

    def min_duration_s(self, scenario):
        return MIN_JOINT_DURATION_S if self.is_joint(scenario) else 60.0

    def default_duration_s(self, scenario):
        if self.is_joint(scenario):
            return min(GATE_SPAN_S, self.max_duration_s(scenario))
        with open(os.path.join(self.configs_root, scenario + ".json")) as fh:
            return float(json.load(fh).get("duration_s", 3600.0))

    def max_attempts(self, scenario):
        return MAX_ATTEMPTS if self.is_joint(scenario) else 1

    def limitations(self, scenario, duration_s):
        if not self.is_joint(scenario):
            return ["No physics gate exists for this scenario; only quaternion validity is checked "
                    "(when the output has orientation columns)."]
        rec = self.max_duration_s(scenario)
        L = ["Sensor → arm-link mapping: **[USER TO VERIFY]**. Files are named by XDK sensor, not by robot "
             "joint; which link each sensor sits on is not confirmed.",
             "C2ST (classifier two-sample test) is reported, not blocking: a classifier can still tell this "
             "data from real, mainly by acceleration and magnetometer."]
        if scenario == "robot_arm_6":
            L.append("Check 7a (activity correlation between sensors) passes with a practical margin of 0.02 that "
                     "was chosen after seeing the results (post hoc); against the statistical bound alone, several "
                     "pairs sit about 0.01 below real.")
        if abs(duration_s - GATE_SPAN_S) > 1:
            L.append(f"The gate thresholds are derived for 60-min outputs compared with the real first 60 min. At "
                     f"{duration_s / 60:.1f} min, span-dependent checks (omega p99, mag_world, cross-sensor, C2ST) "
                     "are not calibrated and may fail or pass for that reason alone.")
        if duration_s > rec:
            L.append(f"Duration exceeds the recording ({rec / 60:.1f} min): drift outside the recording is not "
                     "modelled; cycles past it come from the whole pool.")
        return L

    # generation
    def generate(self, scenario, duration_s, seed, out_dir, progress=None):
        os.makedirs(out_dir, exist_ok=True)
        if self.is_joint(scenario):
            jobs = [(c, os.path.join(out_dir, f"{s}_seed{seed}.csv"))
                    for c, s in zip(self._joint_configs(scenario), self.sensors(scenario))]
        else:
            jobs = [(os.path.join(self.configs_root, scenario + ".json"),
                     os.path.join(out_dir, f"{scenario.split('/')[1]}_seed{seed}.csv"))]
        done = 0
        with ThreadPoolExecutor(max_workers=min(6, len(jobs))) as ex:
            futs = [ex.submit(_run_main, c, o, duration_s, seed) for c, o in jobs]
            for f in as_completed(futs):
                f.result()
                done += 1
                if progress:
                    progress(done / len(jobs), f"generated {done}/{len(jobs)} sensor file(s)")
        return [o for _, o in jobs]

    # validation
    def real_paths(self, scenario) -> dict:
        bank = self.bank(scenario)
        out = {}
        for s in bank.sensors:
            cands = [bank.real_path(s)] + [p.format(sensor=s) for p in REAL_FALLBACK]
            hit = next((p for p in cands if os.path.exists(p)), None)
            if hit is None:
                raise FileNotFoundError(f"real recording for {s} not found (looked in: {', '.join(cands)})")
            out[s] = hit
        return out

    def validate(self, scenario, csv_paths):
        if self.is_joint(scenario):
            from validation.physics_gate import check_physics_gate, load_thresholds
            bank = self.bank(scenario)
            syn = {os.path.basename(p).split("_seed")[0]: p for p in csv_paths}
            try:
                real = self.real_paths(scenario)
            except FileNotFoundError as e:
                return GateReport(ERROR, message=str(e))
            thr = load_thresholds(os.path.join(os.path.dirname(bank.path), "gate_thresholds.json"))
            try:
                rep = check_physics_gate(syn, {s: real[s] for s in syn}, bank.period, cross_sensor=True, thresholds=thr)
            except Exception as e:                       # report, do not hide, a gate that cannot run
                return GateReport(ERROR, message=f"the physics gate could not run: {type(e).__name__}: {e}")
            return GateReport.from_physics(rep)
        return self._validity_only(csv_paths)

    def _validity_only(self, csv_paths):
        from validation import validate_physics as V
        from validation.physics_gate import THRESHOLDS
        checks = []
        for p in csv_paths:
            d = V.load(p)
            if not all(c in d.columns for c in ("orientation_x", "orientation_y", "orientation_z")):
                continue
            qx, qy, qz, _ = V.quat_cols(d)
            s = np.nan_to_num(qx) ** 2 + np.nan_to_num(qy) ** 2 + np.nan_to_num(qz) ** 2
            pct = float(100 * np.mean(s > 1 + THRESHOLDS["s_tol"]))
            checks.append(GateCheck("validity", os.path.basename(p).split("_seed")[0], pct,
                                    f"= 0 % of s > 1+{THRESHOLDS['s_tol']}", pct == 0.0, f"max s {s.max():.5f}"))
        if not checks:
            return GateReport(NOT_VALIDATED, message="No physics gate exists for this scenario.")
        return GateReport(PARTIAL, checks, "No physics gate exists for this scenario; only quaternion validity "
                                           "(no real recording needed) was checked.")

    # figures
    def plot(self, scenario, csv_paths, seed, duration_s, out_dir):
        if not self.is_joint(scenario):
            return []
        real = self.real_paths(scenario)
        span = min(duration_s, self.max_duration_s(scenario))
        zoom = (1200.0, 1380.0) if span >= 1380 else (span / 3, span / 3 + min(180.0, span / 3))
        syn_dir = os.path.dirname(sorted(csv_paths)[0])
        os.makedirs(out_dir, exist_ok=True)

        def one(s):
            k = s.split("_")[-1]
            cmd = [sys.executable, os.path.join(ROOT, "experiments", "plot_real_vs_syn_arm.py"), "--syn-dir", syn_dir,
                   "--seed", str(seed), "--sensors", k, "--span", str(span), "--zoom", str(zoom[0]), str(zoom[1]),
                   "--out", out_dir, "--real", f"{s}={real[s]}",
                   "--label", f"synthetic joint-template ({span / 60:.0f} min)"]
            r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"plot failed for {s}:\n{r.stderr[-2000:]}")
            return os.path.join(out_dir, f"{s}_orientation_accel_real_vs_syn.png")
        with ThreadPoolExecutor(max_workers=6) as ex:
            return list(ex.map(one, self.sensors(scenario)))
