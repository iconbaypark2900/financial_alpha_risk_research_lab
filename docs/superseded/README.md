# Superseded specification — kept as history, not as guidance

The four files in this directory are the **original** specification for this
project, in four formats produced by the same generator. They were sitting
unmarked in the repository root, where they read as the authoritative spec.

**They are superseded by PRD 04**, and they contradict the current README on
nearly every architectural point:

| These files say | PRD 04 / README says |
|---|---|
| "Neo4j for issuer, insider, sector … graphs" | NG3: *"Not a graph database application. Neo4j struck."* |
| "vectorbt / Backtrader for backtests" | §3: *"Whatever is chosen, Backtrader should be struck."* |
| "Vault for secrets. OPA for access policies" | Out of scope — *"controls that purchase against a threat model that does not exist"* |
| "MLflow for experiments and models" | Ratified 2026-08-28 as SQLite; see `.spark-flow/memory/decisions.md` |
| "Qdrant for embeddings", "OpenSearch … document index" | No retrieval component exists or is planned |

## Why they were doing damage

An outdated document is not inert when it is the most official-looking thing in
the tree. Two concrete consequences, both traced back here:

1. **`requirements.txt` pinned 30 packages, four of which were used.** The
   unused 26 are exactly this document's stack — `neo4j`, `qdrant-client`,
   `opensearch-py`, `torch`, `transformers`, `vectorbt`, the Vault/OPA-era auth
   stack. Including `backtrader`, after PRD 04 struck it by name.

2. **`.spark-flow/memory/tasks/backlog.yaml` recommended "add retrieval quality
   checks" and "prototype semantic retrieval behind the baseline"** for a
   repository with no retrieval. That came from `research_rag_service` in the
   `.xml` here — *"Index research documents and filings"*, *"Serve hybrid
   retrieval"*. The backlog was not hallucinated; it was faithfully generated
   from a spec for a different system.

Both have been corrected. These files are moved rather than deleted so the
lineage stays legible — commit `6eb543f` removed the code built from this spec,
and this is the spec it was built from.

## Condition of the files

- `financial_alpha_risk_research_lab.md` — readable prose; no FR numbers, so
  nothing in the current codebase can cite it.
- `financial_alpha_risk_research_lab.json` — valid JSON.
- `financial_alpha_risk_research_lab.xml` — **malformed**; it does not parse
  (`not well-formed (invalid token): line 2, column 1` — the document opens with
  a closing tag and has no root element).
- `financial_alpha_risk_research_lab_detailed.pdf` — not examined.

## Where the real requirements are

PRD 04 itself is **not in this repository** and is not reachable from it. Every
requirement it imposes is quoted at the top of the module implementing it, and
`docs/REQUIREMENTS.md` collects all 25 into one page with their status. That is
a reconstruction from the code, not a substitute for the document.
