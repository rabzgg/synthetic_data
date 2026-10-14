"""
base.py — the interface every sensor profile implements, plus the gate report and run record
the UI works with.

A profile knows, for one sensor family: which scenarios exist, how long an output may be, how to
generate the CSVs and how to validate them. It wraps existing engines and gates; it adds no
generation or validation logic of its own.
"""
import io
import json
import os
import zipfile
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Callable, List, Optional

# Report status values
PASSED, FAILED, NOT_VALIDATED, PARTIAL, ERROR = "passed", "failed", "not_validated", "partial", "error"


@dataclass
class GateCheck:
    name: str
    sensor: str
    value: object
    threshold: str
    passed: bool
    note: str = ""
    informational: bool = False      # shown, but does not decide the gate


@dataclass
class GateReport:
    """Pass/fail per check with its value and threshold.

    status: "passed" / "failed" (a gate ran), "partial" (only checks that need no real recording
    ran), "not_validated" (no gate for this scenario), "error" (the gate could not run)."""
    status: str
    checks: List[GateCheck] = field(default_factory=list)
    message: str = ""

    @property
    def passed(self) -> bool:
        return self.status in (PASSED, PARTIAL) and all(c.passed for c in self.checks if not c.informational)

    @property
    def failed_blocking(self) -> List[GateCheck]:
        return [c for c in self.checks if not c.passed and not c.informational]

    @classmethod
    def from_physics(cls, rep) -> "GateReport":
        """From validation.physics_gate.GateReport; same fields as its to_dict()."""
        d = rep.to_dict()
        return cls(PASSED if d["passed"] else FAILED, [GateCheck(**c) for c in d["checks"]])

    def to_dict(self) -> dict:
        return {"status": self.status, "passed": self.passed, "message": self.message,
                "checks": [asdict(c) for c in self.checks]}


@dataclass
class Attempt:
    number: int
    seed: int
    csv_paths: List[str]
    report: GateReport


@dataclass
class Run:
    """Result of generate_validated: the attempt that is returned plus every attempt made."""
    profile: str
    scenario: str
    duration_s: float
    seed_requested: int
    chosen: Attempt
    attempts: List[Attempt]
    max_attempts: int = 1

    def to_dict(self) -> dict:
        return {"sensor_profile": self.profile, "scenario": self.scenario, "duration_s": self.duration_s,
                "seed_requested": self.seed_requested, "seed_used": self.chosen.seed,
                "attempt_used": self.chosen.number, "attempts_made": len(self.attempts),
                "max_attempts": self.max_attempts,
                "status": self.chosen.report.status, "passed": self.chosen.report.passed,
                "attempts": [{"attempt": a.number, "seed": a.seed, "status": a.report.status,
                              "failed_checks": [f"{c.sensor}/{c.name}" for c in a.report.failed_blocking]}
                             for a in self.attempts],
                "message": self.chosen.report.message,
                "checks": self.chosen.report.to_dict()["checks"]}


Progress = Optional[Callable[[float, str], None]]     # (fraction 0..1, text)


