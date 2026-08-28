"""A research workspace that survives the process — PRD 04 §5.2.

WHY THIS EXISTS

FR-08 asks for "a global count of every backtest executed against each dataset,
across all researchers and all time, including runs whose results were
discarded." The counter that implements it is append-only, refuses deletes and
outcome rewrites by SQLite trigger, and was — in every script in this
repository — created inside a `TemporaryDirectory` and destroyed on exit.

So the count reset to zero on every run. The deflated Sharpe was computed
against one script's search intensity rather than the team's cumulative one,
which is the smallest it could possibly be and therefore the most flattering.
The holdout's exhaustion counter reset with it, so every run began with a fresh,
never-peeked holdout — "a holdout you can move after seeing results is not a
holdout, and an exhaustion count you can reset is not a count" is this project's
own line, and the count was being reset every few minutes. The experiment log
was queryable across all runs, of which there was one.

None of those controls were wrong. They were ephemeral, which for a control that
works by ACCUMULATING is the same as being absent.

A WORKSPACE IS A DIRECTORY, AND THAT IS A REAL LIMIT

Nothing here can stop someone deleting it. Triggers defend the rows inside a
database against SQL; they cannot defend the file against `rm`. What this module
does instead is make a reset CONSPICUOUS: the workspace records when it was
created, `provenance()` reports that age beside the trial count, and a workspace
claiming to have vetted a strategy family while being four hours old is visibly
wrong in the report rather than silently wrong in the arithmetic.

That is weaker than prevention and is the honest ceiling for a file. Back the
directory up, and treat its deletion the way you would treat deleting the trade
blotter.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENV_HOME = "RESEARCH_LAB_HOME"
DEFAULT_HOME = Path.home() / ".financial-alpha-research-lab"
MANIFEST = "workspace.json"


def default_home() -> Path:
    """Outside any checkout by default.

    A workspace tied to a clone loses the accumulated trial count the first time
    someone clones fresh, which is precisely the number that must not reset.
    `RESEARCH_LAB_HOME` overrides it; an explicit path beats both.
    """
    return Path(os.environ.get(ENV_HOME, DEFAULT_HOME)).expanduser()


@dataclass(frozen=True)
class Workspace:
    """The four stores that must outlive the process, in one place."""
    home: Path

    @classmethod
    def open(cls, home: str | Path | None = None) -> "Workspace":
        path = Path(home).expanduser() if home is not None else default_home()
        path.mkdir(parents=True, exist_ok=True)
        manifest = path / MANIFEST
        if not manifest.exists():
            manifest.write_text(json.dumps({
                "created_at": datetime.now(timezone.utc).isoformat(),
                "note": ("Deleting this directory resets the global trial count "
                         "and the holdout exhaustion counters. That is the one "
                         "act that defeats the controls; back it up."),
            }, indent=2), encoding="utf-8")
        return cls(home=path)

    # ---- the stores -------------------------------------------------------
    @property
    def facts_path(self) -> Path:
        return self.home / "facts.duckdb"

    @property
    def trials_path(self) -> Path:
        return self.home / "trials.db"

    @property
    def holdout_path(self) -> Path:
        return self.home / "holdout.db"

    @property
    def runs_path(self) -> Path:
        return self.home / "runs.db"

    def store(self):
        from .point_in_time import PointInTimeStore
        return PointInTimeStore(self.facts_path)

    def counter(self):
        from .trial_counter import TrialCounter
        return TrialCounter(self.trials_path)

    def holdout(self):
        from .holdout import ProtectedHoldout
        return ProtectedHoldout(self.holdout_path)

    def log(self, repo: str | Path = "."):
        from .run_record import ExperimentLog
        return ExperimentLog(self.runs_path, repo=repo)

    def study(self, dataset_id: str, *, repo: str | Path = "."):
        """A Study wired to the persistent stores rather than to temporaries."""
        from .study import Study
        return Study(dataset_id=dataset_id, store=self.store(),
                     counter=self.counter(), holdout=self.holdout(),
                     log=self.log(repo=repo))

    # ---- making a reset visible ------------------------------------------
    def provenance(self) -> dict[str, Any]:
        """Age and totals together, so a reset shows up as a young workspace.

        A trial count is only evidence of search intensity if it has been
        accumulating. Reported alone it cannot distinguish "we have run 40
        backtests against this dataset" from "we deleted the directory this
        morning", and those imply opposite things about a deflated Sharpe.
        """
        created = None
        manifest = self.home / MANIFEST
        if manifest.exists():
            try:
                created = json.loads(manifest.read_text(encoding="utf-8")).get(
                    "created_at")
            except (ValueError, OSError):
                created = None

        age_days = None
        if created:
            try:
                age_days = (datetime.now(timezone.utc)
                            - datetime.fromisoformat(created)).total_seconds() / 86400
            except ValueError:
                age_days = None

        counter = self.counter()
        datasets = counter.datasets()
        return {
            "home": str(self.home),
            "created_at": created,
            "age_days": age_days,
            "datasets": datasets,
            "trials_by_dataset": {d: counter.trial_count(d) for d in datasets},
            "trials_total": sum(counter.trial_count(d) for d in datasets),
            "runs_recorded": len(self.log().query()),
        }

    def describe(self) -> str:
        """One paragraph a researcher can paste into a result."""
        p = self.provenance()
        age = ("unknown age" if p["age_days"] is None
               else f"{p['age_days']:.1f} days old")
        return (f"workspace {p['home']} ({age}): {p['trials_total']:,} trials "
                f"across {len(p['datasets'])} dataset(s), "
                f"{p['runs_recorded']} run(s) recorded")
