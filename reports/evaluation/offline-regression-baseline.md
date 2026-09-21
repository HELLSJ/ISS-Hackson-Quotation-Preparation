# Offline Regression Baseline

**Recorded at:** 2026-09-20T07:37:37Z  
**Scope:** Local deterministic data validation and `OfflineDriver` regression only. No external LLM or model API was invoked.

## Commands executed

```powershell
python scripts/build_data.py
python scripts/validate_data.py
python -m unittest discover -s dell_agent/tests
```

## Results

| Check | Result |
| --- | --- |
| Derived catalogue rebuild | Passed: 12 products, 12 synthetic prices, 96 field-evidence rows, 6 source records, regenerated JSON and SQLite catalogue cache. |
| Source PDFs | Passed: 6 PDFs, 522 pages, 43,929,093 downloaded bytes. |
| Fixture relationships | Passed: 20 dev cases, 20 existing-holdout regression cases, and matching expected IDs. |
| Tool/data validation suite | Passed: 15 tests, 0 failures, 0 errors. |
| `dell_agent` OfflineDriver suite | Passed: 63 tests, with 7 explicit skips and no failures. |
| Independent Decimal precheck | Passed: 15 expected quote totals matched the independently calculated totals in `money-reconciliation.csv`. |

## Explicit OfflineDriver limitations

The following seven cases are deliberately skipped by the existing OfflineDriver expected-results test. They are visible limitations, not passes:

- `DEV-015`: unknown model token handling;
- `HOLDOUT-008`: strict 24.0-inch diagonal interpretation;
- `HOLDOUT-009`: host-vs-downstream 90 W nuance;
- `HOLDOUT-011`: cable-vs-port 100 W nuance;
- `HOLDOUT-013`: 140 Hz constraint;
- `HOLDOUT-014`: named-SKU over-budget status classification;
- `HOLDOUT-015`: unknown model token handling.

## Interpretation boundary

This is a deterministic OfflineDriver regression baseline. It does **not** measure real LLM accuracy, Gateway tool use, model latency, or a blind holdout score. The repository's current `holdout` fixtures are already loaded by ordinary tests and must be described as a regression set rather than a sealed blind evaluation set.