class SensorProfile(ABC):
    name: str = ""        # short id, e.g. "xdk"
    label: str = ""       # shown in the UI

    @abstractmethod
    def scenarios(self) -> list:
        """Scenario ids."""

    def scenario_label(self, scenario: str) -> str:
        return scenario

    @abstractmethod
    def max_duration_s(self, scenario: str) -> Optional[float]:
        """Longest output the data supports (e.g. the recording length); None = no limit known."""

    def min_duration_s(self, scenario: str) -> float:
        return 60.0

    def default_duration_s(self, scenario: str) -> float:
        m = self.max_duration_s(scenario)
        return min(3600.0, m) if m else 3600.0

    def max_attempts(self, scenario: str) -> int:
        """> 1: the gate is used as a filter (new seed until it passes, at most this many tries)."""
        return 1

    def limitations(self, scenario: str, duration_s: float) -> List[str]:
        return []

    @abstractmethod
    def generate(self, scenario: str, duration_s: float, seed: int, out_dir: str,
                 progress: Progress = None) -> List[str]:
        """Write the CSVs for one seed into out_dir and return their paths."""

    @abstractmethod
    def validate(self, scenario: str, csv_paths: List[str]) -> GateReport:
        """Run the scenario's gate on generated CSVs."""

    def plot(self, scenario: str, csv_paths: List[str], seed: int, duration_s: float, out_dir: str) -> List[str]:
        """Real-vs-synthetic figures; [] when the profile has none."""
        return []

    def generate_validated(self, scenario: str, duration_s: float, seed: int, out_dir: str,
                           progress: Progress = None) -> Run:
        """Generate, then validate. With max_attempts > 1 the gate is a filter: seeds seed, seed+1, ...
        until one passes. If none passes, the attempt with the fewest failed blocking checks (earliest
        on ties) is returned, marked as failed."""
        n = self.max_attempts(scenario)
        attempts = []
        for i in range(n):
            s = seed + i
            d = os.path.join(out_dir, f"attempt{i + 1}_seed{s}")
            os.makedirs(d, exist_ok=True)

            def sub(f, text, i=i):
                if progress:
                    progress((i + 0.8 * f) / n, f"attempt {i + 1}/{n} (seed {s}): {text}")
            paths = self.generate(scenario, duration_s, s, d, sub)
            if progress:
                progress((i + 0.8) / n, f"attempt {i + 1}/{n} (seed {s}): running the gate")
            rep = self.validate(scenario, paths)
            attempts.append(Attempt(i + 1, s, paths, rep))
            if rep.passed or rep.status in (NOT_VALIDATED, ERROR):
                break
        if progress:
            progress(1.0, "done")
        chosen = next((a for a in attempts if a.report.passed),
                      min(attempts, key=lambda a: (len(a.report.failed_blocking), a.number)))
        return Run(self.name, scenario, duration_s, seed, chosen, attempts, n)

    def readme(self, run: Run) -> str:
        """Short README for the download ZIP."""
        rep = run.chosen.report
        status = {PASSED: "PASSED", FAILED: "FAILED", PARTIAL: "PARTIAL (only checks without real data)",
                  NOT_VALIDATED: "NOT VALIDATED", ERROR: "ERROR"}[rep.status]
        if rep.status == PARTIAL and not rep.passed:
            status = "FAILED (only checks without real data)"
        L = [f"# Synthetic data: {self.label}, {self.scenario_label(run.scenario)}", "",
             f"- Sensor profile: {self.label} (`{self.name}`)",
             f"- Scenario: `{run.scenario}`",
             f"- Duration: {run.duration_s:.0f} s ({run.duration_s / 60:.1f} min)",
             f"- Seed: {run.chosen.seed}" + (f" (requested {run.seed_requested}; attempt {run.chosen.number} of "
                                              f"{run.max_attempts} allowed)" if run.max_attempts > 1 or
                                             run.chosen.seed != run.seed_requested else ""),
             f"- Gate result: **{status}**"]
        if rep.message:
            L.append(f"- Note: {rep.message}")
        if rep.failed_blocking:
            L.append("- Failed blocking checks: " + ", ".join(f"{c.sensor}/{c.name}" for c in rep.failed_blocking))
        if run.max_attempts > 1:
            L += ["", "## Attempts",
                  f"The gate is used as a filter: seeds {run.seed_requested}, {run.seed_requested + 1}, … are tried until "
                  f"one passes (at most {run.max_attempts}). Because the output is selected, passing here "
                  "does not measure how often the generator passes.", ""]
            L += [f"- attempt {a.number}, seed {a.seed}: {a.report.status}"
                  + (" (" + ", ".join(f"{c.sensor}/{c.name}" for c in a.report.failed_blocking) + ")"
                     if a.report.failed_blocking else "") for a in run.attempts]
        lim = self.limitations(run.scenario, run.duration_s)
        if lim:
            L += ["", "## Known limitations", ""] + [f"- {x}" for x in lim]
        L += ["", "## Files", "",
              "- `*.csv`: synthetic data, one file per sensor.",
              "- `gate_report.json`: every check with its value, threshold and pass/fail; all attempts.", ""]
        return "\n".join(L)

    def write_report(self, run: Run, path: str) -> None:
        with open(path, "w") as fh:
            json.dump(run.to_dict(), fh, indent=1, default=float)

    def bundle(self, run: Run) -> bytes:
        """ZIP for download: the chosen attempt's CSVs, gate_report.json and README.md."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for p in run.chosen.csv_paths:
                z.write(p, os.path.basename(p))
            z.writestr("gate_report.json", json.dumps(run.to_dict(), indent=1, default=float))
            z.writestr("README.md", self.readme(run))
        return buf.getvalue()
