"""Build and validate immutable saved and confirmed quote snapshots."""
from __future__ import annotations

import copy
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

SNAPSHOT_SCHEMA_VERSION = 2


class SnapshotError(ValueError):
    def __init__(self, code: str, message: str, missing_fields: list[str] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.missing_fields = missing_fields or []


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _nonblank(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _parse_iso_date(value: Any, field: str) -> date:
    if not _nonblank(value):
        raise SnapshotError("invalid_snapshot", f"{field} must be an ISO date.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SnapshotError("invalid_snapshot", f"{field} must be an ISO date.") from exc


def _line_discount(gross_cents: int, discount_bps: int) -> int:
    raw = Decimal(gross_cents) * Decimal(discount_bps) / Decimal(10000)
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def validate_draft(draft: dict[str, Any]) -> None:
    """Reject any draft that cannot safely become a historical snapshot."""
    if not isinstance(draft, dict):
        raise SnapshotError("invalid_snapshot", "Quote draft must be an object.")
    if draft.get("status") != "draft" or draft.get("is_confirmed") is not False:
        raise SnapshotError("invalid_snapshot", "Only an unconfirmed calculation draft can be saved.")
    if not _nonblank(draft.get("currency")):
        raise SnapshotError("invalid_snapshot", "Quote currency is required.")

    context = draft.get("pricing_context")
    required_context = (
        "dataset_version", "price_version", "rule_version",
        "price_effective_date", "rounding", "tax_mode", "source_type",
        "inventory", "delivery",
    )
    if not isinstance(context, dict):
        raise SnapshotError("invalid_snapshot", "Pricing provenance is required.")
    missing_context = [key for key in required_context if not _nonblank(context.get(key))]
    if missing_context:
        raise SnapshotError(
            "invalid_snapshot",
            "Pricing provenance is incomplete.",
            [f"pricing_context.{key}" for key in missing_context],
        )

    lines = draft.get("lines")
    if not isinstance(lines, list) or not lines:
        raise SnapshotError("invalid_snapshot", "At least one quote line is required.")
    line_ids: set[str] = set()
    subtotal = 0
    for index, line in enumerate(lines):
        prefix = f"lines[{index}]"
        if not isinstance(line, dict):
            raise SnapshotError("invalid_snapshot", f"{prefix} must be an object.")
        for field in ("line_id", "sku", "model", "name"):
            if not _nonblank(line.get(field)):
                raise SnapshotError("invalid_snapshot", f"{prefix}.{field} is required.")
        line_id = line["line_id"]
        if line_id in line_ids:
            raise SnapshotError("invalid_snapshot", f"Duplicate line_id {line_id!r}.")
        line_ids.add(line_id)
        for field in (
            "quantity", "unit_price_cents", "discount_bps", "gross_cents",
            "discount_cents", "net_cents",
        ):
            if not _is_int(line.get(field)):
                raise SnapshotError("invalid_snapshot", f"{prefix}.{field} must be an integer.")
        if line["quantity"] < 1:
            raise SnapshotError("invalid_snapshot", f"{prefix}.quantity must be at least 1.")
        if line["unit_price_cents"] < 0:
            raise SnapshotError("invalid_snapshot", f"{prefix}.unit_price_cents cannot be negative.")
        if not 0 <= line["discount_bps"] <= 500:
            raise SnapshotError("invalid_snapshot", f"{prefix}.discount_bps must be between 0 and 500.")
        gross = line["unit_price_cents"] * line["quantity"]
        discount = _line_discount(gross, line["discount_bps"])
        if line["gross_cents"] != gross or line["discount_cents"] != discount:
            raise SnapshotError("invalid_snapshot", f"{prefix} arithmetic does not match the pricing rule.")
        if line["net_cents"] != gross - discount:
            raise SnapshotError("invalid_snapshot", f"{prefix}.net_cents is inconsistent.")
        subtotal += line["net_cents"]

    for field in ("subtotal_cents", "shipping_fee_cents", "total_cents", "validity_days"):
        if not _is_int(draft.get(field)):
            raise SnapshotError("invalid_snapshot", f"{field} must be an integer.")
    if draft["subtotal_cents"] != subtotal:
        raise SnapshotError("invalid_snapshot", "subtotal_cents does not equal the line total.")
    if draft["shipping_fee_cents"] < 0:
        raise SnapshotError("invalid_snapshot", "shipping_fee_cents cannot be negative.")
    if draft["total_cents"] != subtotal + draft["shipping_fee_cents"]:
        raise SnapshotError("invalid_snapshot", "total_cents is inconsistent.")
    if draft["validity_days"] < 1:
        raise SnapshotError("invalid_snapshot", "validity_days must be positive.")
    if not _nonblank(draft.get("tax_note")) or not _nonblank(draft.get("disclaimer")):
        raise SnapshotError("invalid_snapshot", "Tax note and synthetic disclaimer are required.")

    budget = draft.get("budget_cents")
    budget_fields = ("within_budget", "over_budget_cents")
    if budget is None:
        if any(field in draft for field in budget_fields):
            raise SnapshotError("invalid_snapshot", "Budget outcome requires budget_cents.")
    else:
        if not _is_int(budget) or budget < 0:
            raise SnapshotError("invalid_snapshot", "budget_cents must be a non-negative integer.")
        if draft.get("within_budget") is not (draft["total_cents"] <= budget):
            raise SnapshotError("invalid_snapshot", "within_budget is inconsistent.")
        expected_over = max(0, draft["total_cents"] - budget)
        if draft.get("over_budget_cents") != expected_over:
            raise SnapshotError("invalid_snapshot", "over_budget_cents is inconsistent.")


def build_saved_snapshot(
    draft: dict[str, Any],
    *,
    quote_id: str,
    quote_number: str,
    quote_version: int,
    source_result_message_id: str,
    created_at: str,
    customer_display_name: str | None,
) -> dict[str, Any]:
    validate_draft(draft)
    quote_date = datetime.fromisoformat(created_at).date()
    valid_until = quote_date + timedelta(days=draft["validity_days"])
    customer = customer_display_name.strip() if customer_display_name else None
    snapshot = copy.deepcopy(draft)
    snapshot.update(
        {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "status": "saved_draft",
            "is_confirmed": False,
            "quote_id": quote_id,
            "quote_number": quote_number,
            "quote_version": quote_version,
            "quote_date": quote_date.isoformat(),
            "valid_until": valid_until.isoformat(),
            "customer": {"display_name": customer},
            "source": {"result_message_id": source_result_message_id},
            "terms": {
                "tax_note": draft["tax_note"],
                "disclaimer": draft["disclaimer"],
                "inventory": draft["pricing_context"]["inventory"],
                "delivery": draft["pricing_context"]["delivery"],
            },
        }
    )
    validate_saved_snapshot(snapshot, require_customer=False)
    return snapshot


def validate_saved_snapshot(snapshot: dict[str, Any], *, require_customer: bool) -> None:
    if snapshot.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise SnapshotError(
            "not_confirmable",
            "Legacy or unsupported snapshot schema.",
            ["schema_version"],
        )
    validate_draft({**snapshot, "status": "draft", "is_confirmed": False})
    missing = []
    for field in ("quote_id", "quote_number", "quote_version", "quote_date", "valid_until"):
        value = snapshot.get(field)
        if field == "quote_version":
            if not _is_int(value) or value < 1:
                missing.append(field)
        elif not _nonblank(value):
            missing.append(field)
    source = snapshot.get("source")
    if not isinstance(source, dict) or not _nonblank(source.get("result_message_id")):
        missing.append("source.result_message_id")
    customer = snapshot.get("customer")
    if require_customer and (
        not isinstance(customer, dict) or not _nonblank(customer.get("display_name"))
    ):
        missing.append("customer.display_name")
    if missing:
        raise SnapshotError("not_confirmable", "Snapshot metadata is incomplete.", missing)
    quote_date = _parse_iso_date(snapshot["quote_date"], "quote_date")
    valid_until = _parse_iso_date(snapshot["valid_until"], "valid_until")
    if valid_until != quote_date + timedelta(days=snapshot["validity_days"]):
        raise SnapshotError("invalid_snapshot", "valid_until is inconsistent with validity_days.")


def build_confirmed_snapshot(
    saved: dict[str, Any],
    *,
    customer_display_name: str,
    confirmed_by: str,
    confirmed_at: str,
) -> dict[str, Any]:
    customer = customer_display_name.strip()
    confirmer = confirmed_by.strip()
    if not customer or not confirmer:
        raise SnapshotError(
            "not_confirmable",
            "Customer display name and confirmer are required.",
            [field for field, value in (("customer.display_name", customer), ("confirmed_by", confirmer)) if not value],
        )
    candidate = copy.deepcopy(saved)
    candidate["customer"] = {"display_name": customer}
    validate_saved_snapshot(candidate, require_customer=True)
    candidate["status"] = "confirmed"
    candidate["is_confirmed"] = True
    candidate["confirmation"] = {
        "confirmed_at": confirmed_at,
        "confirmed_by": confirmer,
    }
    return candidate
