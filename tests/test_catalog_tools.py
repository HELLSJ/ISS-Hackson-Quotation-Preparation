"""Contract tests for the canonical quotation tool implementation.

The CLI compatibility wrapper must delegate to ``dell_agent.agent.tools``;
there is intentionally no second catalogue or pricing engine in scripts/.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dell_agent.agent.tools import dispatch
from scripts.catalog_tools import CatalogTools, ToolError


class CanonicalContractTests(unittest.TestCase):
    def test_usb_video_and_host_power(self) -> None:
        rows = dispatch("search_products", {"usb_c_video": True, "min_pd_watts": 90})
        skus = {p["sku"] for p in rows}
        self.assertTrue({"MON-007", "MON-008", "MON-009", "MON-011"}.issubset(skus))
        self.assertGreater(len(rows), 4)
        self.assertTrue(all(p["usb_c_video"] and p["usb_c_pd_watts"] >= 90 for p in rows))

    def test_data_only_port_is_not_video(self) -> None:
        self.assertEqual(dispatch("search_products", {"query": "U2724D", "usb_c_video": True}), [])
        product = dispatch("get_product", {"sku": "MON-010"})
        self.assertTrue(product["found"])
        self.assertFalse(product["usb_c_video"])
        self.assertEqual(product["usb_c_downstream_charge_watts"], 15)

    def test_exact_model_does_not_silently_substitute(self) -> None:
        rows = dispatch("search_products", {"query": "P2425"})
        self.assertEqual([p["model"] for p in rows], ["P2425"])

    def test_precise_diagonal_is_used(self) -> None:
        rows = dispatch("search_products", {"query": "P2425HE", "min_screen_inches": 24})
        self.assertEqual(rows, [])

    def test_unknown_product_is_explicit(self) -> None:
        self.assertEqual(dispatch("get_product", {"sku": "MON-999"}), {"found": False, "sku": "MON-999"})

    def test_product_lookup_enforces_its_schema(self) -> None:
        self.assertEqual(dispatch("get_product", {})["error"], "bad_argument")
        self.assertEqual(dispatch("get_product", {"sku": 7})["error"], "bad_argument")
        self.assertEqual(
            dispatch("get_product", {"sku": "MON-001", "price": True})["error"],
            "bad_argument",
        )

    def test_quote_budget_and_revision_anchors(self) -> None:
        initial = dispatch("calculate_quote", {"items": [{"sku": "MON-007", "quantity": 8}], "budget_cents": 250000})
        revised = dispatch("calculate_quote", {"items": [{"sku": "MON-007", "quantity": 10}], "budget_cents": 250000})
        self.assertEqual(initial["total_cents"], 231200)
        self.assertTrue(initial["within_budget"])
        self.assertEqual(revised["total_cents"], 289000)
        self.assertEqual(revised["over_budget_cents"], 39000)

    def test_invalid_quantity_is_structured_error(self) -> None:
        for quantity in (None, 0, -1, 1.5, True, "2"):
            with self.subTest(quantity=quantity):
                result = dispatch("calculate_quote", {"items": [{"sku": "MON-001", "quantity": quantity}]})
                self.assertEqual(result["error"], "invalid_quantity")

    def test_discount_limit_is_structured_error(self) -> None:
        result = dispatch("calculate_quote", {"items": [{"sku": "MON-001", "quantity": 2, "discount_bps": 501}]})
        self.assertEqual(result["error"], "discount_limit_exceeded")

    def test_price_override_is_forbidden(self) -> None:
        result = dispatch("calculate_quote", {"items": [{"sku": "MON-001", "quantity": 1, "unit_price_cents": 1}]})
        self.assertEqual(result["error"], "custom_price_forbidden")

    def test_unknown_tool_and_argument_are_rejected(self) -> None:
        self.assertEqual(dispatch("delete_all", {})["error"], "unknown_tool")
        self.assertEqual(dispatch("search_products", {"stock": True})["error"], "bad_argument")
        self.assertEqual(dispatch("search_products", [])["error"], "bad_argument")
        self.assertEqual(
            dispatch("calculate_quote", {"items": [{"sku": "MON-001", "quantity": 1}], "currency": "USD"})["error"],
            "bad_argument",
        )
        self.assertEqual(
            dispatch("calculate_quote", {"items": [{"sku": "MON-001", "quantity": 1, "note": "override"}]})["error"],
            "bad_argument",
        )

    def test_negative_budget_is_rejected(self) -> None:
        result = dispatch(
            "calculate_quote",
            {"items": [{"sku": "MON-001", "quantity": 1}], "budget_cents": -1},
        )
        self.assertEqual(result["error"], "bad_argument")

    def test_duplicate_skus_remain_separate_lines(self) -> None:
        result = dispatch("calculate_quote", {"items": [{"sku": "MON-001", "quantity": 1}, {"sku": "MON-001", "quantity": 2}]})
        self.assertEqual(len(result["lines"]), 2)
        self.assertEqual(result["total_cents"], 44700)

    def test_independent_expected_amounts(self) -> None:
        for raw in (ROOT / "data/evaluation/expected_results.jsonl").read_text().splitlines():
            case = json.loads(raw)
            expected = case["expected"]
            if "items" not in expected:
                continue
            independent = 0
            for item in expected["items"]:
                product = dispatch("get_product", {"sku": item["sku"]})
                gross = Decimal(product["unit_price_cents"]) * item["quantity"]
                deduction = (gross * Decimal(item.get("discount_bps", 0)) / 10000).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                independent += int(gross - deduction)
            self.assertEqual(independent, expected["total_cents"], case["case_id"])
            self.assertEqual(dispatch("calculate_quote", {"items": expected["items"]})["total_cents"], independent)


class CompatibilityAndCliTests(unittest.TestCase):
    def test_compatibility_class_delegates_and_raises(self) -> None:
        adapter = CatalogTools()
        self.assertEqual(adapter.calculate_quote([{"sku": "MON-007", "quantity": 8}])["total_cents"], 231200)
        with self.assertRaises(ToolError):
            adapter.dispatch("delete_all", {})

    def test_cli_emits_canonical_shape(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/catalog_tools.py", "search_products", '{"query":"P2425HE"}'],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        result = json.loads(completed.stdout)
        self.assertIsInstance(result, list)
        self.assertEqual(result[0]["sku"], "MON-007")

    def test_cli_error_exits_two(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/catalog_tools.py", "calculate_quote", '{"items":[{"sku":"MON-007","quantity":0}]}'],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(json.loads(completed.stdout)["error"], "invalid_quantity")


if __name__ == "__main__":
    unittest.main()
