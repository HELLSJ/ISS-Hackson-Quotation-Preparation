"""The three frozen tools plus the dispatcher.

Each tool takes a plain dict of JSON arguments and returns a JSON-serialisable
dict (or list of dicts). The tools own all facts; the model never invents
prices, quantities, or substitutions.

Implemented so far:
  * ``search_products`` (task 5.1) -- structured, deterministic filtering.

To be appended later (do not implement here):
  * ``get_product`` (task 6.1)
  * ``calculate_quote`` + ``dispatch`` (task 7.1)

Uses only the Python standard library.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from dell_agent.data import catalog
from dell_agent.models import Evidence, Product

# --------------------------------------------------------------------------- #
# Error-code helpers
# --------------------------------------------------------------------------- #
#
# Tools never raise for caller/business-rule violations; they return a structured
# error dict so the agent loop can relay a clear message and a tool-calling model
# cannot mistake a failure for success. Error codes are shared across all tools
# (see design.md "Error Handling"): bad_argument, unknown_sku, invalid_quantity,
# discount_limit_exceeded, missing_price, custom_price_forbidden, unknown_tool.


def _error(code: str, message: str) -> Dict[str, Any]:
    """Build a structured tool error result."""
    return {"error": code, "message": message}


# --------------------------------------------------------------------------- #
# Product serialisation (JSON-safe summaries)
# --------------------------------------------------------------------------- #

def _product_summary(product: Product) -> Dict[str, Any]:
    """Return a JSON-serialisable summary of a product (Req 2 result shape).

    Emits plain dicts (never dataclass instances) with the public, filterable
    facts a caller needs to choose a candidate. Unknown facts (e.g.
    ``max_refresh_hz``) are preserved as ``None`` and never coerced to 0/false.
    """
    return {
        "sku": product.sku,
        "model": product.model,
        "name": product.name,
        "brand": product.brand,
        "category": product.category,
        "unit": product.unit,
        "screen_inches": product.screen_inches,
        "resolution": product.resolution,
        "max_refresh_hz": product.max_refresh_hz,
        "usb_c_video": product.usb_c_video,
        "usb_c_pd_watts": product.usb_c_pd_watts,
        "usb_c_downstream_charge_watts": product.usb_c_downstream_charge_watts,
        "video_inputs": list(product.video_inputs),
        "aliases": list(product.aliases),
        "unit_price_cents": product.unit_price_cents,
    }


# --------------------------------------------------------------------------- #
# search_products (task 5.1, Req 2)
# --------------------------------------------------------------------------- #

# Tool-schema allow-list. Any other key is rejected with bad_argument
# (Req 2.1). Keeps tool selection deterministic and prevents a model from
# smuggling a free-text sentence or an unsupported filter.
_SEARCH_ALLOWED_KEYS = frozenset(
    {
        "query",
        "usb_c_video",
        "min_pd_watts",
        "min_screen_inches",
        "max_screen_inches",
        "resolution",
        "min_refresh_hz",
        "max_unit_price_cents",
    }
)


def _exact_query_skus(query: str) -> set:
    """Resolve an exact model/SKU/alias before allowing substring search.

    This prevents an exact request for U2724D or P2425 from silently expanding
    to U2724DE/P2425HE variants that may have materially different ports.
    """
    needle = query.strip().lower()
    if not needle:
        return set()
    exact = set()
    for product in catalog.all_products():
        values = [product.model, product.sku, product.name, *product.aliases]
        if needle in {(value or "").strip().lower() for value in values}:
            exact.add(product.sku)
    return exact


def _query_matches(product: Product, query: str) -> bool:
    """Case-insensitive substring match of ``query`` against keyword fields.

    The query is treated strictly as a keyword against model / sku / name /
    aliases -- never parsed as a natural-language sentence (Req 2.2).
    """
    needle = query.strip().lower()
    if not needle:
        return True
    haystacks: List[str] = [product.model, product.sku, product.name]
    haystacks.extend(product.aliases)
    return any(needle in (h or "").lower() for h in haystacks)


def search_products(args: Optional[Dict[str, Any]] = None) -> Any:
    """Filter the catalogue with explicit structured constraints (Req 2).

    Accepts only the allow-listed schema keys (Req 2.1); any unknown key yields
    a ``bad_argument`` error. Filters are applied conjunctively (Req 2.4); a
    product whose referenced field is ``None`` fails that filter (Req 2.3).
    Results are returned as JSON-serialisable summaries sorted by
    ``unit_price_cents`` ascending (Req 2.5); no match yields ``[]`` with no
    substitution (Req 2.6).

    Args:
        args: A dict of filter arguments restricted to the tool schema keys.

    Returns:
        A list of product-summary dicts, or a ``{"error": ...}`` dict on a
        bad argument.
    """
    args = args or {}

    # Reject unknown keys rather than silently ignoring them (Req 2.1).
    unknown = set(args) - _SEARCH_ALLOWED_KEYS
    if unknown:
        return _error(
            "bad_argument",
            "Unknown search parameter(s): "
            + ", ".join(sorted(unknown))
            + ". Allowed keys: "
            + ", ".join(sorted(_SEARCH_ALLOWED_KEYS))
            + ".",
        )

    query = args.get("query")
    usb_c_video = args.get("usb_c_video")
    min_pd_watts = args.get("min_pd_watts")
    min_screen_inches = args.get("min_screen_inches")
    max_screen_inches = args.get("max_screen_inches")
    resolution = args.get("resolution")
    min_refresh_hz = args.get("min_refresh_hz")
    max_unit_price_cents = args.get("max_unit_price_cents")

    if query is not None and not isinstance(query, str):
        return _error("bad_argument", "query must be text.")
    if usb_c_video is not None and not isinstance(usb_c_video, bool):
        return _error("bad_argument", "usb_c_video must be boolean.")
    for key, value in (
        ("min_pd_watts", min_pd_watts),
        ("min_refresh_hz", min_refresh_hz),
        ("max_unit_price_cents", max_unit_price_cents),
    ):
        if value is not None and (not _is_int(value) or value < 0):
            return _error("bad_argument", f"{key} must be a non-negative integer.")
    for key, value in (
        ("min_screen_inches", min_screen_inches),
        ("max_screen_inches", max_screen_inches),
    ):
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            return _error("bad_argument", f"{key} must be a positive number.")
    if resolution is not None and not isinstance(resolution, str):
        return _error("bad_argument", "resolution must be text such as 2560x1440.")

    exact_skus = _exact_query_skus(query) if query else set()
    matches: List[Product] = []
    for product in catalog.all_products():
        # Exact model/SKU/alias selection wins over substring matching. This is
        # a safety property: U2724D must not silently become U2724DE.
        if exact_skus:
            if product.sku not in exact_skus:
                continue
        elif query is not None and not _query_matches(product, query):
            continue

        # usb_c_video: only products whose upstream USB-C carries video
        # (excludes data-only USB-C such as U2724D) (Req 2.7). A None field
        # fails the filter (Req 2.3).
        if usb_c_video is not None:
            if product.usb_c_video is None or product.usb_c_video != usb_c_video:
                continue

        # min_pd_watts: upstream host-charging power, NOT downstream (Req 2.8).
        if min_pd_watts is not None:
            if product.usb_c_pd_watts is None or product.usb_c_pd_watts < min_pd_watts:
                continue

        # Screen size range against the precise viewable diagonal (Req 2.3).
        if min_screen_inches is not None:
            if product.screen_inches is None or product.screen_inches < min_screen_inches:
                continue
        if max_screen_inches is not None:
            if product.screen_inches is None or product.screen_inches > max_screen_inches:
                continue

        # resolution: exact match.
        if resolution is not None:
            if product.resolution is None or product.resolution != resolution:
                continue

        # min_refresh_hz against max_refresh_hz; None (unknown) fails (Req 2.3).
        if min_refresh_hz is not None:
            if product.max_refresh_hz is None or product.max_refresh_hz < min_refresh_hz:
                continue

        # max_unit_price_cents: price ceiling.
        if max_unit_price_cents is not None:
            if (
                product.unit_price_cents is None
                or product.unit_price_cents > max_unit_price_cents
            ):
                continue

        matches.append(product)

    # Sort by synthetic unit price ascending (Req 2.5).
    matches.sort(key=lambda p: p.unit_price_cents)

    # JSON-serialisable summaries; empty list on no match (Req 2.6).
    return [_product_summary(p) for p in matches]


# --------------------------------------------------------------------------- #
# get_product (task 6.1, Req 3)
# --------------------------------------------------------------------------- #

def _evidence_entry(ev: Evidence) -> Dict[str, Any]:
    """Return a JSON-serialisable evidence citation (Req 3.2, 3.3).

    Every entry carries the source identifier, source URL, and PDF page
    number(s) (Req 3.2). ``method`` names the derivation so a standardised
    derivation is distinguishable from a direct spec (Req 3.3). ``field`` /
    ``value`` / ``note`` are included for traceability.
    """
    return {
        "sku": ev.sku,
        "field": ev.field,
        "value": ev.value,
        "source_id": ev.source_id,
        "source_url": ev.source_url,
        "pdf_page": ev.pdf_page,
        "method": ev.method,
        "note": ev.note,
    }


_GET_PRODUCT_ALLOWED_KEYS = frozenset({"sku"})


def get_product(args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Retrieve one SKU with its public specs, price, and field evidence (Req 3).

    On a valid ``sku`` the tool returns the product's public specifications, its
    synthetic price in cents, and field-level evidence entries carrying the
    source id/url, PDF page number(s), and derivation method (Req 3.1-3.3).
    Stock and delivery lead time are never surfaced as concrete values; they are
    reported as ``null`` alongside an availability note (Req 3.5). An unknown
    ``sku`` yields a not-found result without fabricating a product (Req 3.4).

    Args:
        args: A dict expected to contain the ``sku`` key.

    Returns:
        A JSON-serialisable dict. For a known SKU: ``{"found": True, ...specs...,
        "unit_price_cents": ..., "evidence": [...], "stock_quantity": None,
        "delivery_lead_days": None, "availability_note": "not available"}``. For
        an unknown SKU: ``{"found": False, "sku": sku}``.
    """
    args = args or {}
    unknown = set(args) - _GET_PRODUCT_ALLOWED_KEYS
    if unknown:
        return _error(
            "bad_argument",
            "Unknown get_product parameter(s): " + ", ".join(sorted(unknown)) + ".",
        )
    sku = args.get("sku")

    if not isinstance(sku, str) or not sku.strip():
        return _error("bad_argument", "sku must be non-blank text.")

    sku = sku.strip()
    product = catalog.get(sku)
    if product is None:
        # Not found: do not fabricate a product (Req 3.4).
        return {"found": False, "sku": sku}

    # Public specifications + synthetic price (Req 3.1). Reuse the shared summary
    # so the fact set stays consistent with search_products; drop the summary's
    # own sku so the assembled dict keeps a single ordered "found"/"sku" pair.
    result: Dict[str, Any] = {"found": True}
    summary = _product_summary(product)
    result.update(summary)

    # Field-level evidence with source id/url, PDF page, and method (Req 3.2, 3.3).
    result["evidence"] = [_evidence_entry(ev) for ev in product.evidence]

    # Never surface stock/delivery as concrete values; report unavailable (Req 3.5).
    result["stock_quantity"] = None
    result["delivery_lead_days"] = None
    result["availability_note"] = "not available"

    return result

