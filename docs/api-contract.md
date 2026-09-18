# Quotation Agent API and tool contract

This document freezes the boundary between the language layer, deterministic business tools, HTTP API, and browser client.

## Authority

`dell_agent.agent.tools.dispatch(name, args)` is the only runtime implementation of product lookup and pricing. Scripts, the offline driver, Bedrock Converse, FastAPI, and tests must call this boundary instead of duplicating product filters or money calculations.

All monetary values are integer SGD cents. Product prices come from the catalogue. Callers cannot submit a unit price. Unknown facts stay `null`.

## Tool result convention

A successful tool returns its documented JSON value. A caller/business error returns:

```json
{"error":"invalid_quantity","message":"Quantity for SKU 'MON-007' must be an integer >= 1."}
```

Tools do not raise for ordinary invalid input. The frozen error codes are:

- `bad_argument`
- `unknown_tool`
- `invalid_quantity`
- `discount_limit_exceeded`
- `missing_price`
- `custom_price_forbidden`

An unknown SKU passed to `get_product` is not an exception: it returns `{"found":false,"sku":"..."}`. An unknown SKU passed to `calculate_quote` returns `missing_price`, because pricing cannot proceed.

## `search_products`

Input keys are conjunctive structured filters:

```json
{
  "query": "P2425HE",
  "usb_c_video": true,
  "min_pd_watts": 65,
  "min_screen_inches": 23.8,
  "max_screen_inches": 27,
  "resolution": "1920x1080",
  "min_refresh_hz": 100,
  "max_unit_price_cents": 35000
}
```

`query` is only a model/SKU/name/alias keyword. It is not a natural-language enquiry. Success returns a bare array of product summaries sorted by `unit_price_cents`; no match returns `[]` and never substitutes another model.

## `get_product`

Input:

```json
{"sku":"MON-007"}
```

Success returns `found`, the public specification fields, synthetic `unit_price_cents`, `evidence[]`, and `stock_quantity`/`delivery_lead_days` as `null`. Every evidence entry has `source_id`, `source_url`, `pdf_page`, `field`, `value`, `method`, and `note`.

## `calculate_quote`

Input:

```json
{
  "items":[{"sku":"MON-007","quantity":8,"discount_bps":0}],
  "budget_cents":250000
}
```

Success returns an unconfirmed draft:

```json
{
  "status":"draft",
  "is_confirmed":false,
  "currency":"SGD",
  "lines":[],
  "total_cents":231200,
  "within_budget":true,
  "over_budget_cents":0,
  "validity_days":7,
  "tax_note":"...",
  "disclaimer":"synthetic demo, not a tax invoice"
}
```

`within_budget` and `over_budget_cents` are omitted when no budget is supplied. Discounts are basis points in `[0, 500]`; values above the limit are rejected rather than clamped. Duplicate SKUs are valid separate input lines and are not silently merged.

## Agent result

Both drivers return:

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

Statuses are `ready_to_quote`, `needs_clarification`, `explain_limitation`, `answer_with_evidence`, `no_match`, `budget_conflict`, `rule_violation`, and `invalid_quantity`.

## HTTP convention

HTTP errors use:

```json
{"detail":{"error":"not_found","message":"Conversation not found."}}
```

The HTTP service persists ordered user turns, replays all turns through the selected driver, and stores every result. A quote is saved only through an explicit save endpoint; a `calculate_quote` result alone is not approval.

### Save precondition

Saving a quote must identify the exact displayed Agent result; it never means "save whatever is latest":

```json
POST /api/conversations/{id}/quotes
{"result_message_id":"<latest assistant message id>"}
```

The server rejects a stale ID with HTTP 409 / `stale_draft`. Repeating the same valid save is idempotent and returns the existing quote version.