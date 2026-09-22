# Quotation Agent API and tool contract

This document freezes the boundary between the language layer, deterministic tools, quote lifecycle, HTTP API, and browser client.

## Authority and invariants

`dell_agent.agent.tools.dispatch(name, args)` is the only product and pricing implementation. Models, browsers, persistence, diff, and PDF code must not duplicate or override it.

- Money is integer SGD cents.
- Unit prices come from the frozen catalogue; custom prices are rejected.
- Unknown facts stay `null`.
- A calculated `draft` is not saved or approved.
- A `saved_draft` is immutable but not approved.
- Only an immutable `confirmed` schema-v2 snapshot is exportable.
- Diff and PDF read stored snapshot JSON only; they never re-price or call an Agent.

## Tool errors

Ordinary caller/business errors are values, not exceptions:

```json
{"error":"invalid_quantity","message":"Quantity for SKU 'MON-007' must be an integer >= 1."}
```

Frozen codes: `bad_argument`, `unknown_tool`, `invalid_quantity`, `discount_limit_exceeded`, `missing_price`, and `custom_price_forbidden`.

## Deterministic tools

### `search_products`

Input is a conjunctive structured filter, never a natural-language sentence:

```json
{
  "query":"P2425HE",
  "usb_c_video":true,
  "min_pd_watts":65,
  "min_screen_inches":23.8,
  "max_screen_inches":27,
  "resolution":"1920x1080",
  "min_refresh_hz":100,
  "max_unit_price_cents":35000
}
```

Success is a bare product-summary array sorted by synthetic unit price. Exact model/SKU/alias matches take precedence over substring matches. No match returns `[]`; there is no silent substitution.

### `get_product`

```json
{"sku":"MON-007"}
```

Success returns public specifications, synthetic price, `evidence[]`, and `stock_quantity`/`delivery_lead_days` as `null`. Evidence contains `source_id`, `source_url`, `pdf_page`, `field`, `value`, `method`, and `note`. `source_url` is the official Dell URL with a `#page=N` fragment; the HTTP API does not host or redistribute Dell source PDFs. Unknown SKU returns `{"found":false,"sku":"..."}`.

### `calculate_quote`

```json
{
  "items":[{"sku":"MON-007","quantity":8,"discount_bps":0}],
  "budget_cents":250000
}
```

Success is an unconfirmed calculation:

```json
{
  "status":"draft",
  "is_confirmed":false,
  "currency":"SGD",
  "lines":[{
    "line_id":"line-mon-007-001",
    "sku":"MON-007",
    "model":"P2425HE",
    "name":"Dell P2425HE Monitor",
    "quantity":8,
    "unit_price_cents":28900,
    "discount_bps":0,
    "gross_cents":231200,
    "discount_cents":0,
    "net_cents":231200
  }],
  "subtotal_cents":231200,
  "shipping_fee_cents":0,
  "total_cents":231200,
  "budget_cents":250000,
  "within_budget":true,
  "over_budget_cents":0,
  "validity_days":7,
  "pricing_context":{
    "dataset_version":"2026-09-14.v1",
    "price_version":"demo-v1",
    "rule_version":"demo-v1",
    "price_effective_date":"2026-09-14",
    "rounding":"half_up_per_line_discount",
    "tax_mode":"not_modelled",
    "source_type":"synthetic",
    "inventory":"not_available",
    "delivery":"not_available"
  },
  "tax_note":"...",
  "disclaimer":"synthetic demo, not a tax invoice"
}
```

Budget fields are omitted when no budget is supplied. Discounts must be in `[0,500]` bps and are rejected rather than clamped. Duplicate SKUs remain separate lines with occurrence-stable IDs.

## Agent result

`OfflineDriver` and `GatewayDriver` return the same base shape:

```json
{
  "status":"needs_clarification",
  "ask_for":[],
  "candidates":[],
  "quote_draft":null,
  "citations":[],
  "notes":[],
  "trace":[]
}
```

Statuses: `ready_to_quote`, `needs_clarification`, `explain_limitation`, `answer_with_evidence`, `no_match`, `budget_conflict`, `rule_violation`, and `invalid_quantity`.

The application adds `configured_driver` and `used_fallback`. A Gateway result
counts as a real-model result only when `configured_driver="gateway"`,
`used_fallback=false`, and its trace contains a Gateway tool turn.

```http
GET /api/health
POST /api/conversations
Content-Type: application/json

{"driver":"gateway"}
```

`GET /api/health` exposes `configured_driver` and the boolean
`gateway_configured`; it never returns the Gateway URL or API key. Conversation
drivers are `offline` or `gateway`. Existing SQLite rows using the legacy cloud
driver name are migrated to `gateway` when schema version 3 is initialized.

## HTTP errors

```json
{"detail":{"error":"not_found","message":"Conversation not found."}}
```

Business errors use 404/409/422 as documented below. `snapshot_token` is an optimistic-concurrency token, not authentication; this prototype has no access-control layer.

## Quote lifecycle

### 1. Save the exact displayed draft

```http
POST /api/conversations/{conversation_id}/quotes
Content-Type: application/json

{
  "result_message_id":"<latest assistant message id>",
  "customer_display_name":"Example Customer"
}
```

The server validates all line arithmetic, discount limits, totals, budget outcome, dates, and pricing provenance before persistence. Server-owned metadata cannot be supplied by the browser.

A schema-v2 `payload` contains:

- immutable line facts and money;
- `schema_version`, `quote_id`, `quote_number`, and `quote_version`;
- `quote_date`, `validity_days`, and `valid_until`;
- customer display name (nullable until confirmation);
- complete `pricing_context` and synthetic terms;
- source result message ID.

Response additions:

