---
description: Rename the top-level package from `src` to `research_integrity` — mechanical, and cheaper now than later
---

# Rename the top-level package

## Why now

The install path is `src.research_integrity`, so the installed top-level package
is literally `src`. `pyproject.toml` defends this and the defence holds *today*:

> It is kept because this is an internal tool that is never published, the
> README documents that import path throughout, and renaming it is a change to
> the public API rather than a packaging detail.

That reasoning expires the moment the project is published or imported alongside
anything else that made the same choice. The same file already records the move
and calls it mechanical. **It gets more expensive with every README reference,
so do it before publishing, not after.**

If the decision is to stay internal forever, close this out by saying so
explicitly rather than leaving the note as standing debt.

## The move

`src/research_integrity/` → `research_integrity/` at the repository root, and
`src/portfolio/` → decide: `portfolio/` at the root, or nested under
`research_integrity/`? They are deliberately separate packages answering
different questions, so root-level is the faithful move — but `portfolio` is
nearly as generic a top-level name as `src`, so consider `falrl_portfolio` or
a shared namespace.

## Everything that has to move with it

Use `git mv`, then grep — do not trust a single pass:

- `pyproject.toml`: `[tool.setuptools] packages`, and the `pythonpath = ["."]`
  note under `[tool.pytest.ini_options]` (its comment explains why it exists —
  keep the reasoning, update the paths).
- Every `from src.` / `import src.` in `src/`, `tests/`, `scripts/`.
- `README.md` — it documents the import path throughout, and the pyproject
  comment names that as the reason the rename was deferred.
- `docs/REQUIREMENTS.md`, `docs/LIAISON_PROJECT_BRIEF.md`, `docs/SPEC_*.md`.
- `tests/test_requirements_map.py` scans `src/` for FR references (`ROOT / "src"`,
  ~line 45). It does **not** pass vacuously — it half-fails, confusingly: the
  `cited_in_code` fixture feeds two assertions in opposite directions, so
  `test_the_map_covers_every_requirement_the_code_cites` goes vacuous while
  `test_the_map_invents_no_requirements` fails loudly, reporting all 25 FRs as
  invented. The rename is caught here, but the error message points the wrong way.
  Update the path and confirm both directions still work.
- `tests/test_study.py::test_no_control_is_orphaned` globs
  `src/research_integrity/*.py` for call sites. This one has **no** vacuous-pass
  risk — it asserts the caller list is non-empty, so a glob over a directory that
  no longer exists fails immediately on the first control
  (`FR-07: nothing outside point_in_time.py calls '.require_point_in_time('`).
  It is a signpost, not a silent hazard.
- `.github/workflows/tests.yml` — the `minimal` job imports
  `src.research_integrity` inline in a heredoc.
- `financial_alpha_risk_research_lab.egg-info/` is stale build output; regenerate.
- `.gitignore`, if it has path-specific entries.

## The specific danger

Two tests in this suite work by **scanning the source tree**. A rename that
leaves them pointing at a directory that no longer exists turns them into tests
that pass because they check nothing — exactly the failure mode the causality
checker hit when NaN compared equal to NaN. Verify each one still fails when
given something it should reject, before you call this done.

## Done when

`pip install -e '.[all]'` works from a clean venv, `pytest -q` is green with 508
tests, the two scanning tests have been shown to still fail on bad input, and no
`src.` reference survives anywhere in the repository.
