"""Structured comparison of immutable quote snapshots; never re-prices."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

_LINE_FIELDS = (
    "sku", "model", "name", "quantity", "unit_price_cents", "discount_bps",
    "gross_cents", "discount_cents", "net_cents",
)
_LINE_MONEY_FIELDS = {
    "unit_price_cents", "gross_cents", "discount_cents", "net_cents"
}
_MONEY_FIELDS = ("subtotal_cents", "shipping_fee_cents", "total_cents")
_METADATA_FIELDS = (
    "currency", "quote_date", "valid_until", "customer", "pricing_context", "terms"
)


def effective_snapshot(quote: dict[str, Any]) -> dict[str, Any]:
    confirmation = quote.get("confirmation")
    return confirmation["snapshot"] if confirmation else quote["payload"]


def _signature(line: dict[str, Any]) -> tuple:
    return tuple(line.get(field) for field in _LINE_FIELDS)


def _pair_cost(before: dict[str, Any], after: dict[str, Any]) -> tuple:
    """Prefer exact facts, then few changes, then small business deltas."""
    changed = sum(before.get(field) != after.get(field) for field in _LINE_FIELDS)
    money = abs(int(before.get("net_cents", 0)) - int(after.get("net_cents", 0)))
    quantity = abs(int(before.get("quantity", 0)) - int(after.get("quantity", 0)))
    discount = abs(int(before.get("discount_bps", 0)) - int(after.get("discount_bps", 0)))
    return changed, money, quantity, discount


def _match_lines(
    before_lines: list[dict[str, Any]], after_lines: list[dict[str, Any]]
) -> tuple[list[tuple[int, int]], list[int], list[int], str]:
    """Match duplicate/reordered lines without trusting positional occurrence IDs."""
    before_skus = Counter(str(line.get("sku")) for line in before_lines)
    after_skus = Counter(str(line.get("sku")) for line in after_lines)
    all_ids = [line.get("line_id") for line in before_lines + after_lines]
    stable_ids = (
        all(isinstance(value, str) and value for value in all_ids)
        and max(before_skus.values(), default=0) <= 1
        and max(after_skus.values(), default=0) <= 1
    )
    if stable_ids:
        after_by_id = {line["line_id"]: index for index, line in enumerate(after_lines)}
        pairs = [
            (index, after_by_id[line["line_id"]])
            for index, line in enumerate(before_lines)
            if line["line_id"] in after_by_id
        ]
        paired_before = {left for left, _ in pairs}
        paired_after = {right for _, right in pairs}
        return (
            pairs,
            [i for i in range(len(before_lines)) if i not in paired_before],
            [i for i in range(len(after_lines)) if i not in paired_after],
            "stable_line_id",
        )

    pairs: list[tuple[int, int]] = []
    used_before: set[int] = set()
    used_after: set[int] = set()
    by_sku_before: dict[str, list[int]] = defaultdict(list)
    by_sku_after: dict[str, list[int]] = defaultdict(list)
    for index, line in enumerate(before_lines):
        by_sku_before[str(line.get("sku"))].append(index)
    for index, line in enumerate(after_lines):
        by_sku_after[str(line.get("sku"))].append(index)

    for sku in sorted(set(by_sku_before) | set(by_sku_after)):
        left = by_sku_before.get(sku, [])
        right = by_sku_after.get(sku, [])
        # Cancel exact line signatures first, so duplicate insertion/reorder does
        # not turn unchanged lines into artificial edits.
        for left_index in left:
            match = next(
                (
                    right_index for right_index in right
                    if right_index not in used_after
                    and _signature(before_lines[left_index]) == _signature(after_lines[right_index])
                ),
                None,
            )
            if match is not None:
                pairs.append((left_index, match))
                used_before.add(left_index)
                used_after.add(match)
        # Greedily pair remaining same-SKU lines by deterministic business cost.
        candidates = sorted(
            (
                (_pair_cost(before_lines[left_index], after_lines[right_index]), left_index, right_index)
                for left_index in left if left_index not in used_before
                for right_index in right if right_index not in used_after
            ),
            key=lambda item: (item[0], item[1], item[2]),
        )
        for _, left_index, right_index in candidates:
            if left_index in used_before or right_index in used_after:
                continue
            pairs.append((left_index, right_index))
            used_before.add(left_index)
            used_after.add(right_index)

    pairs.sort(key=lambda pair: pair[0])
    return (
        pairs,
        [i for i in range(len(before_lines)) if i not in used_before],
        [i for i in range(len(after_lines)) if i not in used_after],
        "sku_value_matching",
    )


def _delta(before: Any, after: Any) -> Any:
    if (
        isinstance(before, int) and not isinstance(before, bool)
        and isinstance(after, int) and not isinstance(after, bool)
    ):
        return after - before
    return None


def compare_quotes(from_quote: dict[str, Any], to_quote: dict[str, Any]) -> dict[str, Any]:
    """Compare two stored versions without consulting tools or catalogue data."""
    if from_quote["conversation_id"] != to_quote["conversation_id"]:
        raise ValueError("cross_conversation")
    before_snapshot = effective_snapshot(from_quote)
    after_snapshot = effective_snapshot(to_quote)
    before_lines = list(before_snapshot.get("lines") or [])
    after_lines = list(after_snapshot.get("lines") or [])
    before_currency = before_snapshot.get("currency")
    after_currency = after_snapshot.get("currency")
    comparable = bool(before_currency and before_currency == after_currency)
    pairs, removed_indices, added_indices, identity_quality = _match_lines(
        before_lines, after_lines
    )

    added = []
    removed = []
    changed = []
    unchanged_count = 0
    for before_index, after_index in pairs:
        before = before_lines[before_index]
        after = after_lines[after_index]
        changes = {}
        for field in _LINE_FIELDS:
            if before.get(field) != after.get(field):
                change = {"from": before.get(field), "to": after.get(field)}
                delta = _delta(before.get(field), after.get(field))
                if delta is not None and (comparable or field not in _LINE_MONEY_FIELDS):
                    change["delta"] = delta
                changes[field] = change
        if changes:
            entry = {
                "line_id": before.get("line_id") or after.get("line_id") or f"legacy:{before_index}",
                "before": before,
                "after": after,
                "changes": changes,
            }
            if comparable:
                entry["net_delta_cents"] = int(after.get("net_cents", 0)) - int(before.get("net_cents", 0))
            changed.append(entry)
        else:
            unchanged_count += 1
    for index in removed_indices:
        before = before_lines[index]
        entry = {"line_id": before.get("line_id") or f"legacy:before:{index}", "before": before, "after": None}
        if comparable:
            entry["net_delta_cents"] = -int(before.get("net_cents", 0))
        removed.append(entry)
    for index in added_indices:
        after = after_lines[index]
        entry = {"line_id": after.get("line_id") or f"legacy:after:{index}", "before": None, "after": after}
        if comparable:
            entry["net_delta_cents"] = int(after.get("net_cents", 0))
        added.append(entry)

    totals = {}
    for field in _MONEY_FIELDS:
        before_value = before_snapshot.get(field)
        after_value = after_snapshot.get(field)
        if before_value is None and field == "subtotal_cents":
            before_value = sum(int(line.get("net_cents", 0)) for line in before_lines)
        if after_value is None and field == "subtotal_cents":
            after_value = sum(int(line.get("net_cents", 0)) for line in after_lines)
        if before_value is None and field == "shipping_fee_cents":
            before_value = int(before_snapshot.get("total_cents", 0)) - int(totals["subtotal_cents"]["from"])
        if after_value is None and field == "shipping_fee_cents":
            after_value = int(after_snapshot.get("total_cents", 0)) - int(totals["subtotal_cents"]["to"])
        totals[field] = {"from": before_value, "to": after_value}
        if comparable and isinstance(before_value, int) and isinstance(after_value, int):
            totals[field]["delta"] = after_value - before_value

    metadata_changes = {}
    for field in _METADATA_FIELDS:
        if before_snapshot.get(field) != after_snapshot.get(field):
            metadata_changes[field] = {"from": before_snapshot.get(field), "to": after_snapshot.get(field)}
    total_values_changed = any(value["from"] != value["to"] for value in totals.values())
    has_changes = bool(added or removed or changed or metadata_changes or total_values_changed)
    return {
        "from": {
            "quote_id": from_quote["id"], "version": from_quote["version"],
            "status": from_quote["status"],
            "snapshot_schema_version": from_quote["snapshot_schema_version"],
        },
        "to": {
            "quote_id": to_quote["id"], "version": to_quote["version"],
            "status": to_quote["status"],
            "snapshot_schema_version": to_quote["snapshot_schema_version"],
        },
        "comparable": comparable,
        "currency": before_currency if comparable else None,
        "identity_quality": identity_quality,
        "lines": {"added": added, "removed": removed, "changed": changed, "unchanged_count": unchanged_count},
        "totals": totals,
        "metadata_changes": metadata_changes,
        "has_changes": has_changes,
    }
