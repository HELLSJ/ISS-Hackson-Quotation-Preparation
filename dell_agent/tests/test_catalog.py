"""Tests for catalogue loading and fail-fast validation.

Covers Requirements 1.3, 1.4, and 1.6:
  * exactly 12 SKUs load from the frozen catalogue (Req 1.1/1.6);
  * ``screen_inches`` stays precise and is never rounded to a marketed size
    class (Req 1.4) - MON-004 has a genuinely non-integer diagonal (23.81);
  * unknown facts (``stock_quantity``/``delivery_lead_days``) stay ``None`` and
    are never coerced to 0/false (Req 1.3);
  * a corrupted catalogue (wrong product count, duplicate SKU, missing required
    field, or ``discount_limit_bps`` != 500) raises :class:`CatalogError`
    (Req 1.6).

Runs on the Python standard library only::

    python -m unittest dell_agent.tests.test_catalog
    python -m dell_agent.tests.test_catalog
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from dell_agent.data.catalog import (
    CatalogError,
    DEFAULT_CATALOG_PATH,
    EXPECTED_PRODUCT_COUNT,
    load_catalog,
)


def _read_default_doc() -> dict:
    """Load the real frozen catalogue JSON as a plain dict for mutation."""
    with DEFAULT_CATALOG_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


class LoadValidCatalogTests(unittest.TestCase):
    """The real, uncorrupted catalogue must load and preserve facts."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.products, cls.rules = load_catalog()

    def test_twelve_skus_load(self) -> None:
        """Exactly 12 monitor SKUs load (Req 1.1/1.6)."""
        self.assertEqual(len(self.products), EXPECTED_PRODUCT_COUNT)
        self.assertEqual(len(self.products), 12)

    def test_screen_inches_stays_precise(self) -> None:
        """A genuinely non-integer diagonal is preserved verbatim (Req 1.4).

        MON-004 (P2425H) has a viewable diagonal of 23.81 in the manual; the
        loader must not round it to the marketed 24" size class.
        """
        mon004 = self.products["MON-004"]
        self.assertEqual(mon004.screen_inches, 23.81)
        # Not rounded to an integer/marketed class.
        self.assertNotEqual(mon004.screen_inches, 24)
        self.assertNotEqual(mon004.screen_inches, round(mon004.screen_inches))

    def test_null_facts_stay_null(self) -> None:
        """Unknown facts remain None, never coerced to 0/false (Req 1.3)."""
        for product in self.products.values():
            self.assertIsNone(
                product.stock_quantity,
                f"{product.sku} stock_quantity should stay None",
            )
            self.assertIsNone(
                product.delivery_lead_days,
                f"{product.sku} delivery_lead_days should stay None",
            )

    def test_rules_discount_limit(self) -> None:
        """The synthetic discount ceiling and snapshot provenance are frozen."""
        self.assertEqual(self.rules.discount_limit_bps, 500)
        self.assertEqual(self.rules.rule_version, "demo-v1")
        self.assertEqual(self.rules.price_version, "demo-v1")
        self.assertEqual(self.rules.effective_date, "2026-09-14")
        self.assertEqual(self.rules.rounding, "half_up_per_line_discount")
        self.assertEqual(self.rules.tax_mode, "not_modelled")
        self.assertEqual(self.rules.source_type, "synthetic")
        self.assertTrue(self.rules.confirmation_required)


class CorruptedCatalogTests(unittest.TestCase):
    """Corrupted catalogues must fail fast with CatalogError (Req 1.6)."""

    def _write_temp_catalog(self, doc: dict) -> Path:
        """Write ``doc`` to a temp JSON file and return its path."""
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        try:
            json.dump(doc, tmp)
        finally:
            tmp.close()
        path = Path(tmp.name)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        return path

    def test_wrong_product_count_raises(self) -> None:
        """A catalogue with 11 products (not 12) fails fast."""
        doc = _read_default_doc()
        doc["products"] = doc["products"][:11]
        path = self._write_temp_catalog(doc)
        with self.assertRaises(CatalogError):
            load_catalog(path=path)

    def test_duplicate_sku_raises(self) -> None:
        """A catalogue with a duplicate SKU fails fast."""
        doc = _read_default_doc()
        # Replace the last product with a duplicate of the first, keeping the
        # count at exactly 12 so the duplicate check is what trips.
        doc["products"][-1] = copy.deepcopy(doc["products"][0])
        path = self._write_temp_catalog(doc)
        with self.assertRaises(CatalogError):
            load_catalog(path=path)

    def test_missing_required_field_raises(self) -> None:
        """A record missing a required field fails fast."""
        doc = _read_default_doc()
        del doc["products"][0]["screen_inches"]
        path = self._write_temp_catalog(doc)
        with self.assertRaises(CatalogError):
            load_catalog(path=path)

    def test_missing_price_raises(self) -> None:
        """A record missing price.unit_price_cents fails fast."""
        doc = _read_default_doc()
        doc["products"][0].pop("price", None)
        path = self._write_temp_catalog(doc)
        with self.assertRaises(CatalogError):
            load_catalog(path=path)

    def test_bad_discount_limit_raises(self) -> None:
        """A rules block with discount_limit_bps != 500 fails fast."""
        doc = _read_default_doc()
        doc["rules"]["discount_limit_bps"] = 600
        path = self._write_temp_catalog(doc)
        with self.assertRaises(CatalogError):
            load_catalog(path=path)


if __name__ == "__main__":
    unittest.main()