```json
{
  "id":"<quote id>",
  "version":1,
  "status":"saved_draft",
  "is_confirmed":false,
  "snapshot_schema_version":2,
  "snapshot_token":"<sha256>",
  "confirmable":true,
  "exportable":false,
  "payload":{},
  "confirmation":null,
  "pdf_url":null
}
```

Rules:

- stale result ID → 409 `stale_draft`;
- no calculated draft → 409 `no_draft`;
- inconsistent snapshot → 409 `invalid_snapshot`;
- same source result with changed save metadata → 409 `save_conflict`;
- exact retry returns the same quote/version (idempotent).

### 2. Confirm one immutable saved version

```http
POST /api/quotes/{quote_id}/confirm
Content-Type: application/json

{
  "snapshot_token":"<64-character sha256>",
  "customer_display_name":"Example Customer",
  "confirmed_by":"Sales Admin"
}
```

Confirmation is append-only in `quote_confirmations`. It copies the saved payload and adds customer/confirmation metadata; it never updates the saved payload, calls `calculate_quote`, or reads current catalogue prices.

Rules:

- quote not found → 404 `not_found`;
- wrong token or older unconfirmed version → 409 `stale_confirmation`;
- legacy/incomplete schema → 409 `not_confirmable` with `missing_fields`;
- different retry after confirmation → 409 `already_confirmed`;
- exact retry returns the existing confirmation (idempotent).

Successful quote detail has `status="confirmed"`, `is_confirmed=true`, `exportable=true`, an immutable `confirmation.snapshot`, and `pdf_url`.

### Legacy schema-v1 policy

Startup performs an additive, restart-safe SQLite migration. Existing `payload_json` and fingerprints are never rewritten. Such rows return `status="legacy_saved_draft"`, remain readable/diffable, and have `confirmable=false`/`exportable=false`. Recalculate and save a schema-v2 version before confirmation.

## Structured version diff

```http
GET /api/quotes/{from_quote_id}/diff/{to_quote_id}
```

Both versions must belong to one conversation; otherwise 409 `cross_conversation`. The response includes:

```json
{
  "from":{"quote_id":"...","version":1,"status":"saved_draft"},
  "to":{"quote_id":"...","version":2,"status":"confirmed"},
  "comparable":true,
  "currency":"SGD",
  "identity_quality":"stable_line_id",
  "lines":{
    "added":[],
    "removed":[],
    "changed":[{
      "line_id":"line-mon-007-001",
      "before":{},
      "after":{},
      "changes":{"quantity":{"from":8,"to":10,"delta":2}},
      "net_delta_cents":57800
    }],
    "unchanged_count":0
  },
  "totals":{"total_cents":{"from":231200,"to":289000,"delta":57800}},
  "metadata_changes":{},
  "has_changes":true
}
```

Schema-v2 lines match by stable `line_id`; legacy lines use a documented SKU-occurrence fallback. Unlike currencies are not subtracted (`comparable=false`). Diff never consults current catalogue or pricing tools.

## Confirmed quote PDF

```http
GET /api/quotes/{quote_id}/pdf
```

- missing quote → 404 `not_found`;
- saved/legacy/unconfirmed quote → 409 `not_exportable`;
- rendering failure → 500 `pdf_generation_failed` without changing quote state.

Success returns `application/pdf` as an attachment named from the server-generated quote number. The PDF includes customer, quote/version dates, confirmer, lines, quantities, unit prices, discounts, totals, synthetic terms, unavailable stock/delivery notice, and dataset/price/rule versions. The renderer accepts only `confirmation.snapshot` and has no Agent, catalogue, or pricing dependency.

## Browser integration handoff for D

The backend HTTP path was exercised end to end with Story A in `tests/test_quote_backend.py::QuoteApiTests.test_story_a_version_handoff_over_http`. The UI can use this sequence:

| Step | Request | UI field or action |
|---|---|---|
| Refresh | `GET /api/conversations/{id}` | Read `latest_result_message_id`, `latest_result.quote_draft`, and `quote_versions`. Keep the displayed result ID with its draft. |
| Save | `POST /api/conversations/{id}/quotes` | Send that `result_message_id` and optional `customer_display_name`. Display returned `version`, `status`, `payload` and `confirmable`. Repeating the same request returns the same version. |
| Confirm | `POST /api/quotes/{id}/confirm` | Send the saved response's `snapshot_token`, `customer_display_name`, and `confirmed_by`. Enable only when `confirmable=true`. Refresh quote detail after a conflict. |
| Compare | `GET /api/quotes/{v1}/diff/{v2}` | Render the server's `lines`, `totals`, and `metadata_changes`; keep integer cents as the source of truth. |
| Download | `GET /api/quotes/{id}/pdf` | Offer the returned `pdf_url` only when `exportable=true`; the response is an attachment, not JSON. |

For Story A, saving 8 P2425HE units gives v1 `total_cents=231200`; changing the quantity to 10 and saving gives v2 `total_cents=289000`. The diff reports `total_cents.delta=57800` and quantity `delta=2`. After v2 is saved, confirming unconfirmed v1 returns 409 `stale_confirmation`; confirming v2 enables its `pdf_url`.

For UI recovery, a 409 `stale_draft` or `stale_confirmation` means refresh the conversation/quote and require a new user decision. `no_draft` and `not_confirmable` mean keep save/confirm disabled until there is a valid calculated/saved quote. `save_conflict` and `already_confirmed` mean show the existing version/confirmation rather than silently changing it. A database save failure returns 500 while preserving the displayed draft; retry the same save after recovery. A 500 `pdf_generation_failed` leaves the confirmed version exportable; retry its PDF URL. All quote money and version deltas come from the server.
