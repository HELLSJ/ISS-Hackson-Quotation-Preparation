"""Tests for the ``search_products`` tool (Req 2).

Covers the frozen search behaviour and its two correctness properties:

  * the canonical USB-C video + PD filter returns exactly
    ``[MON-007, MON-008, MON-009, MON-011]`` price-ascending (Req 2.9);
  * the data-only USB-C model (MON-010 / U2724D) is excluded from
    ``usb_c_video: true`` results (Req 2.7);
  * an unknown (``null``) field never satisfies a filter (Req 2.3);
  * no match returns exactly ``[]`` with no substitution (Req 2.6);
  * ``query`` is a keyword against model/sku/name/aliases only, never a
    natural-language sentence (Req 2.2);
  * an unknown parameter key is rejected with ``bad_argument`` (Req 2.1).

Property 8 (search soundness) and Property 9 (no silent substitution) are
exercised with randomised filter combinations against the real catalogue,
plus a swapped-in catalogue that contains a genuine ``null`` field to prove a
null value never satisfies a numeric filter.

Runs on the Python standard library only::

    python -m unittest dell_agent.tests.test_search
    python -m dell_agent.tests.test_search
"""

from __future__ import annotations

import random
import unittest
from dataclasses import replace
from typing import Any, Dict, List

from dell_agent.agent import tools
from dell_agent.data import catalog
from dell_agent.models import Product

# Deterministic randomness for the property tests.
_SEED = 20240117
_ITERATIONS = 500


def _skus(result: Any) -> List[str]:
    """Extract the SKU list from a search result (assumes a list result)."""
    return [row["sku"] for row in result]


class SearchExampleTests(unittest.TestCase):
    """Concrete, catalogue-anchored examples (Req 2.2, 2.6, 2.7, 2.9)."""

    def test_usb_c_video_and_pd_returns_exact_price_sorted_set(self) -> None:
        """{usb_c_video:true, min_pd_watts:90} -> exactly the 4 SKUs, price asc (Req 2.9)."""
        result = tools.search_products({"usb_c_video": True, "min_pd_watts": 90})
        self.assertEqual(
            _skus(result),
            ["MON-007", "MON-008", "MON-009", "MON-011"],
        )
        # Explicitly assert the ordering is by ascending unit price (Req 2.5).
        prices = [row["unit_price_cents"] for row in result]
        self.assertEqual(prices, sorted(prices))

    def test_data_only_usb_c_excluded_from_usb_c_video(self) -> None:
        """MON-010 / U2724D (data-only USB-C) is never in usb_c_video:true results (Req 2.7)."""
        # Sanity-check the fixture: MON-010 really is a data-only USB-C model.
        mon010 = catalog.get("MON-010")
        self.assertEqual(mon010.model, "U2724D")
        self.assertFalse(mon010.usb_c_video)

        result = tools.search_products({"usb_c_video": True})
        self.assertNotIn("MON-010", _skus(result))
        # And every returned product genuinely carries video-capable USB-C.
        for row in result:
            self.assertTrue(row["usb_c_video"])

    def test_no_match_returns_empty_list(self) -> None:
        """An impossible price ceiling yields exactly [] (Req 2.6)."""
        result = tools.search_products({"max_unit_price_cents": 1})
        self.assertEqual(result, [])

    def test_query_is_keyword_only(self) -> None:
        """query matches model/sku/alias keywords, not full sentences (Req 2.2)."""
        # A model keyword matches its single product.
        self.assertEqual(_skus(tools.search_products({"query": "P2425HE"})), ["MON-007"])
        # A SKU keyword matches.
        self.assertEqual(_skus(tools.search_products({"query": "MON-007"})), ["MON-007"])
        # An alias keyword matches (MON-001 aliases include "Dell S2425H").
        self.assertIn("MON-001", _skus(tools.search_products({"query": "S2425H"})))
        # A full natural-language sentence is NOT interpreted as a query and
        # matches nothing (it is not a substring of any keyword field).
        sentence = "I need a usb-c monitor for my laptop with charging"
        self.assertEqual(tools.search_products({"query": sentence}), [])

    def test_unknown_key_is_bad_argument(self) -> None:
        """An unknown parameter key is rejected, not silently ignored (Req 2.1)."""
        result = tools.search_products({"colour": "black"})
        self.assertIsInstance(result, dict)
        self.assertEqual(result["error"], "bad_argument")
        self.assertEqual(tools.dispatch("search_products", [] )["error"], "bad_argument")


