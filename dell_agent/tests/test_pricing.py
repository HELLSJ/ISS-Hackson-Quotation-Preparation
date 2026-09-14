"""Offline pricing tests: anchors + property-based invariants (Req 4, 8).

Stdlib-only (``unittest`` + ``decimal`` + ``random``); no third-party deps and
no live model. Runnable via::

    python -m unittest dell_agent.tests.test_pricing

Two layers of verification:

1. **Anchor tests** assert the four canonical monetary anchors from the design
   doc (231200 / 289000+39000-over / 66310 / 101692). Each anchor is
   *cross-checked* against an independent ``Decimal`` recomputation performed in
   the test itself (Req 8.3): the expected value is never merely hardcoded, it
   is derived here with ``ROUND_HALF_UP`` as the oracle and compared against the
   hardcoded literal as a second guard.

2. **Property-based tests** (Req 4, design Properties 1-4, 10) drive many
   randomised inputs through :mod:`dell_agent.pricing` with a fixed seed for
   reproducibility, checking universal invariants against the same independent
   ``Decimal`` oracle.
"""

from __future__ import annotations

import random
import unittest
from decimal import Decimal, ROUND_HALF_UP

from dell_agent.data import catalog
from dell_agent.pricing import compute_line, compute_quote, line_discount_cents


# --------------------------------------------------------------------------- #
# Independent Decimal oracle (re-implemented in the test, not imported from the
# production module, so it acts as a genuine cross-check).
# --------------------------------------------------------------------------- #

def oracle_discount_cents(gross_cents: int, discount_bps: int) -> int:
    """Half-up rounded discount, recomputed independently with ``Decimal``.

    This deliberately mirrors the spec formula
    ``round_half_up(gross * bps / 10000)`` without reusing the production code,
    so a regression in :mod:`dell_agent.pricing` cannot hide behind a shared
    helper.
    """
    raw = Decimal(gross_cents) * Decimal(discount_bps) / Decimal(10000)
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def oracle_net_cents(unit_price_cents: int, quantity: int, discount_bps: int) -> int:
    """Independently recomputed line net: gross - half-up discount."""
    gross = unit_price_cents * quantity
    return gross - oracle_discount_cents(gross, discount_bps)


# SKUs whose unit prices are asserted by the anchor cases.
_MON_007 = 28900
_MON_009 = 34900
_MON_001 = 14900

# Randomised-property configuration.
_SEED = 20240517
_ITERATIONS = 2000
_QTY_RANGE = (1, 50)
_DISCOUNT_RANGE = (0, 500)


class AnchorTests(unittest.TestCase):
    """The four canonical monetary anchors, each Decimal cross-checked."""

    def setUp(self) -> None:
        # Confirm the catalogue supplies the prices the anchors depend on, so a
        # data drift surfaces as a clear failure here rather than a mysterious
        # mismatch below.
        self.assertEqual(catalog.get("MON-007").unit_price_cents, _MON_007)
        self.assertEqual(catalog.get("MON-009").unit_price_cents, _MON_009)
        self.assertEqual(catalog.get("MON-001").unit_price_cents, _MON_001)
        self.rules = catalog.rules()
        self.assertEqual(self.rules.shipping_fee_cents, 0)

    def _quote(self, sku, unit_price, qty, discount, budget=None):
        product = catalog.get(sku)
        line = compute_line(sku, product.name, unit_price, qty, discount)
        return compute_quote([line], self.rules, budget_cents=budget)

    def test_mon007_8x_zero_discount_231200(self):
        """8 x MON-007 @0 -> 231200 (Req 4.9)."""
        expected = oracle_net_cents(_MON_007, 8, 0)
        self.assertEqual(expected, 231200)  # oracle agrees with the literal
        draft = self._quote("MON-007", _MON_007, 8, 0)
        self.assertEqual(draft.total_cents, expected)
        self.assertEqual(draft.lines[0].net_cents, expected)

    def test_mon007_10x_zero_discount_289000_over_budget(self):
        """10 x MON-007 @0 -> 289000, 39000 over a 250000 budget (Req 4.8, 4.9)."""
        expected_total = oracle_net_cents(_MON_007, 10, 0)
        self.assertEqual(expected_total, 289000)
        budget = 250000
        expected_over = max(expected_total - budget, 0)
        self.assertEqual(expected_over, 39000)

        draft = self._quote("MON-007", _MON_007, 10, 0, budget=budget)
        self.assertEqual(draft.total_cents, expected_total)
        self.assertFalse(draft.within_budget)
        self.assertEqual(draft.over_budget_cents, expected_over)

    def test_mon007_8x_within_250000_budget(self):
        """8 x MON-007 @0 sits within a 250000 budget (Req 4.9)."""
        draft = self._quote("MON-007", _MON_007, 8, 0, budget=250000)
        self.assertTrue(draft.within_budget)
        self.assertEqual(draft.over_budget_cents, 0)

    def test_mon009_2x_500bps_66310(self):
        """2 x MON-009 @500 -> 66310 (Req 4.3, 8.3)."""
        expected = oracle_net_cents(_MON_009, 2, 500)
        self.assertEqual(expected, 66310)
        draft = self._quote("MON-009", _MON_009, 2, 500)
        self.assertEqual(draft.total_cents, expected)
        self.assertEqual(draft.lines[0].net_cents, expected)
        # Discount itself: round_half_up(69800 * 500 / 10000) = 3490.
        self.assertEqual(draft.lines[0].discount_cents, oracle_discount_cents(69800, 500))

    def test_mon001_7x_250bps_101692_half_up(self):
        """7 x MON-001 @250 -> 101692; exercises the half-up tie (Req 4.3, 8.3)."""
        expected = oracle_net_cents(_MON_001, 7, 250)
        self.assertEqual(expected, 101692)
        draft = self._quote("MON-001", _MON_001, 7, 250)
        self.assertEqual(draft.total_cents, expected)
        # gross = 104300; 104300 * 250 / 10000 = 2607.5 -> half-up -> 2608.
        self.assertEqual(draft.lines[0].discount_cents, 2608)
        self.assertEqual(oracle_discount_cents(104300, 250), 2608)


