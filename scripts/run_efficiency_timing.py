"""Measure five Agent cases and combine them with human timing observations."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dell_agent.agent.loop import GatewayDriver, OfflineDriver

CASES = [
    ("TIME-001", "Exact quote: 8 P2425HE with SGD 2500 budget", ["Quote 8 P2425HE. Budget SGD 2500."], "ready_to_quote", 231200),
    ("TIME-002", "Multi-line quote: 2 S2425H and 1 U2724DE", ["Quote 2 S2425H and 1 U2724DE."], "ready_to_quote", 92700),
    ("TIME-003", "Discount quote: 2 P2725HE at 5 percent", ["Quote 2 P2725HE at a 5% discount."], "ready_to_quote", 66310),
    ("TIME-004", "Revision: 8 P2425HE changed to 10", ["Quote 8 P2425HE.", "Change that to 10 units."], "ready_to_quote", 289000),
    ("TIME-005", "Policy boundary: 5 S2725QC at 6 percent with delivery request", ["Quote 5 S2725QC with a 6% discount and guarantee delivery tomorrow."], "rule_violation", None),
]
CASE_IDS = {row[0] for row in CASES}


def has_fallback(result: dict[str, Any]) -> bool:
    return any(
        isinstance(row, dict) and row.get("step") == "gateway_fallback"
        for row in result.get("trace", [])
    )


def gateway_trace_counts(result: dict[str, Any]) -> tuple[bool, int]:
    trace = result.get("trace", [])
    started = any(
        isinstance(row, dict) and row.get("step") == "gateway_start"
        for row in trace
    )
    tool_calls = sum(
        isinstance(row, dict)
        and str(row.get("step", "")).startswith("gateway_turn_")
        and bool(row.get("tool"))
        for row in trace
    )
    return started, tool_calls


def load_manual(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    completed = []
    for row in rows:
        if row.get("duration_seconds"):
            row["duration_seconds"] = float(row["duration_seconds"])
            if row["duration_seconds"] <= 0:
                raise SystemExit(f"manual timing must be positive for {row.get('case_id')}")
            completed.append(row)
    return completed


def manual_is_complete(rows: list[dict[str, Any]]) -> bool:
    return (
        len(rows) == len(CASES)
        and {row.get("case_id") for row in rows} == CASE_IDS
        and all(
            row.get("operator")
            and row.get("started_at")
            and row.get("finished_at")
            and row.get("result_check") == "PASS"
            for row in rows
        )
    )


def stats(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {"count": len(values), "median_seconds": statistics.median(values), "min_seconds": min(values), "max_seconds": max(values)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--driver", choices=("offline", "gateway"), required=True)
    parser.add_argument("--gateway-url", default=os.getenv("LLM_GATEWAY_URL", ""))
    parser.add_argument("--model-id", default=os.getenv("LLM_MODEL", ""))
    parser.add_argument("--manual-csv", type=Path, default=ROOT / "reports/evaluation/manual-timing-input.csv")
    parser.add_argument("--label", default="first-pass")
    args = parser.parse_args()
    gateway_key = os.getenv("LLM_GATEWAY_API_KEY", "")
    if args.driver == "gateway" and (not args.gateway_url or not gateway_key or not args.model_id):
        parser.error("gateway timing requires LLM_GATEWAY_URL, LLM_GATEWAY_API_KEY and LLM_MODEL")

    driver = OfflineDriver() if args.driver == "offline" else GatewayDriver(
        base_url=args.gateway_url, api_key=gateway_key, model=args.model_id
    )
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{args.driver}-{args.label}"
    out = ROOT / "reports/evaluation/timing" / run_id
    out.mkdir(parents=True, exist_ok=False)
    rows: list[dict[str, Any]] = []
    for case_id, scenario, turns, expected_status, expected_total in CASES:
        started = datetime.now(timezone.utc)
        tick = time.perf_counter()
        result = driver.run(turns).to_dict()
        duration = time.perf_counter() - tick
        used_fallback = has_fallback(result)
        gateway_started, gateway_tool_calls = gateway_trace_counts(result)
        total = (result.get("quote_draft") or {}).get("total_cents")
        rows.append({
            "case_id": case_id, "scenario": scenario, "driver": args.driver,
            "model_id": args.model_id, "started_at": started.isoformat(),
            "duration_seconds": round(duration, 6), "status": result.get("status"),
            "total_cents": total if total is not None else "", "used_fallback": used_fallback,
            "gateway_started": gateway_started, "gateway_tool_calls": gateway_tool_calls,
            "result_check": result.get("status") == expected_status and (expected_total is None or total == expected_total),
        })
    with (out / "agent-timing.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)

    manual = load_manual(args.manual_csv)
    agent_stats = stats([float(row["duration_seconds"]) for row in rows])
    manual_stats = stats([float(row["duration_seconds"]) for row in manual])
    human_complete = manual_is_complete(manual)
    fallbacks = sum(bool(row["used_fallback"]) for row in rows)
    gateway_starts = sum(bool(row["gateway_started"]) for row in rows)
    gateway_tool_calls = sum(int(row["gateway_tool_calls"]) for row in rows)
    real_model_valid = (
        args.driver == "gateway"
        and fallbacks == 0
        and gateway_starts == len(rows)
        and gateway_tool_calls > 0
    )
    agent_correct = all(row["result_check"] for row in rows)
    summary = {
        "run_id": run_id, "driver": args.driver, "model_id": args.model_id or None,
        "gateway_url_sha256": hashlib.sha256(args.gateway_url.encode()).hexdigest() if args.gateway_url else None,
        "case_count": len(rows), "all_results_correct": agent_correct,
        "fallback_count": fallbacks, "valid_real_model_timing": real_model_valid,
        "gateway_started_count": gateway_starts,
        "gateway_tool_call_count": gateway_tool_calls,
        "agent": agent_stats, "human": manual_stats,
        "human_records_complete_and_correct": human_complete,
        "comparison_complete": real_model_valid and agent_correct and human_complete,
        "manual_source": str(args.manual_csv.relative_to(ROOT)) if args.manual_csv.is_relative_to(ROOT) else str(args.manual_csv),
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    human_line = "pending 5 human observations" if manual_stats is None else f"n={manual_stats['count']}, median={manual_stats['median_seconds']:.2f}s, range={manual_stats['min_seconds']:.2f}–{manual_stats['max_seconds']:.2f}s"
    (out / "report.md").write_text(
        f"# Efficiency timing — {run_id}\n\n"
        f"- Agent: n={agent_stats['count']}, median={agent_stats['median_seconds']:.3f}s, range={agent_stats['min_seconds']:.3f}–{agent_stats['max_seconds']:.3f}s\n"
        f"- Human: {human_line}\n"
        f"- Valid real-model timing: **{summary['valid_real_model_timing']}**\n"
        f"- Comparison complete: **{summary['comparison_complete']}**\n",
        encoding="utf-8",
    )
    print(out.relative_to(ROOT))
    if args.driver == "gateway" and not real_model_valid:
        return 2
    if args.driver == "gateway" and not summary["comparison_complete"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