class NullFieldFilterTests(unittest.TestCase):
    """A null field never satisfies a filter (Req 2.3, Property 8).

    No real catalogue product has a ``null`` ``max_refresh_hz``, so this swaps
    in a catalogue where one product's field is genuinely ``None`` and confirms
    ``min_refresh_hz`` excludes it.
    """

    def setUp(self) -> None:
        real = catalog.all_products()
        # Force MON-010's max_refresh_hz to None to simulate an unknown fact.
        self._patched: List[Product] = [
            replace(p, max_refresh_hz=None) if p.sku == "MON-010" else p
            for p in real
        ]
        self._orig_all_products = tools.catalog.all_products
        tools.catalog.all_products = lambda: list(self._patched)  # type: ignore[assignment]

    def tearDown(self) -> None:
        tools.catalog.all_products = self._orig_all_products  # type: ignore[assignment]

    def test_null_field_excluded_by_min_filter(self) -> None:
        """A product with max_refresh_hz=None fails a min_refresh_hz filter (Req 2.3)."""
        # Baseline: with a numeric max_refresh_hz MON-010 would qualify at 120.
        result = tools.search_products({"min_refresh_hz": 100})
        self.assertNotIn("MON-010", _skus(result))
        # Products that DO have a known refresh >= 100 still appear.
        self.assertTrue(len(result) > 0)
        for row in result:
            self.assertIsNotNone(row["max_refresh_hz"])
            self.assertGreaterEqual(row["max_refresh_hz"], 100)


# --------------------------------------------------------------------------- #
# Property tests (Property 8 & 9) — stdlib random, fixed seed
# --------------------------------------------------------------------------- #

# Candidate filter values drawn from the real catalogue's value space so the
# generator explores meaningful matches and non-matches.
_QUERY_CHOICES = [None, "P2425", "MON", "U2724", "Dell", "S2725", "zzz-nomatch"]
_USB_C_CHOICES = [None, True, False]
_PD_CHOICES = [None, 65, 90, 91, 240]
_MIN_SCREEN_CHOICES = [None, 21.5, 23.8, 24.0, 27.0]
_MAX_SCREEN_CHOICES = [None, 23.81, 24.07, 27.0]
_RESOLUTION_CHOICES = [None, "1920x1080", "1920x1200", "2560x1440", "3840x2160", "nope"]
_MIN_REFRESH_CHOICES = [None, 100, 101, 120, 121]
_MAX_PRICE_CHOICES = [None, 1, 20000, 30000, 50000, 10_000_000]


def _random_filters(rng: random.Random) -> Dict[str, Any]:
    """Build a random, schema-valid filter dict from the catalogue value space."""
    candidate = {
        "query": rng.choice(_QUERY_CHOICES),
        "usb_c_video": rng.choice(_USB_C_CHOICES),
        "min_pd_watts": rng.choice(_PD_CHOICES),
        "min_screen_inches": rng.choice(_MIN_SCREEN_CHOICES),
        "max_screen_inches": rng.choice(_MAX_SCREEN_CHOICES),
        "resolution": rng.choice(_RESOLUTION_CHOICES),
        "min_refresh_hz": rng.choice(_MIN_REFRESH_CHOICES),
        "max_unit_price_cents": rng.choice(_MAX_PRICE_CHOICES),
    }
    # Drop the None entries so we exercise varying subsets of filters.
    return {k: v for k, v in candidate.items() if v is not None}


