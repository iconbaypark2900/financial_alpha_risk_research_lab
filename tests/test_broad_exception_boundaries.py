"""What each broad `except Exception` in this project is actually protecting.

Seven of them were flagged as one finding. They are not one pattern, and a
single shared justification would be the wrong annotation for most of them:
some record a failed outcome and re-raise, and some deliberately swallow. The
distinction is the whole point — "records the failure before re-raising" is a
false description of a clause that discards the error.

The four in this project's own recording layer are pinned here, by behaviour:

  * `_git` swallows a failure to RUN git and degrades to None. That is right
    for a box without git and wrong for anything else, because `git_state`
    turns None into "clean tree, commit UNKNOWN" — a permanent record that
    positively claims the working tree was clean.
  * `environment()` swallows a broken package listing, because a distribution
    with unreadable metadata must not stop a run being recorded at all.
  * `Mirror.fetch` deletes the partial download and re-raises as MirrorError,
    and has to be broad to do it: `http.client.IncompleteRead` — a truncated
    download, the exact case the cleanup exists for — is an HTTPException and
    not an OSError.

Each test below fails if the clause it covers is narrowed past what it protects
or widened past what it should swallow.
"""
from __future__ import annotations

import http.client
import importlib.metadata
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.research_integrity.mirror import Mirror, MirrorError  # noqa: E402
from src.research_integrity.run_record import (  # noqa: E402
    ExperimentLog,
    _git,
    environment,
    git_state,
)


@pytest.fixture()
def repo(tmp_path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=r, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=r, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=r, check=True)
    (r / "strategy.py").write_text("VALUE = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=r, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=r, check=True)
    return r


# --- run_record._git: swallows the environment, not everything --------------

@pytest.mark.parametrize("failure", [
    FileNotFoundError(2, "No such file or directory: 'git'"),
    PermissionError(13, "Permission denied"),
    subprocess.TimeoutExpired(cmd="git", timeout=30),
])
def test_a_box_that_cannot_run_git_degrades_to_none(monkeypatch, repo, failure):
    """The reason the clause exists. Narrowing it away would break these."""
    def boom(*args, **kwargs):
        raise failure

    monkeypatch.setattr(subprocess, "run", boom)
    assert _git(repo, "rev-parse", "HEAD") is None


def test_a_failure_that_is_not_gits_is_not_swallowed(monkeypatch, repo):
    """A diff too large to buffer is not "git is not installed".

    `_git` captures output into memory, so `git diff HEAD --binary` on a tree
    holding a large modified file can raise MemoryError. Swallowing it returns
    None, which `git_state` reads as "nothing is modified".
    """
    def boom(*args, **kwargs):
        raise MemoryError("cannot buffer the diff")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(MemoryError):
        _git(repo, "diff", "HEAD", "--binary")


def test_a_dirty_tree_is_never_recorded_as_clean_because_the_diff_failed(
        monkeypatch, repo, tmp_path):
    """The consequence, which is why this one is worth narrowing.

    git runs, HEAD resolves, and only the calls that inspect the working tree
    fail. Swallowing those gives `code_dirty=0` beside a real commit SHA: a
    permanent record stating the tree was clean, with nothing in it to suggest
    otherwise. FR-24 exists to stop exactly that, and `allow_uncommitted=True`
    is meant to buy a full diff rather than an exemption.
    """
    (repo / "strategy.py").write_text("VALUE = 2\n")   # uncommitted change
    assert git_state(repo)["dirty"] is True            # ...and git can see it

    real = subprocess.run

    def inspecting_the_tree_runs_out_of_memory(cmd, *args, **kwargs):
        if any(a in ("status", "diff", "ls-files") for a in cmd):
            raise MemoryError("cannot buffer the diff")
        return real(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", inspecting_the_tree_runs_out_of_memory)
    log = ExperimentLog(tmp_path / "runs.db", repo=repo)
    with pytest.raises(MemoryError):
        log.start("momentum", params={}, seeds={"deterministic": 0},
                  dataset_versions=["v1"], allow_uncommitted=True)

    assert log.query() == [], (
        "a run was recorded even though the state of the code could not be "
        "determined")


# --- run_record.environment(): swallows, on purpose -------------------------

def test_a_broken_package_listing_does_not_stop_a_run_being_recorded(
        monkeypatch, repo, tmp_path):
    """Enumerating site-packages touches metadata this project did not write.

    One distribution with an unreadable METADATA must not be able to stop a run
    being recorded — the environment is context, and the reproducibility
    contract is the SHA, the diff, the seeds and the dataset versions.
    """
    def boom():
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    monkeypatch.setattr(importlib.metadata, "distributions", boom)

    env = environment()
    assert env["packages"] == []
    assert env["python"] == sys.version.split()[0]

    log = ExperimentLog(tmp_path / "runs.db", repo=repo)
    run_id = log.start("momentum", params={}, seeds={"deterministic": 0},
                       dataset_versions=["v1"])
    assert log.get(run_id) is not None


# --- Mirror.fetch: cleans up and re-raises as one error type ----------------

class _TruncatedResponse:
    """A download that dies part-way, the way a real one does."""

    def __init__(self, first: bytes) -> None:
        self._first: bytes | None = first

    def __enter__(self) -> "_TruncatedResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self, _n: int) -> bytes:
        if self._first is not None:
            block, self._first = self._first, None
            return block
        # NOT an OSError: HTTPException sits beside Exception, so narrowing the
        # clause to OSError leaves the .partial on disk and lets a non-Mirror
        # error out of a Mirror method.
        raise http.client.IncompleteRead(b"", 4096)


def test_a_truncated_download_is_cleaned_up_and_reported_as_a_mirror_error(
        monkeypatch, tmp_path):
    assert not issubclass(http.client.IncompleteRead, OSError)

    monkeypatch.setattr("urllib.request.urlopen",
                        lambda *a, **k: _TruncatedResponse(b"PK\x03\x04partial"))
    dest = tmp_path / "companyfacts.zip"

    with pytest.raises(MirrorError, match="could not fetch"):
        Mirror.fetch("https://example.invalid/companyfacts.zip", dest,
                     contact="t@t")

    assert not dest.with_suffix(".zip.partial").exists(), (
        "a partial download survived; the next verify() would hash a truncated "
        "archive")
    assert not dest.exists()
