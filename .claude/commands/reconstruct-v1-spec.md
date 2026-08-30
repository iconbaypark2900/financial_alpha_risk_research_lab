---
description: Close the §5.5 hole — the V1 portfolio layer was built against a specification nobody has read
---

# Reconstruct the V1 requirements (PRD 04 §5.5)

## The problem, in the repository's own words

> **"Correct against the literature" is not "meets §5.5", and nothing here can
> tell the difference.** A portfolio layer can implement the Kelly criterion
> flawlessly and still be the wrong thing to have built.
>
> — `docs/REQUIREMENTS.md`, §5.5

`src/portfolio/` is roughly 900 lines committed against an unread section. Every
V0 module opens by quoting the requirement it implements; `src/portfolio/` quotes
a **section number**. The only FR numbers in it — FR-14 and FR-23 — are borrowed
from V0 to explain design decisions, not requirements V1 satisfies.

## Preferred path: find the document

`docs/REQUIREMENTS.md` already names the two ways to close this, in order.
Option 1 is to put PRD 04, or a copy of §5.5, into `docs/`. Before reconstructing
anything, search for it:

- `docs/superseded/` holds the project's **original** spec in four formats
  (`.md`, `.json`, `.xml`, `.pdf`). It contradicts the current README on Neo4j,
  Backtrader, Vault, OPA and MLflow, so it is not PRD 04 — but check whether it
  carries a portfolio-construction section that PRD 04 plausibly inherited, and
  say clearly whether what you found is the document or an ancestor of it.
- Check `.spark-flow/memory/` and the parent directory the README says the old
  link resolved into.

If you find it, the job changes: quote §5.5 at the top of each `src/portfolio/`
module the way every V0 module does, and turn the §5.5 section of
`docs/REQUIREMENTS.md` into a status table like the four above it. Stop there.

## Fallback: an honest reconstruction

If the document is not reachable, write down what §5.5 is *believed* to require
and **mark it a reconstruction of unknown fidelity**. That is worse than the
document and better than the current state, where the requirement is neither
written down nor known to be missing by anyone who has not read that page.

Derive candidate requirements from what is actually built, and label each with
where it came from:

| module | verified against | what that does and does not establish |
|---|---|---|
| `kelly.py` | Kelly (1956), Thorp (2006) §7 | correct mathematics; silent on scope |
| `drawdown.py` | Martin & McCann (1989) for Ulcer | correct mathematics; silent on scope |
| `simulator.py` | its own closed forms | correct by construction; silent on scope |

## House rules

- **Never let a reconstruction pass as the spec.** Every reconstructed
  requirement carries the label in the same sentence, not in a footnote.
- Do not invent FR numbers for §5.5. `tests/test_requirements_map.py` fails if
  `docs/REQUIREMENTS.md` invents a requirement the code has never heard of —
  and inventing V1 numbers would make the map lie in a new direction.
- Keep the existing warning intact: treat every V1 status claim as "correct
  mathematics, unverified scope" until the document is in the repository.
- `src/portfolio/` is **not** a control and must not start looking like one.
