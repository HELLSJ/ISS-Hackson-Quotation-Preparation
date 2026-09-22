"""Tests for the ``calculate_quote`` tool (task 7.2, Req 4).

Covers Requirements 4.1, 4.5, 4.7, and 4.10 with both concrete unit tests and
stdlib property tests (fixed seed, many iterations):

  * invalid quantity (0, negative, non-int) -> ``invalid_quantity`` (Req 4.7);
  * ``discount_bps`` above 500 -> ``discount_limit_exceeded``, never clamped
    (Req 4.5);
  * an item carrying a custom unit price -> ``custom_price_forbidden`` (Req 4.1);
  * an unknown SKU -> ``missing_price``;
  * duplicate SKUs are quoted as two separate lines;
  * budget evaluation (within and over) with independent ``Decimal`` checks
    (Req 4.8, 8.3);
  * every successful draft has ``is_confirmed == false`` and carries no
    side-effect fields (Req 4.10, Property 11).

Property coverage (design.md):
  * Property 5  - discount bound: accepted ``discount_bps`` in ``[0, 500]``;
    above 500 always rejected (never clamped).
  * Property 6  - quantity validity: accepted ``quantity`` is an int ``>= 1``;
    invalid rejected with ``invalid_quantity``.
  * Property 7  - no price fabrication: an item carrying a custom unit price is
    always rejected.
  * Property 11 - draft has no side effects: a successful draft has
    ``is_confirmed == false`` and no persistence/approval/etc. fields.

Runs on the Python standard library only::

    python -m unittest dell_agent.tests.test_calculate_quote
"""

from __future__ import annotations

import random
import unittest
from decimal import ROUND_HALF_UP, Decimal

from dell_agent.agent import tools
from dell_agent.data import catalog

# A SKU with a known catalogue price used across the concrete cases.
_MON_007 = "MON-007"
_MON_007_PRICE = 28900  # SGD 289.00 in cents (see spec Req 4.9)

# Fixed seed + iteration count keep the property tests deterministic yet broad.
_SEED = 20240517
_ITERATIONS = 400

# Keys that must never appear in a returned draft: a successful calculation is
# only a draft and performs no persistence, approval, reservation, export, or
# messaging (Req 4.10, 6.5, Property 11).
_SIDE_EFFECT_KEYS = frozenset(
    {
        "saved",
        "approved",
        "reserved",
        "pdf",
        "message",
        "sent",
        "version",
        "quote_id",
        "reservation",
        "invoice",
    }
)


def _priced_skus():
    """Return the sorted list of catalogue SKUs that carry a unit price."""
    return sorted(
        p.sku for p in catalog.all_products() if p.unit_price_cents is not None
    )


