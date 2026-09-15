"""Tests for the ``get_product`` tool (task 6.2).

Covers Requirements 3.2, 3.4, and 3.5:
  * a known SKU returns its public facts, synthetic price, and field-level
    evidence, and every evidence entry carries ``source_id`` / ``source_url`` /
    ``method`` with at least one entry exposing an integer ``pdf_page``
    (Req 3.2);
  * an unknown SKU returns a not-found result and fabricates nothing (Req 3.4);
  * stock and delivery lead time are never surfaced as concrete values -- they
    are reported as ``None`` with an availability note (Req 3.5).

Runs on the Python standard library only::

    python -m unittest dell_agent.tests.test_get_product
    python -m dell_agent.tests.test_get_product
"""

from __future__ import annotations

import unittest

from dell_agent.agent.tools import get_product


class GetKnownProductTests(unittest.TestCase):
    """A valid SKU returns cited facts and a synthetic price (Req 3.1-3.3)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.result = get_product({"sku": "MON-001"})

    def test_found_and_known_fields(self) -> None:
        """MON-001 resolves with its expected public facts (Req 3.1)."""
        result = self.result
        self.assertTrue(result["found"])
        self.assertEqual(result["sku"], "MON-001")
        # Model/name are present and non-empty public identifiers.
        self.assertEqual(result["model"], "S2425H")
        self.assertTrue(result["name"])
        # Synthetic unit price in integer cents (SGD 149.00).
        self.assertEqual(result["unit_price_cents"], 14900)
        self.assertIsInstance(result["unit_price_cents"], int)

    def test_evidence_entries_carry_citations(self) -> None:
        """Every evidence entry carries source id/url and derivation method (Req 3.2, 3.3)."""
        evidence = self.result["evidence"]
        self.assertIsInstance(evidence, list)
        self.assertTrue(evidence, "expected at least one evidence entry")
        for entry in evidence:
            self.assertIn("source_id", entry)
            self.assertTrue(entry["source_id"])
            self.assertIn("source_url", entry)
            self.assertTrue(entry["source_url"])
            self.assertIn("method", entry)
            self.assertTrue(entry["method"])
            # pdf_page must be present (may be None for some fields).
            self.assertIn("pdf_page", entry)

    def test_at_least_one_page_number(self) -> None:
        """At least one evidence entry cites an integer PDF page (Req 3.2)."""
        pages = [
            entry["pdf_page"]
            for entry in self.result["evidence"]
            if isinstance(entry["pdf_page"], int)
            and not isinstance(entry["pdf_page"], bool)
        ]
        self.assertTrue(
            pages,
            "expected at least one evidence entry with an integer pdf_page",
        )


class GetUnknownProductTests(unittest.TestCase):
    """An unknown SKU returns not-found without fabrication (Req 3.4)."""

    def test_unknown_sku_returns_not_found(self) -> None:
        result = get_product({"sku": "MON-999"})
        self.assertFalse(result["found"])
        self.assertEqual(result["sku"], "MON-999")
        # No fabricated specs or evidence leak into a not-found result.
        self.assertNotIn("evidence", result)
        self.assertNotIn("unit_price_cents", result)


class StockAndDeliveryUnavailableTests(unittest.TestCase):
    """Stock/delivery are reported unavailable, never fabricated (Req 3.5)."""

    def test_stock_and_delivery_unavailable(self) -> None:
        result = get_product({"sku": "MON-001"})
        self.assertIsNone(result["stock_quantity"])
        self.assertIsNone(result["delivery_lead_days"])
        self.assertIn("availability_note", result)
        self.assertIn("not available", result["availability_note"].lower())


if __name__ == "__main__":
    unittest.main()
