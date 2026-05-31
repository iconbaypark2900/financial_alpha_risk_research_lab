# Integration Plan: finGuard → financial_alpha_risk_research_lab

## Status

- Source project: `finGuard`
- Target project: `financial_alpha_risk_research_lab`
- Merge policy: `merge_finance_risk_features`
- Domain: `financial_risk_management`
- Migration inbox: `migration_inbox/finGuard`
- Generated: Sat May 30 09:18:28 PM EDT 2026

## Goal

Integrate useful capabilities from `finGuard` into `financial_alpha_risk_research_lab` without blindly copying scaffolding, duplicate configs, generated artifacts, or obsolete app shells.

## Recommended integration strategy

1. Treat `migration_inbox/finGuard` as a read-only reference snapshot.
2. Review docs and technical papers first.
3. Extract algorithms, domain models, utilities, and tests into target-native modules.
4. Do not import duplicate project scaffolding directly unless the target lacks it.
5. Keep source project archived only after target integration is validated.

## Candidate assets to review

See:

- `docs/merge_plans/finGuard_inventory.md`

## Integration checklist

### Documentation

- [ ] Review source README and technical papers.
- [ ] Move useful architecture notes into target docs.
- [ ] Add a short "Imported from finGuard" note to target docs if useful.

### Source code

- [ ] Identify reusable modules.
- [ ] Decide target-native module location.
- [ ] Copy only selected code, not full app scaffolding.
- [ ] Rename imports and package names to target conventions.
- [ ] Remove duplicated CLI/app entrypoints unless needed.

### Tests

- [ ] Identify source tests worth preserving.
- [ ] Port tests into target test framework.
- [ ] Run target test suite.
- [ ] Add regression tests for imported behavior.

### Dependencies

- [ ] Compare source dependency files with target dependencies.
- [ ] Add only missing runtime dependencies.
- [ ] Avoid duplicate package managers or environment files.

### Security/privacy

- [ ] Confirm no secrets, local env files, or private keys were staged.
- [ ] Review PDFs/sample data for sensitive content before publishing.
- [ ] Remove generated outputs if not needed.

### Finalization

- [ ] Commit integrated target-native code.
- [ ] Leave `migration_inbox/finGuard` until integration is validated.
- [ ] Mark source repo as `merged_to_financial_alpha_risk_research_lab` in Liaison registry.
- [ ] Archive source repo after review.

## Suggested first extraction

Start with risk and allocation modules:

- `src/finguard/kelly.py`
- `src/finguard/drawdown.py`
- `src/finguard/simulator.py`
- `tests/test_kelly.py`
- `tests/test_drawdown.py`

Target likely areas:

- Kelly sizing
- drawdown controls
- risk simulation
- backtest risk metrics
