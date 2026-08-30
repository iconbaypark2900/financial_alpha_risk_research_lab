---
description: Add console entry points so the seam is the obvious path, not just the documented one
argument-hint: "[optional: subcommand to add, e.g. 'study run']"
---

# Give the controls a command-line surface

## Why

`pyproject.toml` declares **no console scripts**. Everything runs as
`python3 scripts/<name>.py`. Four of the five scripts in `scripts/` are
demonstrations; `install_workspace.py` is the installer and is the closest thing
to an interface today — its own docstring section is titled "WHY THIS IS SEPARATE
FROM THE DEMOS", and two tests encode that distinction. Preserve it. For a tool run by its author that is fine; it
is the first blocker for anyone else adopting it.

There is a design argument too, and it is the repository's own: `Study` exists
so that the honest path is easier than the dishonest one. A CLI whose only
backtest verb goes through the seam makes that true at the shell, where most
people actually start.

## Scope

Add a `[project.scripts]` entry point and a `src/research_integrity/cli.py`.
Suggested surface — argue with it if the code suggests better:

```
falrl status                  # Study.status(): trials, var, holdout, runs recorded
falrl study run               # a backtest through the seam, refusals and all
falrl study search            # a sweep through the seam
falrl holdout register        # FR-11 pre-registration, recorded before the run
falrl holdout evaluate        # FR-12, permanent, exhaustion-flagged
falrl log query               # FR-25: by strategy, factor, date range, outcome
falrl log replay              # FR-23: re-execute and require an identical hash
falrl workspace install       # what scripts/install_workspace.py does today
```

`scripts/install_workspace.py` already has a `--home` / `--status` argument
shape worth reusing rather than reinventing.

## Constraints that are specific to this repository

- **Core is numpy alone.** The CLI must import and give a useful error when
  DuckDB or NautilusTrader is absent, not traceback. `PointInTimeStore` and
  `run_backtest` are `None` in the minimal install, and CI asserts that.
- **No default store, counter, holdout or log.** `Study.__post_init__` refuses
  when any is `None`, on the grounds that a study missing one is a study with
  that control switched off. The CLI must not quietly supply defaults and undo
  that; it should resolve them from the persistent workspace and fail loudly
  when there is no workspace.
- **Use the workspace, not a `TemporaryDirectory`.** `workspace.py` exists
  because every script in this repository created the trial counter in a temp
  dir, so the global count reset to zero on every run and the deflated Sharpe
  was computed against one script's search intensity. A CLI that repeats that
  reintroduces the exact bug the module was written to fix.
  `tests/test_workspace.py::test_the_research_scripts_do_use_the_workspace`
  polices this for scripts — extend it to cover the CLI.
- Exit codes should distinguish a **refusal** (a control fired: holdout
  violation, uncommitted code, non-point-in-time dataset) from a **crash**.
  A refusal is the tool working.

## Tests

- Each subcommand has a test that runs it end to end against a temp workspace.
- A refusal path exits non-zero with the control's message on stderr, and the
  trial counter is unchanged where the refusal preceded counting.
- The minimal install (numpy only) can run `falrl --help` and `falrl status`.

## Done when

`pip install -e .` puts `falrl` on the path, the README's "Running it" section
leads with it, and `python scripts/...` is documented as the demo path it is.