# --------------------------------------------------------------------------- #
# calculate_quote (task 7.1, Req 4)
# --------------------------------------------------------------------------- #

from dell_agent import pricing
from dell_agent.models import QuoteDraft, QuoteLine

# Item keys that would let a caller smuggle in a custom price. The catalogue is
# the only source of unit prices (Req 4.1, Property 7); any item carrying one of
# these keys is rejected with custom_price_forbidden.
_CUSTOM_PRICE_KEYS = frozenset({"unit_price", "unit_price_cents"})
_QUOTE_ALLOWED_KEYS = frozenset({"items", "budget_cents"})
_QUOTE_ITEM_ALLOWED_KEYS = frozenset({"sku", "quantity", "discount_bps"})


def _quote_line_dict(line: QuoteLine) -> Dict[str, Any]:
    """Serialise a :class:`QuoteLine` to a JSON-serialisable dict (Req 4.10)."""
    return {
        "sku": line.sku,
        "name": line.name,
        "quantity": line.quantity,
        "unit_price_cents": line.unit_price_cents,
        "discount_bps": line.discount_bps,
        "gross_cents": line.gross_cents,
        "discount_cents": line.discount_cents,
        "net_cents": line.net_cents,
    }


def _quote_draft_dict(
    draft: QuoteDraft, budget_cents: Optional[int]
) -> Dict[str, Any]:
    """Serialise a :class:`QuoteDraft` to a JSON-serialisable dict (Req 4.10, 5.8).

    Emits only the quote-facing fields: currency, lines, total, budget outcome
    (only when a budget was supplied), validity, tax note, draft status, and the
    synthetic disclaimer. Never exposes save/approve/reserve/PDF/send fields
    (Req 6.5, Property 11).
    """
    result: Dict[str, Any] = {
        "status": draft.status,
        "is_confirmed": draft.is_confirmed,
        "currency": draft.currency,
        "lines": [_quote_line_dict(line) for line in draft.lines],
        "subtotal_cents": sum(line.net_cents for line in draft.lines),
        "shipping_fee_cents": catalog.rules().shipping_fee_cents,
        "total_cents": draft.total_cents,
    }
    # Budget outcome is present only when the caller supplied a budget (Req 4.8).
    if budget_cents is not None:
        result["budget_cents"] = budget_cents
        result["within_budget"] = draft.within_budget
        result["over_budget_cents"] = draft.over_budget_cents
    result["validity_days"] = draft.validity_days
    result["pricing_context"] = catalog.pricing_context()
    result["tax_note"] = draft.tax_note
    result["disclaimer"] = draft.disclaimer
    return result


