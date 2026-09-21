# Evidence-backed Quotation Preparation Agent

[中文说明](README.zh-CN.md) · [Project plan (Chinese)](docs/project-plan-zh.md) · [API and tool contract](docs/api-contract.md)

A quotation-preparation workbench for a fictional office-equipment distributor. It turns an incomplete English customer enquiry into evidence-backed product candidates and a deterministic SGD quote draft while keeping product selection and approval under human control.

```text
Customer enquiry → clarify requirements → search the frozen catalogue
→ inspect source evidence → user selects a product → deterministic pricing
→ save immutable draft versions → compare versions → confirm → export PDF
```

## Why this project exists

Wholesale sales administrators repeatedly search catalogues, verify product specifications, calculate discounts, and rebuild quotation files when customers change quantities. That work is slow and error-prone, especially when requirements such as “USB-C” are ambiguous.

This project demonstrates a safer division of responsibility:

> **The model understands language and asks questions; deterministic tools own every fact and every cent.**

The model and browser cannot provide a unit price, calculate a total, silently substitute a SKU, or turn an unknown specification into a fact. Product facts come from frozen source records, and important fields link back to a Dell manual and PDF page.

> [!IMPORTANT]
> Product specifications come from publicly accessible Dell manuals. Prices, discount rules, and customer enquiries are synthetic hackathon data. They do not represent Dell pricing, stock, delivery commitments, or commercial policy. A calculated or saved draft is not an approved quotation or tax invoice.

## Current status

The usable vertical slice and backend quote lifecycle are complete: deterministic tools, an offline Agent, FastAPI, SQLite persistence, a responsive three-panel workbench, local source-PDF evidence, immutable schema-v2 draft versions, append-only confirmation, structured diff, and confirmed-snapshot PDF export.

| Area | Status |
|---|---|
| Source data | 6 Dell manuals, 522 pages, about 43.9 MB |
| Catalogue | 12 monitor SKUs and 12 synthetic SGD prices |
| Evidence | 96 field-level records with source ID, PDF page, and method |
| Evaluation fixtures | 20 development, 20 holdout, and 3 fixed demo scenarios |
| Canonical tools | `search_products`, `get_product`, and `calculate_quote` through one dispatcher |
| Offline Agent | Clarification, limitations, policy blocking, pricing, and revisions |
| Application | FastAPI + `app.sqlite` + browser workbench |
| Saved versions | Validated schema-v2 snapshots; immutable, idempotent, and protected against stale saves |
| Confirmation | Append-only immutable confirmed snapshot with exact-token idempotency |
| Version diff and quote PDF | Backend APIs complete; PDF is confirmed-snapshot-only and never re-prices |
| Automated validation | 38 catalogue/backend/failure-path/evaluation-gate tests; 63 Agent tests with 7 documented heuristic skips |
| Live Bedrock run | **Not completed**: no verified live model trace yet |
| Independent data review | Complete: 24/24 evidence checks signed and dataset `2026-09-14.v1` frozen |
| Browser confirmation/diff/PDF controls | Implemented and exercised end to end in headless Chrome |
| Formal model/holdout evaluation | **Not completed** |

The authoritative remaining-work sequence and acceptance criteria are in the [consolidated project plan](docs/project-plan-zh.md).

## Quick start

The web application requires Python 3.10 or newer.

```bash
git clone https://github.com/HELLSJ/ISS-Hackson-Quotation-Preparation.git
cd ISS-Hackson-Quotation-Preparation
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. The default `OfflineDriver` needs no cloud credentials. The browser stores the current conversation ID, while `storage/app.sqlite` remains the authoritative store for messages and saved draft versions.

FastAPI documentation is available at <http://127.0.0.1:8000/docs> while the server is running.

### Try the main demo

Use the three built-in demo shortcuts or enter these turns:

```text
We need 8 monitors with USB-C. Budget SGD 2500.
Video plus at least 65W charging; 23.8-inch FHD is acceptable.
Choose P2425HE at zero discount.
```

The pricing tool returns SGD 2,312.00. Save that as version 1, then enter:

```text
Change quantity to 10 units.
```

The revised draft is SGD 2,890.00, which is SGD 390.00 over budget. Saving it creates version 2 without changing version 1.

## Architecture

```text
Browser workbench (`app/static/`)
  → FastAPI (`app/main.py`)
      → QuotationService
          → OfflineDriver
          → ConverseDriver → Amazon Bedrock Converse (optional)
      → canonical tool dispatcher (`dell_agent.agent.tools.dispatch`)
          → frozen catalogue, pricing rules, and field evidence
      → `storage/app.sqlite`
          → conversations
          → messages + AgentResult/trace
          → immutable quote_versions + append-only confirmations
      → allow-listed local Dell source PDFs
      → stored-snapshot diff and confirmed quote-PDF renderer
```

`storage/catalog.sqlite` is a regenerable catalogue cache. `storage/app.sqlite` stores application conversations and saved quote-draft snapshots. Neither database is committed.

## Canonical tools

All runtime paths—CLI, OfflineDriver, ConverseDriver, FastAPI, and tests—use:

```python
from dell_agent.agent.tools import dispatch
```

| Tool | Responsibility |
|---|---|
| `search_products` | Applies explicit structured filters. Unknown values do not satisfy a filter; no match returns an empty list; exact model aliases prevent suffix substitution. |
| `get_product` | Returns one SKU’s public specifications, synthetic price, field-level evidence, and unavailable stock/delivery fields. |
| `calculate_quote` | Uses catalogue prices only, integer cents, per-line half-up discount rounding, and a maximum discount of 500 bps. |

`scripts/catalog_tools.py` is only a CLI/compatibility adapter and contains no second pricing engine. The frozen result and error shapes are documented in [docs/api-contract.md](docs/api-contract.md).

Examples:

```bash
# USB-C video plus at least 90 W host charging
python scripts/catalog_tools.py search_products \
  '{"usb_c_video":true,"min_pd_watts":90}'