class SearchPropertyTests(unittest.TestCase):
    """Property 8 (soundness) and Property 9 (no silent substitution)."""

    def _assert_row_satisfies_filters(
        self, row: Dict[str, Any], filters: Dict[str, Any]
    ) -> None:
        """Every provided filter must hold for a returned row; null never passes."""
        if "query" in filters:
            needle = str(filters["query"]).strip().lower()
            product = catalog.get(row["sku"])
            haystacks = [product.model, product.sku, product.name, *product.aliases]
            self.assertTrue(
                any(needle in (h or "").lower() for h in haystacks),
                f"{row['sku']} does not match query {filters['query']!r}",
            )
        if "usb_c_video" in filters:
            self.assertIsNotNone(row["usb_c_video"])
            self.assertEqual(row["usb_c_video"], filters["usb_c_video"])
        if "min_pd_watts" in filters:
            self.assertIsNotNone(row["usb_c_pd_watts"])
            self.assertGreaterEqual(row["usb_c_pd_watts"], filters["min_pd_watts"])
        if "min_screen_inches" in filters:
            self.assertIsNotNone(row["screen_inches"])
            self.assertGreaterEqual(row["screen_inches"], filters["min_screen_inches"])
        if "max_screen_inches" in filters:
            self.assertIsNotNone(row["screen_inches"])
            self.assertLessEqual(row["screen_inches"], filters["max_screen_inches"])
        if "resolution" in filters:
            self.assertIsNotNone(row["resolution"])
            self.assertEqual(row["resolution"], filters["resolution"])
        if "min_refresh_hz" in filters:
            self.assertIsNotNone(row["max_refresh_hz"])
            self.assertGreaterEqual(row["max_refresh_hz"], filters["min_refresh_hz"])
        if "max_unit_price_cents" in filters:
            self.assertIsNotNone(row["unit_price_cents"])
            self.assertLessEqual(row["unit_price_cents"], filters["max_unit_price_cents"])

    def test_property_8_search_soundness(self) -> None:
        """Every result satisfies all filters and is price-ascending (Property 8)."""
        rng = random.Random(_SEED)
        for _ in range(_ITERATIONS):
            filters = _random_filters(rng)
            result = tools.search_products(filters)
            # Randomly generated filters are always schema-valid -> list result.
            self.assertIsInstance(result, list, f"filters={filters} -> {result}")

            # Soundness: each returned product satisfies every provided filter,
            # and a null field never sneaks through.
            for row in result:
                self._assert_row_satisfies_filters(row, filters)

            # Sorted by unit_price_cents ascending.
            prices = [row["unit_price_cents"] for row in result]
            self.assertEqual(prices, sorted(prices), f"unsorted for filters={filters}")

    def test_property_8_null_field_never_satisfies_filter(self) -> None:
        """A genuine null field is never returned by the corresponding filter (Property 8)."""
        rng = random.Random(_SEED + 1)
        real = catalog.all_products()
        # Swap in a catalogue where MON-010 has an unknown (None) refresh rate.
        patched = [
            replace(p, max_refresh_hz=None) if p.sku == "MON-010" else p
            for p in real
        ]
        orig = tools.catalog.all_products
        tools.catalog.all_products = lambda: list(patched)  # type: ignore[assignment]
        try:
            for _ in range(_ITERATIONS):
                threshold = rng.choice([1, 60, 100, 120, 500])
                result = tools.search_products({"min_refresh_hz": threshold})
                # The null-refresh product must never appear.
                self.assertNotIn("MON-010", _skus(result))
                # Anything returned has a known refresh meeting the threshold.
                for row in result:
                    self.assertIsNotNone(row["max_refresh_hz"])
                    self.assertGreaterEqual(row["max_refresh_hz"], threshold)
        finally:
            tools.catalog.all_products = orig  # type: ignore[assignment]

    def test_property_9_no_silent_substitution(self) -> None:
        """When nothing matches, the result is exactly [] (Property 9)."""
        rng = random.Random(_SEED + 2)
        # Deliberately construct unsatisfiable filters and confirm [] every time.
        impossible_filters = [
            {"max_unit_price_cents": 1},
            {"min_pd_watts": 10_000},
            {"min_screen_inches": 100.0},
            {"max_screen_inches": 1.0},
            {"resolution": "no-such-resolution"},
            {"min_refresh_hz": 10_000},
            {"query": "definitely-not-a-model-or-sku"},
            {"usb_c_video": True, "max_unit_price_cents": 1},
        ]
        for _ in range(_ITERATIONS):
            filters = rng.choice(impossible_filters)
            result = tools.search_products(filters)
            self.assertEqual(result, [], f"expected [] for filters={filters}")


if __name__ == "__main__":
    unittest.main()
