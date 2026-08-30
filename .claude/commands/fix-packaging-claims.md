---
description: The distribution artefact fails its own suite, and three packaging claims are asserted by nothing
---

# Fix the packaging claims

Companion to `/add-quality-gates`, which covers lint, types and coverage. This one
covers what the package *is* when it leaves the repository.

## The sdist cannot pass its own test suite

There is no `MANIFEST.in`. `python -m build` ships `tests/` but **not**
`requirements.txt`, `scripts/` or `docs/`, and setuptools injects a generated
`setup.cfg`. Built, unpacked, and run:

```
9 failed, 493 passed, 6 errors
```

Including `test_there_is_no_second_pytest_config` (the sdist's `setup.cfg`
contains `[egg_info]`), `test_the_two_dependency_files_agree`
(`FileNotFoundError` on `requirements.txt`), and four `test_workspace.py`
failures from the missing `scripts/` directory.

The project's own distribution artefact is self-contradicting, and the failure is
invisible because CI only ever tests a git checkout. Add a `MANIFEST.in`, and add
a CI job that builds the sdist and runs the suite inside it — otherwise this
regresses silently the moment anyone adds a test that reads a file.

## Three claims nothing asserts

1. **The CI file is the only claim-bearing file in the repo no test reads.**
   `grep -rn 'workflows\|tests.yml\|github' tests/*.py` returns nothing. Yet
   `README.md:48`, `:73`, `:79-81` and `pyproject.toml:30-32` make three checkable
   claims about it: "508 tests pass, on every push", "CI runs 3.12, 3.13 and 3.14",
   and "A CI job installs the minimal form and asserts the degradation." Delete
   the minimal job or drop 3.12 from the matrix and all three documents are wrong
   with a green suite. Every other assertion here is pinned by a test; this one
   should be too.

2. **The `nautilus_trader` <3.15 cap is asserted nowhere, and pyproject's
   justification is false.** `pyproject.toml:30-32` says the upper bound is left
   out of metadata because "The CI matrix checks the range rather than leaving it
   asserted in a metadata file." The matrix is 3.12/3.13/3.14 — three versions all
   *inside* the range — so it never tests the boundary. `requires-python` has no
   cap and neither extra carries a `python_version` marker, so on 3.15
   `pip install -e '.[all]'` fails with a bare resolver error. Either encode the
   cap or correct the comment; a deliberate decision resting on a false
   justification is worse than either.

3. **Declared dependency floors are never installed, and one is broken on a
   supported Python.** Every specifier is a lower bound with no lock file, and CI
   always resolves the newest release — so the minimums are pure assertion.
   `pytest>=7.0.0` (`pyproject.toml:47`) is falsifiable and false: pytest 7.0.0
   cannot collect the suite on Python 3.14 (`ast.Str` was removed), and 3.14 is
   both a matrix entry and the only version the minimal job uses. The same pin
   passes on 3.12, confirming it is version-specific. Raise the floor to something
   true, and consider a CI job that installs the declared minimums.

   Note CI never runs `pip install -r requirements.txt` at all — it installs only
   `-e '.[all]'` and `-e '.[dev]'`. The file that carries the reasoning for every
   dependency is never exercised.

## One metadata gap

`pyproject.toml` declares no `license`, no classifiers and no authors, so the
built wheel identifies Apache-2.0 only by bundling the file — no
`License-Expression`, no Trove classifier, no named copyright holder anywhere in
the repository. Tools that read metadata rather than file contents (SBOM
generators, dependency scanners) will report the package as unlicensed. Trivial
to fix, and it matters for the credibility-asset positioning.

## House rules

- `test_packaging.py` has two guards that bite here — see `/add-quality-gates`
  for the one that fails even when both dependency files agree.
- Do not weaken `test_there_is_no_second_pytest_config` to make the sdist pass.
  The sdist should stop shipping a competing config; the test is right.
- Verify each fix by building and running, not by reading the config.
