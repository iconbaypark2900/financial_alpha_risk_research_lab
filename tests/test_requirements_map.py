"""`docs/REQUIREMENTS.md` must agree with the code about which FRs exist.

PRD 04 is not in this repository, so that page is the only place the twenty-five
requirements are listed together. A status board that drifts is worse than none:
it is read instead of the code, and it looks authoritative while doing it.

That is not hypothetical here. Four superseded specs sat unmarked in the
repository root until 2026-08-28 (now `docs/superseded/`), and they were the
source of both a dependency file pinning 26 unused packages and a backlog
recommending semantic-retrieval work for a project with no retrieval. A stale
document in a prominent place does damage in proportion to how official it
looks.

These tests cannot check the page against PRD 04 — nobody here has it. They
check the two things that are checkable: the page covers every requirement the
code cites, and it invents none that the code has never heard of.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MAP = ROOT / "docs" / "REQUIREMENTS.md"
FR = re.compile(r"FR-\d{2}")


def _numbers(text: str) -> set[str]:
    return set(FR.findall(text))


@pytest.fixture(scope="module")
def documented() -> set[str]:
    return _numbers(MAP.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def cited_in_code() -> set[str]:
    found: set[str] = set()
    # All of src/, not just research_integrity: src/portfolio/ cites FR-14 and
    # FR-23 and was invisible to this guard, so a requirement referenced only
    # from the V1 package would not have to appear in the map at all.
    for path in (ROOT / "src").rglob("*.py"):
        found |= _numbers(path.read_text(encoding="utf-8"))
    return found


def test_the_map_covers_every_requirement_the_code_cites(documented, cited_in_code):
    missing = sorted(cited_in_code - documented)
    assert not missing, (
        f"{missing} are cited in src/ but absent from docs/REQUIREMENTS.md. "
        "A requirement implemented but unlisted is invisible to anyone reading "
        "the status board instead of the code.")


def test_the_map_invents_no_requirements(documented, cited_in_code):
    """The other direction, which matters more than it sounds.

    A row for a requirement nothing implements reads as coverage. This is how
    the superseded specs in docs/superseded/ did their damage.
    """
    invented = sorted(documented - cited_in_code)
    assert not invented, (
        f"{invented} appear in docs/REQUIREMENTS.md but nothing in src/ cites "
        "them. Either implement them or remove the rows.")


def test_the_map_accounts_for_all_twenty_five(documented):
    expected = {f"FR-{n:02d}" for n in range(1, 26)}
    assert documented == expected, (
        f"missing {sorted(expected - documented)}, "
        f"unexpected {sorted(documented - expected)}")


def test_every_requirement_carries_a_status(documented):
    """A row without one of the three permitted statuses is an opinion."""
    text = MAP.read_text(encoding="utf-8")
    rows = [line for line in text.splitlines()
            if line.startswith("| FR-")]
    assert len(rows) == 25, f"expected 25 requirement rows, found {len(rows)}"
    allowed = ("met", "**partial**", "**not implemented**")
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        assert cells[2] in allowed, (
            f"{cells[0]} has status {cells[2]!r}; must be one of {allowed}")


def test_the_summary_counts_match_the_rows():
    """The count at the bottom is recomputed, not trusted."""
    text = MAP.read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if line.startswith("| FR-")]
    tally = {"met": 0, "**partial**": 0, "**not implemented**": 0}
    for row in rows:
        tally[[c.strip() for c in row.strip("|").split("|")][2]] += 1

    for label, key in (("met", "met"), ("partial", "**partial**"),
                       ("not implemented", "**not implemented**")):
        assert f"| {label} | {tally[key]} |" in text, (
            f"summary says something other than {tally[key]} for {label!r}")


def test_the_superseded_specs_are_not_in_the_repository_root():
    """They read as the authoritative spec while sitting there, and they
    contradict the README on Neo4j, Backtrader, Vault, OPA and MLflow."""
    # Only the spec documents themselves. An editable install drops a
    # `financial_alpha_risk_research_lab.egg-info/` directory here, which git
    # ignores and this test used to report as a returned specification.
    spec_suffixes = {".md", ".xml", ".json", ".pdf"}
    strays = sorted(p.name for p in ROOT.glob("financial_alpha_risk_research_lab*")
                    if p.is_file() and p.suffix in spec_suffixes)
    assert not strays, (
        f"{strays} are back in the repository root. They are superseded by "
        "PRD 04; they belong in docs/superseded/ with the note explaining why.")


def test_nothing_imports_the_retired_finguard_package():
    """finGuard is retired to docs/superseded/ with thirteen known defects.

    Its own 23 tests still pass from there, which is precisely why the directory
    is a hazard rather than a resource: working-looking code with a sign
    inversion in it, one import away. The replacements are in src/portfolio/.
    """
    import re

    offenders = []
    for area in ("src", "tests", "scripts"):
        for path in (ROOT / area).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if re.search(r"^\s*(?:from|import)\s+finguard\b", source, re.MULTILINE):
                offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, (
        f"{offenders} import the retired finGuard package. Use src/portfolio/ — "
        "the finGuard versions invert position signs and understate recovery "
        "time by 41.5% at a 50% drawdown.")


def test_the_migration_inbox_is_gone():
    """It was an inbox with nothing left to deliver. Everything it held is
    either superseded, rewritten, or deliberately out of scope."""
    assert not (ROOT / "migration_inbox").exists(), (
        "migration_inbox/ is back. finGuard was retired to "
        "docs/superseded/finGuard/ on 2026-08-28.")


def test_the_retired_finguard_carries_its_warning():
    """A retired directory without a note explaining why is just an old
    directory, and the next reader will treat it as a resource."""
    note = ROOT / "docs" / "superseded" / "finGuard" / "RETIRED.md"
    assert note.exists(), "docs/superseded/finGuard/RETIRED.md is missing"
    text = note.read_text(encoding="utf-8")
    assert "Do not import" in text
    assert "thirteen defects" in text