def _is_int(value: Any) -> bool:
    """True only for genuine integers (``bool`` excluded, ``float`` excluded)."""
    return isinstance(value, int) and not isinstance(value, bool)


def calculate_quote(args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Compute a draft quote from catalogue prices only (Req 4).

    Accepts ``{"items": [{"sku", "quantity", "discount_bps?"}], "budget_cents?"}``.
    Unit prices come solely from the catalogue; an item carrying a custom
    ``unit_price``/``unit_price_cents`` is rejected (Req 4.1, Property 7). Each
    item requires an integer ``quantity >= 1`` (Req 4.7, Property 6) and a
    ``discount_bps`` in ``[0, 500]`` — anything above 500 is rejected, never
    clamped (Req 4.5, Property 5). An unknown SKU or a catalogue entry without a
    price is rejected with ``missing_price``. Duplicate SKUs are kept as separate
    lines; the tool quotes exactly what it is given. The returned draft has
    ``is_confirmed == false`` and performs no persistence (Req 4.10, Property 11).

    Args:
        args: A dict with an ``items`` list and an optional ``budget_cents``.

    Returns:
        A JSON-serialisable quote-draft dict, or a ``{"error": ...}`` dict on the
        first offending item / argument.
    """
    args = args or {}

    unknown_args = set(args) - _QUOTE_ALLOWED_KEYS
    if unknown_args:
        return _error(
            "bad_argument",
            "Unknown calculate_quote parameter(s): "
            + ", ".join(sorted(unknown_args))
            + ".",
        )

    items = args.get("items")
    if not isinstance(items, list) or not items:
        return _error(
            "bad_argument",
            "calculate_quote requires a non-empty 'items' list.",
        )

    budget_cents = args.get("budget_cents")
    budget_given = budget_cents is not None
    if budget_given and (not _is_int(budget_cents) or budget_cents < 0):
        return _error(
            "bad_argument",
            "budget_cents must be a non-negative integer number of cents.",
        )

    lines: List[QuoteLine] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            return _error(
                "bad_argument",
                f"Item at index {index} must be an object.",
            )

        unknown_item_keys = set(item) - _QUOTE_ITEM_ALLOWED_KEYS
        if unknown_item_keys:
            offending_price_keys = unknown_item_keys & _CUSTOM_PRICE_KEYS
            if offending_price_keys:
                return _error(
                    "custom_price_forbidden",
                    "Custom unit prices are not allowed; prices come from the "
                    "catalogue only. Offending key(s): "
                    + ", ".join(sorted(offending_price_keys))
                    + ".",
                )
            return _error(
                "bad_argument",
                f"Unknown key(s) for item at index {index}: "
                + ", ".join(sorted(unknown_item_keys))
                + ".",
            )

        # Reject any attempt to supply a custom unit price (Req 4.1, Property 7).
        offending = _CUSTOM_PRICE_KEYS & set(item)
        if offending:
            return _error(
                "custom_price_forbidden",
                "Custom unit prices are not allowed; prices come from the "
                "catalogue only. Offending key(s): "
                + ", ".join(sorted(offending))
                + ".",
            )

        sku = item.get("sku")
        if not isinstance(sku, str) or not sku.strip():
            return _error(
                "bad_argument",
                f"Item at index {index} requires a non-blank text 'sku'.",
            )
        sku = sku.strip()

        # Integer quantity >= 1; reject non-int, <= 0, or missing (Req 4.7).
        quantity = item.get("quantity")
        if not _is_int(quantity) or quantity < 1:
            return _error(
                "invalid_quantity",
                f"Quantity for SKU '{sku}' must be an integer >= 1.",
            )

        # discount_bps defaults to 0; must be within [0, 500] (Req 4.5).
        discount_bps = item.get("discount_bps", 0)
        if not _is_int(discount_bps):
            return _error(
                "bad_argument",
                f"discount_bps for SKU '{sku}' must be an integer.",
            )
        if discount_bps < 0:
            return _error(
                "discount_limit_exceeded",
                f"discount_bps for SKU '{sku}' must not be negative.",
            )
        if discount_bps > 500:
            return _error(
                "discount_limit_exceeded",
                f"discount_bps {discount_bps} for SKU '{sku}' exceeds the "
                "500 bps limit.",
            )

        # Unknown SKU or a catalogue entry without a price -> missing_price.
        product = catalog.get(sku)
        if product is None or product.unit_price_cents is None:
            return _error(
                "missing_price",
                f"No catalogue price available for SKU '{sku}'.",
            )

        lines.append(
            pricing.compute_line(
                sku=sku,
                name=product.name,
                unit_price_cents=product.unit_price_cents,
                quantity=quantity,
                discount_bps=discount_bps,
            )
        )

    draft = pricing.compute_quote(lines, catalog.rules(), budget_cents)
    result = _quote_draft_dict(draft, budget_cents)
    occurrences: Dict[str, int] = {}
    for line, item in zip(result["lines"], items):
        sku = str(item["sku"])
        occurrences[sku] = occurrences.get(sku, 0) + 1
        product = catalog.get(sku)
        line["line_id"] = f"line-{sku.lower()}-{occurrences[sku]:03d}"
        line["model"] = product.model if product else sku
    return result


# --------------------------------------------------------------------------- #
# Dispatcher (task 7.1, Req 7.2)
# --------------------------------------------------------------------------- #

# Frozen tool registry. Both Agent drivers and tests route through this single
# entry point; an unrecognised name is rejected rather than silently ignored.
_TOOLS = {
    "search_products": search_products,
    "get_product": get_product,
    "calculate_quote": calculate_quote,
}


def dispatch(name: str, args: Optional[Dict[str, Any]] = None) -> Any:
    """Route a named tool call to its implementation (Req 7.2).

    Args:
        name: One of ``search_products`` / ``get_product`` / ``calculate_quote``.
        args: The plain-dict JSON arguments for the tool.

    Returns:
        The tool's JSON-serialisable result, or ``{"error": "unknown_tool", ...}``
        when ``name`` is not a registered tool.
    """
    if args is not None and not isinstance(args, dict):
        return _error("bad_argument", "Tool arguments must be a JSON object.")
    tool = _TOOLS.get(name)
    if tool is None:
        return _error(
            "unknown_tool",
            f"Unknown tool '{name}'. Available tools: "
            + ", ".join(sorted(_TOOLS))
            + ".",
        )
    return tool(args)
