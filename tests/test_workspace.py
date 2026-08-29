"""The workspace: the controls only work if they outlive the process.

Every script in this repository built its trial counter, holdout and run log
inside a TemporaryDirectory. The counter is append-only and refuses deletes by
SQLite trigger — and was discarded minutes later, so FR-08's "across all
researchers and all time" meant "within this invocation". These tests are about
persistence, because for a control that works by accumulating, ephemeral is the
same as absent.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("duckdb", reason="the workspace owns the point-in-time store")

from src.research_integrity.workspace import (
    DEFAULT_HOME,
    ENV_HOME,
    Workspace,
    default_home,
)

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def lab(tmp_path: Path) -> Workspace:
    return Workspace.open(tmp_path / "lab")


def test_opening_creates_the_directory_and_a_manifest(tmp_path):
    home = tmp_path / "new"
    assert not home.exists()
    lab = Workspace.open(home)
    assert home.is_dir()
    manifest = json.loads((home / "workspace.json").read_text(encoding="utf-8"))
    assert manifest["created_at"]
    assert "resets the global trial count" in manifest["note"]


def test_reopening_keeps_the_original_creation_date(tmp_path):
    """Age is evidence. If reopening reset it, a workspace could never be shown
    to be old, which is the whole point of recording it."""
    first = Workspace.open(tmp_path / "lab")
    created = json.loads((first.home / "workspace.json").read_text())["created_at"]
    again = Workspace.open(tmp_path / "lab")
    assert json.loads((again.home / "workspace.json").read_text())["created_at"] == created


def test_the_default_home_is_outside_any_checkout(monkeypatch):
    """A workspace tied to a clone loses the accumulated trial count the first
    time someone clones fresh — the one number that must not reset."""
    monkeypatch.delenv(ENV_HOME, raising=False)
    assert default_home() == DEFAULT_HOME
    assert ROOT not in default_home().parents
    monkeypatch.setenv(ENV_HOME, "/tmp/elsewhere")
    assert default_home() == Path("/tmp/elsewhere")


def test_every_store_lives_under_the_home(lab):
    for path in (lab.facts_path, lab.trials_path, lab.holdout_path, lab.runs_path):
        assert path.parent == lab.home


# --- the property the module exists for ------------------------------------

def test_the_trial_count_survives_a_new_process(tmp_path):
    """Not a new object in the same process — a genuinely separate interpreter,
    which is how researchers actually run things."""
    home = tmp_path / "lab"
    script = (
        "import sys; sys.path.insert(0, %r)\n"
        "from src.research_integrity.workspace import Workspace\n"
        "w = Workspace.open(%r)\n"
        "c = w.counter()\n"
        "for i in range(5):\n"
        "    t = c.start_trial('ds')\n"
        "    c.record_outcome(t, sharpe=0.01 * i)\n"
        "print(c.trial_count('ds'))\n"
    ) % (str(ROOT), str(home))

    counts = []
    for _ in range(3):
        out = subprocess.run([sys.executable, "-c", script], capture_output=True,
                             text=True, cwd=ROOT, timeout=120)
        assert out.returncode == 0, out.stderr
        counts.append(int(out.stdout.strip()))
    assert counts == [5, 10, 15], f"the count did not accumulate: {counts}"


def test_holdout_exhaustion_survives_a_new_workspace_object(lab):
    """The counter that made 'a holdout you can reset is not a holdout' true."""
    lab.holdout().define("ds", start="2025-01-01", end="2025-12-31")

    def look(n: int) -> dict:
        holdout = lab.holdout()          # a fresh object each time, same file
        reg = holdout.preregister(
            "ds", strategy_family="fam",
            hypothesis=f"variant {n} beats the benchmark on drawdown",
            expected_result="max drawdown between 8% and 14%")
        return holdout.evaluate(reg, observed={"max_drawdown": 0.1})

    assert look(1)["evaluations"] == 1
    assert look(2)["evaluations"] == 2
    assert "EXHAUSTION" in look(3)["warning"]
    assert look(4)["exhausted"] is True


def test_run_records_accumulate(lab, tmp_path):
    log = lab.log(repo=tmp_path)         # a non-repo, so FR-24 is not the subject
    assert lab.provenance()["runs_recorded"] == 0


# --- making a reset conspicuous --------------------------------------------

def test_provenance_reports_age_beside_the_count(lab):
    """A trial count is only evidence of search intensity if it accumulated.
    Reported alone it cannot tell 40 backtests from a directory deleted this
    morning, and those imply opposite things about a deflated Sharpe."""
    counter = lab.counter()
    for i in range(7):
        counter.record_outcome(counter.start_trial("ds"), sharpe=0.01 * i)

    p = lab.provenance()
    assert p["trials_total"] == 7
    assert p["trials_by_dataset"] == {"ds": 7}
    assert p["age_days"] is not None and p["age_days"] >= 0
    assert p["created_at"]
    assert str(lab.home) == p["home"]


def test_describe_puts_the_age_in_the_sentence(lab):
    counter = lab.counter()
    counter.record_outcome(counter.start_trial("ds"), sharpe=0.1)
    described = lab.describe()
    assert "days old" in described
    assert "1 trials" in described


def test_a_wiped_workspace_reads_as_young_rather_than_as_experienced(tmp_path):
    """The honest ceiling. Triggers defend rows against SQL; nothing defends a
    directory against `rm`. What can be done is make the reset visible."""
    import shutil

    home = tmp_path / "lab"
    lab = Workspace.open(home)
    counter = lab.counter()
    for i in range(40):
        counter.record_outcome(counter.start_trial("ds"), sharpe=0.01 * i)
    assert lab.provenance()["trials_total"] == 40

    shutil.rmtree(home)
    fresh = Workspace.open(home)
    after = fresh.provenance()
    assert after["trials_total"] == 0, "the count is gone, as it must be"
    assert after["age_days"] < 1, "and the workspace now reads as new"


# --- it wires a Study without temporaries ----------------------------------

def test_the_workspace_builds_a_study_on_its_own_stores(lab, tmp_path):
    study = lab.study("ds", repo=tmp_path)
    assert study.counter.db_path == str(lab.trials_path)
    assert study.dataset_id == "ds"


def test_the_demo_scripts_stay_ephemeral_on_purpose():
    """A guard against a well-meant "fix".

    null_benchmark_demo.py and readme_tables.py build their counters in a
    TemporaryDirectory deliberately: their output is pinned by
    tests/test_readme_is_true.py, so a persistent counter would make the
    deflated Sharpe drift every run and the documentation tests would fail for
    a reason unrelated to correctness. The workspace commit makes the opposite
    look like an oversight, so the reason is written into both files and
    asserted here.
    """
    for name in ("null_benchmark_demo.py", "readme_tables.py"):
        source = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "TemporaryDirectory" in source, f"{name} lost its temp counter"
        assert "DO NOT \"FIX\" THEM" in source, (
            f"{name} must explain why its counters are deliberately thrown away")
        assert "Workspace" not in source, (
            f"{name} must not use the persistent workspace; its output is "
            "asserted by the README tests and would drift")


def test_no_demonstration_defaults_to_a_persistent_workspace():
    """The safe path must be the lazy one.

    For twenty minutes both demo scripts resolved `--home` to None and handed
    that to `Workspace.open`, which falls back to ~/.financial-alpha-research-lab
    — so the documented bare invocation added 2,691 demo trials to the
    production count, and `believed_strategy.py` spent a look at the real
    holdout. That is precisely the harm install_workspace.py exists to prevent,
    arriving through a different door: the seeding path was fixed and the
    running path was left open.

    A demonstration must opt IN to touching real state. This asserts the shape
    that makes that true — the fallback is a scratch path, never `args.home`
    alone.
    """
    for name in ("real_data_pipeline.py", "believed_strategy.py"):
        source = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "args.home if args.home else" in source, (
            f"{name} must fall back to a throwaway workspace, not to the "
            "default home")
        assert "Workspace.open(args.home)" not in source, (
            f"{name} passes args.home straight through; when it is None that "
            "resolves to the production workspace")
        assert "--ephemeral" not in source, (
            f"{name} still offers --ephemeral, which implies persistence is "
            "the default — it must not be")


def test_only_the_installer_targets_the_default_home():
    """install_workspace.py is the one script whose job IS the real workspace,
    and it runs no search, so it cannot pollute a trial count."""
    installer = (ROOT / "scripts" / "install_workspace.py").read_text(encoding="utf-8")
    assert "Workspace.open(args.home)" in installer
    for forbidden in ("run_search", "search_series", "run_backtest"):
        assert forbidden not in installer, (
            f"the installer must not {forbidden}: a fresh workspace's trial "
            "count should be zero because nothing was searched")


def test_the_research_scripts_do_use_the_workspace():
    """The other direction. believed_strategy.py printed "the registration is
    spent" while building its holdout in a TemporaryDirectory, so the next run
    got a fresh, unspent one — the demonstration of exhaustion was the thing
    defeating exhaustion."""
    for name in ("real_data_pipeline.py", "believed_strategy.py",
                 "install_workspace.py"):
        source = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "Workspace" in source, f"{name} must persist its controls"
