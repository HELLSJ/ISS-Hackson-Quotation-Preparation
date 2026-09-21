"""CLI and compatibility wrapper for the canonical quotation tools.

The only product/pricing implementation lives in ``dell_agent.agent.tools``.
This module deliberately contains no catalogue loading, filtering, validation,
or money arithmetic so CLI, Agent, Gateway and HTTP behavior cannot drift.

Usage:
    python scripts/catalog_tools.py search_products '{"usb_c_video":true}'
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dell_agent.agent.tools import dispatch as canonical_dispatch


class ToolError(ValueError):
    """Compatibility exception for callers using the old class interface."""


def _raise_on_error(result: Any) -> Any:
    if isinstance(result, dict) and "error" in result:
        raise ToolError(f"{result['error']}: {result.get('message', '')}".rstrip())
    return result


class CatalogTools:
    """Thin compatibility adapter; new code should import canonical dispatch."""

    def dispatch(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        return _raise_on_error(canonical_dispatch(name, arguments or {}))

    def search_products(self, **filters: Any) -> Any:
        return self.dispatch("search_products", filters)

    def get_product(self, sku: str) -> Dict[str, Any]:
        return self.dispatch("get_product", {"sku": sku})

    def calculate_quote(
        self, items: Any, budget_cents: Optional[int] = None
    ) -> Dict[str, Any]:
        arguments: Dict[str, Any] = {"items": items}
        if budget_cents is not None:
            arguments["budget_cents"] = budget_cents
        return self.dispatch("calculate_quote", arguments)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "tool", choices=["search_products", "get_product", "calculate_quote"]
    )
    parser.add_argument("arguments", help="JSON object")
    args = parser.parse_args()

    try:
        arguments = json.loads(args.arguments)
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": "bad_argument", "message": str(exc)}))
        raise SystemExit(2) from exc

    result = canonical_dispatch(args.tool, arguments)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if isinstance(result, dict) and "error" in result:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