class PropertyTests(unittest.TestCase):
    """Randomised property-based invariants (design Properties 1-4, 10).

    Uses ``random`` with a fixed seed and many iterations (stdlib only). Each
    iteration draws random catalogue SKUs, quantities (1..50), and discount_bps
    (0..500), then checks the invariants against the independent Decimal oracle.
    """

    def setUp(self) -> None:
        self.rules = catalog.rules()
        self.products = catalog.all_products()
        self.assertTrue(self.products)
        self.assertEqual(self.rules.shipping_fee_cents, 0)

    def _random_line(self, rng):
        product = rng.choice(self.products)
        qty = rng.randint(*_QTY_RANGE)
        discount = rng.randint(*_DISCOUNT_RANGE)
        line = compute_line(
            product.sku, product.name, product.unit_price_cents, qty, discount
        )
        return product, qty, discount, line

    def test_property1_non_negative_money(self):
        """Property 1: gross>=0, 0<=discount<=gross, net>=0 (Req 4.3)."""
        rng = random.Random(_SEED)
        for _ in range(_ITERATIONS):
            _, _, _, line = self._random_line(rng)
            self.assertGreaterEqual(line.gross_cents, 0)
            self.assertGreaterEqual(line.discount_cents, 0)
            self.assertLessEqual(line.discount_cents, line.gross_cents)
            self.assertGreaterEqual(line.net_cents, 0)
            self.assertEqual(line.net_cents, line.gross_cents - line.discount_cents)

    def test_property2_integer_cents(self):
        """Property 2: every monetary value is a plain int, never float (Req 4.2)."""
        rng = random.Random(_SEED + 1)
        for _ in range(_ITERATIONS):
            _, _, _, line = self._random_line(rng)
            for value in (
                line.unit_price_cents,
                line.gross_cents,
                line.discount_cents,
                line.net_cents,
            ):
                self.assertIsInstance(value, int)
                self.assertNotIsInstance(value, bool)
            draft = compute_quote([line], self.rules, budget_cents=None)
            self.assertIsInstance(draft.total_cents, int)
            self.assertNotIsInstance(draft.total_cents, bool)

    def test_property3_total_is_sum_of_nets_plus_shipping(self):
        """Property 3: total == sum(net) + shipping_fee_cents (0) (Req 4.4)."""
        rng = random.Random(_SEED + 2)
        for _ in range(_ITERATIONS):
            line_count = rng.randint(1, 5)
            lines = [self._random_line(rng)[3] for _ in range(line_count)]
            draft = compute_quote(lines, self.rules, budget_cents=None)
            expected_total = sum(l.net_cents for l in lines) + self.rules.shipping_fee_cents
            self.assertEqual(draft.total_cents, expected_total)

    def test_property4_half_up_rounding_matches_oracle(self):
        """Property 4: discount == independent Decimal half-up recomputation (Req 4.3, 8.3)."""
        rng = random.Random(_SEED + 3)
        for _ in range(_ITERATIONS):
            product, qty, discount, line = self._random_line(rng)
            expected_disc = oracle_discount_cents(line.gross_cents, discount)
            self.assertEqual(line.discount_cents, expected_disc)
            self.assertEqual(
                line.discount_cents, line_discount_cents(line.gross_cents, discount)
            )
            self.assertEqual(
                line.net_cents,
                oracle_net_cents(product.unit_price_cents, qty, discount),
            )

    def test_property10_budget_consistency(self):
        """Property 10: within_budget == (total<=budget); over == max(total-budget,0) (Req 4.8)."""
        rng = random.Random(_SEED + 4)
        for _ in range(_ITERATIONS):
            line_count = rng.randint(1, 5)
            lines = [self._random_line(rng)[3] for _ in range(line_count)]
            total = sum(l.net_cents for l in lines) + self.rules.shipping_fee_cents
            # Draw a budget spanning below, at, and above the total.
            budget = rng.randint(0, total + 100000)
            draft = compute_quote(lines, self.rules, budget_cents=budget)
            self.assertEqual(draft.within_budget, total <= budget)
            self.assertEqual(draft.over_budget_cents, max(total - budget, 0))

    def test_property10_no_budget_leaves_fields_none(self):
        """When budget omitted, within_budget/over_budget_cents are None (Req 4.8)."""
        rng = random.Random(_SEED + 5)
        for _ in range(200):
            _, _, _, line = self._random_line(rng)
            draft = compute_quote([line], self.rules, budget_cents=None)
            self.assertIsNone(draft.within_budget)
            self.assertIsNone(draft.over_budget_cents)


if __name__ == "__main__":
    unittest.main()