def _decimal_line_net(unit_price_cents: int, quantity: int, discount_bps: int) -> int:
    """Independently compute a line net in cents with Decimal half-up (Req 8.3).

    Mirrors the pricing rule: gross = unit_price * quantity; discount = half-up
    rounded application of ``discount_bps`` to gross; net = gross - discount.
    """
    gross = unit_price_cents * quantity
    discount = int(
        (Decimal(gross) * Decimal(discount_bps) / Decimal(10000)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    return gross - discount


def _assert_no_side_effects(test: unittest.TestCase, draft: dict) -> None:
    """Assert a draft is an unconfirmed draft with no side-effect fields."""
    test.assertNotIn("error", draft)
    test.assertEqual(draft.get("status"), "draft")
    test.assertIs(draft.get("is_confirmed"), False)
    leaked = _SIDE_EFFECT_KEYS & set(draft)
    test.assertEqual(leaked, set(), f"draft leaked side-effect field(s): {leaked}")


class InvalidQuantityTests(unittest.TestCase):
    """Quantity must be an integer >= 1 (Req 4.7)."""

    def test_zero_quantity_rejected(self) -> None:
        result = tools.calculate_quote(
            {"items": [{"sku": _MON_007, "quantity": 0}]}
        )
        self.assertEqual(result.get("error"), "invalid_quantity")

    def test_negative_quantity_rejected(self) -> None:
        result = tools.calculate_quote(
            {"items": [{"sku": _MON_007, "quantity": -3}]}
        )
        self.assertEqual(result.get("error"), "invalid_quantity")

    def test_non_int_quantity_rejected(self) -> None:
        for bad in (2.5, "4", None, True):
            with self.subTest(quantity=bad):
                result = tools.calculate_quote(
                    {"items": [{"sku": _MON_007, "quantity": bad}]}
                )
                self.assertEqual(result.get("error"), "invalid_quantity")


class DiscountLimitTests(unittest.TestCase):
    """discount_bps above 500 is rejected, never clamped (Req 4.5)."""

    def test_discount_above_limit_rejected(self) -> None:
        result = tools.calculate_quote(
            {"items": [{"sku": _MON_007, "quantity": 1, "discount_bps": 501}]}
        )
        self.assertEqual(result.get("error"), "discount_limit_exceeded")

    def test_discount_at_limit_accepted(self) -> None:
        result = tools.calculate_quote(
            {"items": [{"sku": _MON_007, "quantity": 1, "discount_bps": 500}]}
        )
        _assert_no_side_effects(self, result)


class CustomPriceTests(unittest.TestCase):
    """A custom unit price is always rejected (Req 4.1)."""

    def test_unit_price_rejected(self) -> None:
        result = tools.calculate_quote(
            {"items": [{"sku": _MON_007, "quantity": 1, "unit_price": 100}]}
        )
        self.assertEqual(result.get("error"), "custom_price_forbidden")

    def test_unit_price_cents_rejected(self) -> None:
        result = tools.calculate_quote(
            {"items": [{"sku": _MON_007, "quantity": 1, "unit_price_cents": 100}]}
        )
        self.assertEqual(result.get("error"), "custom_price_forbidden")


class MissingPriceTests(unittest.TestCase):
    """An unknown SKU has no catalogue price -> missing_price."""

    def test_unknown_sku_rejected(self) -> None:
        result = tools.calculate_quote(
            {"items": [{"sku": "MON-999", "quantity": 1}]}
        )
        self.assertEqual(result.get("error"), "missing_price")


class DuplicateLineTests(unittest.TestCase):
    """Duplicate SKUs are quoted as two separate lines."""

    def test_duplicate_sku_two_lines(self) -> None:
        result = tools.calculate_quote(
            {
                "items": [
                    {"sku": _MON_007, "quantity": 2},
                    {"sku": _MON_007, "quantity": 3},
                ]
            }
        )
        _assert_no_side_effects(self, result)
        lines = result["lines"]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["sku"], _MON_007)
        self.assertEqual(lines[1]["sku"], _MON_007)
        self.assertEqual(lines[0]["quantity"], 2)
        self.assertEqual(lines[1]["quantity"], 3)
        # Total independently verified with Decimal.
        expected = _decimal_line_net(_MON_007_PRICE, 2, 0) + _decimal_line_net(
            _MON_007_PRICE, 3, 0
        )
        self.assertEqual(result["total_cents"], expected)


class BudgetTests(unittest.TestCase):
    """Budget evaluation reports within/over amounts (Req 4.8, 4.9)."""

    def test_within_budget(self) -> None:
        # 8 x MON-007 @ 0 discount = 231200; budget 250000 -> within.
        result = tools.calculate_quote(
            {
                "items": [{"sku": _MON_007, "quantity": 8}],
                "budget_cents": 250000,
            }
        )
        _assert_no_side_effects(self, result)
        self.assertEqual(result["total_cents"], 231200)
        self.assertEqual(result["subtotal_cents"], 231200)
        self.assertEqual(result["shipping_fee_cents"], 0)
        self.assertEqual(result["budget_cents"], 250000)
        self.assertEqual(result["lines"][0]["line_id"], "line-mon-007-001")
        self.assertEqual(result["lines"][0]["model"], "P2425HE")
        self.assertEqual(result["pricing_context"]["dataset_version"], "2026-09-22.v2")
        self.assertEqual(result["pricing_context"]["price_version"], "demo-v2")
        self.assertEqual(result["pricing_context"]["rule_version"], "demo-v1")
        self.assertIs(result["within_budget"], True)
        self.assertEqual(result.get("over_budget_cents"), 0)

    def test_over_budget(self) -> None:
        # 10 x MON-007 @ 0 discount = 289000; budget 250000 -> 39000 over.
        result = tools.calculate_quote(
            {
                "items": [{"sku": _MON_007, "quantity": 10}],
                "budget_cents": 250000,
            }
        )
        _assert_no_side_effects(self, result)
        self.assertEqual(result["total_cents"], 289000)
        self.assertIs(result["within_budget"], False)
        self.assertEqual(result["over_budget_cents"], 39000)


class Property5DiscountBoundTests(unittest.TestCase):
    """Property 5: accepted discount in [0,500]; >500 always rejected.

    **Validates: Requirements 4.5**
    """

    def test_property_discount_bound(self) -> None:
        rng = random.Random(_SEED)
        skus = _priced_skus()
        for _ in range(_ITERATIONS):
            sku = rng.choice(skus)
            quantity = rng.randint(1, 20)
            if rng.random() < 0.5:
                # Accepted range: [0, 500].
                discount_bps = rng.randint(0, 500)
                result = tools.calculate_quote(
                    {
                        "items": [
                            {"sku": sku, "quantity": quantity,
                             "discount_bps": discount_bps}
                        ]
                    }
                )
                self.assertNotIn("error", result)
                # Discount is applied as given, never clamped.
                self.assertEqual(result["lines"][0]["discount_bps"], discount_bps)
            else:
                # Above the limit: always rejected, never clamped.
                discount_bps = rng.randint(501, 100000)
                result = tools.calculate_quote(
                    {
                        "items": [
                            {"sku": sku, "quantity": quantity,
                             "discount_bps": discount_bps}
                        ]
                    }
                )
                self.assertEqual(result.get("error"), "discount_limit_exceeded")


class Property6QuantityValidityTests(unittest.TestCase):
    """Property 6: accepted quantity is int >= 1; invalid -> invalid_quantity.

    **Validates: Requirements 4.7**
    """

    def test_property_quantity_validity(self) -> None:
        rng = random.Random(_SEED + 1)
        skus = _priced_skus()
        for _ in range(_ITERATIONS):
            sku = rng.choice(skus)
            kind = rng.randint(0, 2)
            if kind == 0:
                # Valid integer quantity >= 1.
                quantity = rng.randint(1, 1000)
                result = tools.calculate_quote(
                    {"items": [{"sku": sku, "quantity": quantity}]}
                )
                self.assertNotIn("error", result)
                self.assertEqual(result["lines"][0]["quantity"], quantity)
            elif kind == 1:
                # Non-positive integer.
                quantity = rng.randint(-1000, 0)
                result = tools.calculate_quote(
                    {"items": [{"sku": sku, "quantity": quantity}]}
                )
                self.assertEqual(result.get("error"), "invalid_quantity")
            else:
                # Non-integer value (float / string).
                quantity = rng.choice(
                    [rng.uniform(0.1, 50.0), str(rng.randint(1, 50))]
                )
                result = tools.calculate_quote(
                    {"items": [{"sku": sku, "quantity": quantity}]}
                )
                self.assertEqual(result.get("error"), "invalid_quantity")


class Property7NoPriceFabricationTests(unittest.TestCase):
    """Property 7: an item carrying a custom unit price is always rejected.

    **Validates: Requirements 4.1**
    """

    def test_property_no_price_fabrication(self) -> None:
        rng = random.Random(_SEED + 2)
        skus = _priced_skus()
        for _ in range(_ITERATIONS):
            sku = rng.choice(skus)
            quantity = rng.randint(1, 20)
            price_key = rng.choice(["unit_price", "unit_price_cents"])
            item = {"sku": sku, "quantity": quantity,
                    price_key: rng.randint(1, 1_000_000)}
            result = tools.calculate_quote({"items": [item]})
            self.assertEqual(result.get("error"), "custom_price_forbidden")


class Property11NoSideEffectsTests(unittest.TestCase):
    """Property 11: a successful draft is unconfirmed with no side effects.

    **Validates: Requirements 4.10**
    """

    def test_property_draft_no_side_effects(self) -> None:
        rng = random.Random(_SEED + 3)
        skus = _priced_skus()
        for _ in range(_ITERATIONS):
            item_count = rng.randint(1, 4)
            items = [
                {
                    "sku": rng.choice(skus),
                    "quantity": rng.randint(1, 20),
                    "discount_bps": rng.randint(0, 500),
                }
                for _ in range(item_count)
            ]
            args = {"items": items}
            if rng.random() < 0.5:
                args["budget_cents"] = rng.randint(1, 5_000_000)
            result = tools.calculate_quote(args)
            _assert_no_side_effects(self, result)


if __name__ == "__main__":
    unittest.main()
