# Dell Quotation Agent

An AI quotation-preparation assistant for a fictional office-equipment
distributor selling **Dell monitors**. A salesperson enters an incomplete,
natural-language customer enquiry; the agent clarifies missing requirements,
filters a fixed, evidence-backed monitor catalogue, computes prices with
deterministic tools, and — after human confirmation — produces a traceable,
revisable quotation **draft**.

## Core principle

> **The model understands and asks; deterministic tools own all facts and money.**

The model (or the offline planner) is only allowed to interpret the enquiry and
decide which tool to call. It never invents prices, quantities, totals, or
substitutes a product. All monetary math is integer-cent and `Decimal`-verified
inside `pricing.py`; all product facts come from the frozen catalogue.

> ⚠️ **All prices, discount rules, and enquiries bundled with this package are
> SYNTHETIC demo data.** They are **not** representative of Dell pricing, stock,
> or policy. A `calculate_quote` result is an unsaved, unapproved **draft** —
> it is **not a tax invoice**, and the tools never save, approve, reserve stock,
> export a PDF, or send a message.

This package is a separate top-level package. It **does not modify or depend on
the existing `app/` office-supplies prototype**; the two coexist independently.

## Data package (fetch step)

The catalogue, rules, evidence, knowledge cards, and evaluation sets are mirrored
from the target repository `lwd0110/ISS-Hackson-Quotation-Preparation` into
`dell_agent/data/`, preserving the repo-relative layout:

```text
dell_agent/data/agent/catalog.json                 # 12 Dell monitor SKUs + evidence
dell_agent/data/agent/tool_schemas.json            # OpenAI/Ollama function schemas (3 tools)
dell_agent/data/agent/instructions.md              # system prompt
dell_agent/data/agent/knowledge/MON-*.md           # per-SKU spec cards
dell_agent/data/processed/pricing_rules.json       # synthetic SGD rules
dell_agent/data/evaluation/*.jsonl                 # test-only; never indexed
```

Fetch (or refresh) the data package with the one-time script, which copies the
files via the GitHub CLI:

```bash
python -m dell_agent.scripts.fetch_data
```

Requirements for the fetch step:

- An installed and **authenticated `gh` CLI** (`gh auth login`) with read access
  to the target repo. No data is fabricated on failure — fix the access issue
  and re-run.

The fetched files are **committed**, so once the data is in place the offline
tools and tests run with **only the Python standard library**. PDFs are not
needed at runtime; `pypdf` is required only if you re-extract specs from the
source PDFs (out of scope for normal use).

## The three frozen tools

All three tools take a plain dict of JSON arguments and return a
JSON-serialisable dict (or list). Route every call through
`dell_agent.agent.tools.dispatch(name, args)` — the same entry point used by the
agent loop and the tests.

| Tool | Purpose |
|------|---------|
| `search_products` | Structured, deterministic filtering (never parses a sentence; sorts by price; no silent substitution). |
| `get_product` | One SKU's public specs, synthetic price, and field-level PDF evidence; stock/delivery reported unavailable. |
| `calculate_quote` | Deterministic integer-cent pricing from catalogue prices only; rejects custom prices, bad quantities, and discounts over 5%. |

### CLI / Python examples

`search_products` — the canonical USB-C-video + 90 W host-charging filter
returns exactly `MON-007, MON-008, MON-009, MON-011`, price-ascending:

```bash
python -c "from dell_agent.agent.tools import dispatch; \
print([p['sku'] for p in dispatch('search_products', {'usb_c_video': True, 'min_pd_watts': 90})])"
# ['MON-007', 'MON-008', 'MON-009', 'MON-011']
```

`get_product` — specs + synthetic price (cents) + evidence; unknown SKU returns
`{"found": false, ...}`:

```bash
python -c "from dell_agent.agent.tools import dispatch; \
r = dispatch('get_product', {'sku': 'MON-007'}); \
print(r['found'], r['unit_price_cents'], r['availability_note'], len(r['evidence']))"
# True 28900 not available 8
```

`calculate_quote` — 8 x `MON-007` at zero discount totals `231200` cents and is
within a `250000`-cent budget:

```bash
python -c "from dell_agent.agent.tools import dispatch; \
q = dispatch('calculate_quote', {'items': [{'sku': 'MON-007', 'quantity': 8}], 'budget_cents': 250000}); \
print(q['total_cents'], q['within_budget'])"
# 231200 True
```

Verified monetary anchors (independently reproduced with `Decimal`):
`MON-007` x8 @0 bps = `231200`; `MON-007` x10 @0 bps = `289000` (`39000` over a
`250000` budget); `MON-009` x2 @500 bps = `66310`; `MON-001` x7 @250 bps =
`101692`.

## Running the offline tests

The test suites run offline with **only the Python standard library** — no cloud
credentials and no live model. From the repository root:

```bash
# Discover and run every suite
python -m unittest discover -s dell_agent/tests

# Or run a single suite by module
python -m unittest dell_agent.tests.test_catalog
```

## Organizer LLM Gateway wiring

The deterministic **`OfflineDriver`** needs no external service. The optional **`GatewayDriver`** sends the conversation and provider-neutral schemas to the organizer supplied Gateway, executes every requested tool locally through `dispatch`, and feeds the JSON result back to the model. It supports native `tool_calls` and the Gateway's JSON request fallback.

```python
import os
from dell_agent.agent.loop import GatewayDriver

driver = GatewayDriver(
    base_url=os.environ["LLM_GATEWAY_URL"],
    api_key=os.environ["LLM_GATEWAY_API_KEY"],
    model=os.environ["LLM_MODEL"],
)
result = driver.run("Please quote 8 Dell P2425HE monitors, budget SGD 2500.")
```

When configuration or transport fails, the result contains a visible `gateway_fallback` trace and the deterministic OfflineDriver result. The API key is never written to the result.

Knowledge retrieval (`dell_agent/knowledge.py`) indexes **only** the
`data/agent/knowledge/MON-*.md` spec cards behind an explicit allow-list;
evaluation data, expected answers, and validation reports are never ingested
into any runtime knowledge store.

## Module map

| Module | Responsibility |
|--------|----------------|
| `dell_agent/models.py` | Typed dataclasses: `Product`, `Evidence`, `Rules`, `QuoteLine`, `QuoteDraft`. Unknown facts stay `None`. |
| `dell_agent/data/catalog.py` | Load + fail-fast validation of `catalog.json` and `pricing_rules.json`; cached `all_products()` / `get(sku)` / `rules()`. |
| `dell_agent/pricing.py` | `Decimal` half-up line/quote money math (integer cents only). |
| `dell_agent/agent/tools.py` | The three frozen tools + `dispatch(name, args)`. |
| `dell_agent/agent/state.py` | Deterministic status classifier and clarification/conflict/injection detectors. |
| `dell_agent/agent/loop.py` | `OfflineDriver` (deterministic) and the optional `GatewayDriver` (LLM), both returning a uniform `AgentResult`. |
| `dell_agent/agent/tool_schemas.py` | Loads provider-neutral OpenAI/Ollama function schemas. |
| `dell_agent/knowledge.py` | Allow-listed spec-card (`MON-*.md`) keyword retrieval. |
| `dell_agent/scripts/fetch_data.py` | One-time `gh`-based mirror of the frozen data package. |
| `dell_agent/data/` | Mirrored data package (catalogue, rules, evidence, knowledge, evaluation). |
| `dell_agent/tests/` | Offline, stdlib-only test suites. |
