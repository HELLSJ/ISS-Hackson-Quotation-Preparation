# Formal evaluation — 20260922T072117Z-gateway-first-pass

- Driver: `gateway`
- Model: `global.anthropic.claude-sonnet-4-5-20250929-v1:0`
- Valid real-model run: **True**
- Fallbacks: **0**

## Metrics

| Metric | Passed | Total | Rate |
|---|---:|---:|---:|
| status | 12 | 20 | 60.0% |
| clarification | 2 | 4 | 50.0% |
| selection | 7 | 8 | 87.5% |
| amount | 7 | 8 | 87.5% |
| budget | 1 | 1 | 100.0% |
| over_budget | 1 | 1 | 100.0% |
| policy_block | 0 | 2 | 0.0% |
| evidence | 4 | 4 | 100.0% |
| target_sku | 3 | 3 | 100.0% |

## Failures

- `SEALED-002`: status, selection, amount (pricing_or_tool)
- `SEALED-007`: clarification (requirements_or_state)
- `SEALED-008`: clarification (requirements_or_state)
- `SEALED-009`: status (requirements_or_state)
- `SEALED-010`: status (requirements_or_state)
- `SEALED-013`: status (requirements_or_state)
- `SEALED-014`: status (requirements_or_state)
- `SEALED-015`: status (requirements_or_state)
- `SEALED-019`: status, policy_block (requirements_or_state)
- `SEALED-020`: status, policy_block (requirements_or_state)
