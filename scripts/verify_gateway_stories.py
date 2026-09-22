"""Exercise the two boundary stories against the configured organizer gateway."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dell_agent.agent.loop import GatewayDriver


STORIES = (
    ("B", "Quote 4 U2724D for one-cable laptop video and 90W charging."),
    ("C", "Quote 5 S2725QC with a 6% discount and guarantee delivery tomorrow."),
)


def has_fallback(result: dict[str, Any]) -> bool:
    return any(row.get("step") == "gateway_fallback" for row in result.get("trace", []))


def summarize(story: str, result: dict[str, Any]) -> dict[str, Any]:
    tools = [row["tool"] for row in result.get("trace", []) if row.get("tool")]
    citation_skus = sorted({row["sku"] for row in result.get("citations", []) if row.get("sku")})
    notes = " ".join(str(note) for note in result.get("notes", [])).lower()
    expected_status = "explain_limitation" if story == "B" else "rule_violation"
    required_sku = "MON-010" if story == "B" else "MON-012"
    passed = (
        result.get("status") == expected_status
        and not has_fallback(result)
        and "get_product" in tools
        and required_sku in citation_skus
        and not result.get("quote_draft")
    )
    if story == "C":
        passed = passed and "delivery" in notes and any(
            phrase in notes for phrase in ("unknown", "unavailable", "cannot guarantee", "not available")
        )
    return {
        "story": story,
        "status": result.get("status"),
        "used_fallback": has_fallback(result),
        "tools": tools,
        "citation_skus": citation_skus,
        "has_quote_draft": bool(result.get("quote_draft")),
        "delivery_unknown_mentioned": "delivery" in notes and any(
            phrase in notes for phrase in ("unknown", "unavailable", "cannot guarantee", "not available")
        ),
        "tool_retry_used": any(
            row.get("result") == "tool_required_retry" for row in result.get("trace", [])
        ),
        "policy_guard_used": any(
            row.get("step") == "local_policy_guard" for row in result.get("trace", [])
        ),
        "passed": passed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    base_url = os.getenv("LLM_GATEWAY_URL", "")
    api_key = os.getenv("LLM_GATEWAY_API_KEY", "")
    model = os.getenv("LLM_MODEL", "")
    if not (base_url and api_key and model):
        parser.error("LLM_GATEWAY_URL, LLM_GATEWAY_API_KEY and LLM_MODEL are required")

    driver = GatewayDriver(base_url=base_url, api_key=api_key, model=model)
    summaries = []
    for story, prompt in STORIES:
        summaries.append(summarize(story, driver.run(prompt).to_dict()))
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "label": args.label,
        "stories": summaries,
        "passed": all(row["passed"] for row in summaries),
    }
    output = ROOT / "reports" / "evaluation" / f"gateway-stories-bc-20260922-{args.label}.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output.relative_to(ROOT))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
