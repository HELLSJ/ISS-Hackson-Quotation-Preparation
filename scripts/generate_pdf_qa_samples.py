"""Regenerate the stable one-page and multi-page PDF review fixtures."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.quote_pdf import render_confirmed_quote

OUTPUT = ROOT / "output/pdf"


def standard_snapshot() -> dict:
    line = {
        "line_id": "line-mon-007-001",
        "sku": "MON-007",
        "model": "P2425HE",
        "name": "Dell P2425HE Monitor",
        "quantity": 8,
        "unit_price_cents": 28900,
        "discount_bps": 0,
        "gross_cents": 231200,
        "discount_cents": 0,
        "net_cents": 231200,
    }
    return {
        "status": "confirmed",
        "is_confirmed": True,
        "quote_number": "Q-20260920-QA-R1",
        "quote_version": 1,
        "currency": "SGD",
        "customer": {"display_name": "Café Example"},
        "quote_date": "2026-09-20",
        "valid_until": "2026-09-27",
        "confirmation": {
            "confirmed_by": "Sales Admin",
            "confirmed_at": "2026-09-20T01:00:00+00:00",
        },
        "lines": [line],
        "subtotal_cents": 231200,
        "shipping_fee_cents": 0,
        "total_cents": 231200,
        "pricing_context": {
            "dataset_version": "2026-09-14",
            "price_version": "demo-policy-2026-09-14",
            "rule_version": "demo-policy-2026-09-14",
        },
        "terms": {
            "tax_note": "Demo quotation: tax is not modelled; this is not a tax invoice.",
            "disclaimer": "synthetic demo, not a tax invoice",
        },
    }


def long_snapshot() -> dict:
    snapshot = standard_snapshot()
    snapshot["quote_number"] = "Q-20260920-QA-LONG-R1"
    original = snapshot["lines"][0]
    snapshot["lines"] = []
    for index in range(45):
        line = copy.deepcopy(original)
        line["line_id"] = f"line-{index + 1:03d}"
        line["name"] = (
            "Dell P2425HE Monitor - enterprise workstation display with ergonomic stand "
            f"and extended support configuration, line {index + 1}"
        )
        snapshot["lines"].append(line)
    snapshot["subtotal_cents"] = sum(line["net_cents"] for line in snapshot["lines"])
    snapshot["total_cents"] = snapshot["subtotal_cents"] + snapshot["shipping_fee_cents"]
    return snapshot


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    artifacts = {
        OUTPUT / "quotation-qa-standard.pdf": standard_snapshot(),
        OUTPUT / "quotation-qa-long.pdf": long_snapshot(),
    }
    for path, snapshot in artifacts.items():
        path.write_bytes(render_confirmed_quote(snapshot))
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