# Inspect one SKU and its evidence
python scripts/catalog_tools.py get_product '{"sku":"MON-007"}'

# Quote 8 P2425HE units within a SGD 2,500 budget
python scripts/catalog_tools.py calculate_quote \
  '{"items":[{"sku":"MON-007","quantity":8}],"budget_cents":250000}'
```

Verified pricing anchors:

| Scenario | Expected result |
|---|---:|
| `MON-007` × 8 at 0 bps | 231,200 cents; within a 250,000-cent budget |
| `MON-007` × 10 at 0 bps | 289,000 cents; 39,000 cents over budget |
| `MON-009` × 2 at 500 bps | 66,310 cents |
| `MON-001` × 7 at 250 bps | 101,692 cents |

## Data and evidence

The catalogue covers three size groups, four resolutions, no/65 W/90 W USB-C host power, and an important data-only trap:

- `usb_c_video` means the upstream USB-C/Thunderbolt connection accepts video;
- `usb_c_pd_watts` means host-laptop power on that video connection;
- `usb_c_downstream_charge_watts` is peripheral charging and cannot replace laptop video/PD;
- U2724D (`MON-010`) has a data-only USB-C upstream port, while U2724DE (`MON-011`) supports video and 90 W host charging;
- `screen_inches` is the precise viewable diagonal, so 23.81 inches does not satisfy a strict 24.0-inch minimum;
- stock and delivery lead time are always unknown in this dataset.

See [data/README.md](data/README.md) for the complete SKU table, field definitions, provenance, and rebuild process.

### Rebuild and validate the data package

Normal application use does not require another download. To regenerate derived data and the catalogue database:

```bash
python scripts/build_data.py
python scripts/validate_data.py
```

Only these two files are intended for manual data maintenance:

- `data/curated_specs.json` — reviewed facts and evidence page numbers;
- `data/synthetic_business.json` — synthetic prices and business rules.

Re-extracting source PDFs requires the separately pinned data dependency:

```bash
.venv/bin/pip install -r scripts/requirements-data.txt
python scripts/extract_sources.py
```

## Tests and evidence boundaries

```bash
.venv/bin/pip install -r requirements-dev.txt
python scripts/build_data.py
python scripts/validate_data.py                            # 15 data/tool checks
.venv/bin/python -m unittest discover -s tests            # 38 catalogue/backend/failure-path/evaluation-gate tests
.venv/bin/python -m unittest discover -s dell_agent/tests # 63 Agent tests
```

The current suites report:

- 15 catalogue/CLI contract tests passing;
- 18 temporary-database backend tests passing (migration, snapshots, concurrency, confirmation, diff, PDF, fault injection and HTTP);
- 63 Agent tests passing, with 7 explicitly documented OfflineDriver heuristic skips;
- all three fixed demo scenarios passing in the offline path.

These numbers are not a model accuracy claim. The expected semantic labels for the existing 40 natural-language fixtures have passed independent review; the new sealed holdout still requires a non-author review. Holdout answers and validation reports must never be placed in the system prompt or runtime knowledge store.

## Optional Amazon Bedrock path

Install the separately pinned cloud dependency:

```bash
.venv/bin/pip install -r requirements-cloud.txt
```

Configure the application without putting AWS keys in source files or `.env`:

```bash
export AGENT_DRIVER=converse
export BEDROCK_MODEL_ID='<supported-bedrock-model-id>'
export AWS_REGION='<enabled-region>'
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Credentials must come from the standard AWS credential chain. The UI shows whether a result used Bedrock or the deterministic fallback. A configured model is not considered verified until `used_fallback=false` and the trace contains a real Converse tool-use cycle.

The live cloud path remains unfinished: the team still needs to run the three demo stories with its AWS account, complete native `ask_for`/candidate/citation assembly, and add a bounded retry for retryable failures.

## Fixed demo stories

1. **Clarify, quote, revise:** an ambiguous eight-monitor USB-C enquiry becomes an SGD 2,312 draft; changing to ten units creates an SGD 2,890 version and exposes the SGD 390 budget gap.
2. **Catch the data-only port:** a request for four U2724D monitors with one-cable video and 90 W charging is blocked with source evidence; U2724DE is suggested but never selected automatically.
3. **Enforce policy:** a 6% discount and next-day delivery request is blocked because the synthetic limit is 5% and delivery data is unavailable.

## Remaining critical path

1. Complete a real Bedrock Converse tool-use run and structured AgentResult assembly.
2. Run and preserve the first formal sealed-holdout evaluation, then separate fixes from the original result.
3. Measure five manual-versus-Agent cases, rehearse, record the 30-minute video, and submit.

See [docs/project-plan-zh.md](docs/project-plan-zh.md) for owners, acceptance criteria, evaluation thresholds, exception coverage, and the video plan.

## Repository map

```text
app/                    FastAPI, SQLite lifecycle, snapshot validation, diff/PDF, browser workbench
data/                   source, curated, generated, evaluation, and validation data
dell_agent/             typed catalogue, pricing, state machine, tools, drivers
docs/api-contract.md    frozen tool and HTTP contract
docs/project-plan-zh.md single authoritative project plan
scripts/                download, extraction, build, validation, and CLI entry points
tests/                  catalogue/CLI and quote-backend integration tests
agent.md                concise engineering handoff
```

## Source and licensing note

Specifications are derived from Dell manuals linked in `data/processed/sources.csv`. The original PDFs remain Dell copyrighted material; public download does not imply an open redistribution licence. Verify redistribution rights before publishing those files. All prices, rules, and enquiries are explicitly synthetic.
