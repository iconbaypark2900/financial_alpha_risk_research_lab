"""pyproject.toml and requirements.txt must not drift apart.

Dependencies are declared twice here: in `pyproject.toml`, which tools read, and
in `requirements.txt`, which carries the reasoning for every line and the record
of what was deliberately removed. Both are worth having and two sources of truth
is how drift starts, so the disagreement is a test failure rather than a
discovery.

This is not hypothetical for this repository. `requirements.txt` pinned
`backtrader` after PRD 04 struck it by name, and `neo4j` on the same page as a
README section citing the strike — for months, because nothing compared the file
against anything.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
REQUIREMENTS = ROOT / "requirements.txt"

# PEP 508: strip everything after the name — extras, markers, specifiers.
NAME = re.compile(r"^([A-Za-z0-9._-]+)")


def _normalise(name: str) -> str:
    """PEP 503 normalisation: nautilus_trader and nautilus-trader are one package."""
    return re.sub(r"[-_.]+", "-", name).lower()


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def declared(pyproject) -> set[str]:
    project = pyproject["project"]
    lines = list(project["dependencies"])
    for extra in project.get("optional-dependencies", {}).values():
        lines.extend(extra)
    return {_normalise(NAME.match(line).group(1)) for line in lines}


@pytest.fixture(scope="module")
def pinned() -> set[str]:
    names = set()
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        names.add(_normalise(NAME.match(line).group(1)))
    return names


def test_the_two_dependency_files_agree(declared, pinned):
    only_pyproject = sorted(declared - pinned)
    only_requirements = sorted(pinned - declared)
    assert not only_pyproject and not only_requirements, (
        f"pyproject.toml and requirements.txt disagree — "
        f"only in pyproject: {only_pyproject}; "
        f"only in requirements.txt: {only_requirements}")


def test_every_declared_dependency_is_actually_imported(declared):
    """A dependency nothing imports is the state this file was cleaned out of.

    `nautilus_trader` counts as imported via backtest.py; `pytest` is imported
    by the suite itself. Anything else must appear in an import statement
    somewhere under src/ or tests/.
    """
    sources = list((ROOT / "src").rglob("*.py")) + list((ROOT / "tests").glob("*.py"))
    text = "\n".join(p.read_text(encoding="utf-8") for p in sources)
    imported = set(re.findall(r"^\s*(?:from|import)\s+([A-Za-z0-9_]+)",
                              text, re.MULTILINE))
    imported = {_normalise(name) for name in imported}

    unused = sorted(name for name in declared if name not in imported)
    assert not unused, (
        f"{unused} are declared but imported nowhere. requirements.txt once "
        "pinned 26 such packages, including one the PRD had struck by name.")


def test_the_struck_libraries_have_not_returned(pinned):
    """PRD 04 strikes these two by name, and both were pinned here anyway."""
    for struck, why in (("backtrader", 'PRD 04 section 3: "Backtrader should be struck"'),
                        ("neo4j", 'PRD 04 NG3: "Neo4j struck"')):
        assert struck not in pinned, f"{struck} is back in requirements.txt — {why}"


def test_pytest_is_configured_to_run_from_any_directory(pyproject):
    """The bug this file was added alongside: without `pythonpath`, the suite
    ran only when pytest was invoked from the repository root, which is not how
    most CI configurations invoke it."""
    options = pyproject["tool"]["pytest"]["ini_options"]
    assert options["pythonpath"] == ["."]
    assert options["testpaths"] == ["tests"]


def test_there_is_no_second_pytest_config():
    """pytest.ini was merged into pyproject.toml. Two config files means one of
    them is silently ignored, and which one depends on the pytest version."""
    for stray in ("pytest.ini", "tox.ini", "setup.cfg"):
        assert not (ROOT / stray).exists(), (
            f"{stray} is back; pytest configuration lives in pyproject.toml")
