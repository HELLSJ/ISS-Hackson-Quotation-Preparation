"""Run inference first, then open the sealed answer key and score the run."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dell_agent.agent.loop import GatewayDriver, OfflineDriver

SEALED_INPUTS = ROOT / "data/evaluation/sealed_holdout_enquiries.jsonl"
SEALED_EXPECTED = ROOT / "reports/evaluation/sealed_holdout_expected.jsonl"
SEALED_MANIFEST = ROOT / "reports/evaluation/sealed-holdout-manifest.json"
RUNS = ROOT / "reports/evaluation/runs"
OVER_BUDGET = re.compile(r"by\s+(\d+)\s+cents", re.I)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()


def git_state() -> dict[str, Any]:
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout
    diff = subprocess.run(
        ["git", "diff", "--binary", "HEAD"], cwd=ROOT, capture_output=True, check=True
    ).stdout
    return {
        "git_dirty": bool(status.strip()),
        "git_status_sha256": hashlib.sha256(status.encode()).hexdigest(),
        "git_diff_sha256": hashlib.sha256(diff).hexdigest(),
    }


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


def verify_manifest(require_review: bool) -> dict[str, Any]:
    manifest = json.loads(SEALED_MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("case_count") != 20:
        raise SystemExit("sealed manifest must contain exactly 20 cases")
    if manifest.get("inputs_sha256") != sha256(SEALED_INPUTS):
        raise SystemExit("sealed input hash does not match the manifest")
    if require_review and manifest.get("status") != "SEALED_REVIEW_PASSED":
        raise SystemExit(
            "sealed holdout is not independently approved; complete the review sheet and run "
            "scripts/prepare_sealed_holdout_review.py --finalize"
        )
    return manifest


def line_tuples(result: dict[str, Any]) -> list[tuple[str, int, int]]:
    return sorted(
        (str(line.get("sku")), int(line.get("quantity", 0)), int(line.get("discount_bps", 0)))
        for line in (result.get("quote_draft") or {}).get("lines", [])
    )


def expected_line_tuples(expected: dict[str, Any]) -> list[tuple[str, int, int]]:
    return sorted(
        (str(line["sku"]), int(line["quantity"]), int(line.get("discount_bps", 0)))
        for line in expected.get("items", [])
    )


def over_budget(result: dict[str, Any]) -> int | None:
    draft = result.get("quote_draft") or {}
    if draft.get("over_budget_cents") is not None:
        return int(draft["over_budget_cents"])
    for note in result.get("notes", []):
        match = OVER_BUDGET.search(str(note))
        if match:
            return int(match.group(1))
    return None


def score(case: dict[str, Any], result: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, bool] = {"status": result.get("status") == expected.get("status")}
    if "ask_for" in expected:
        checks["clarification"] = result.get("ask_for") == expected["ask_for"]
    if expected.get("items") and expected.get("status") == "ready_to_quote":
        checks["selection"] = line_tuples(result) == expected_line_tuples(expected)
    if "total_cents" in expected and expected.get("status") == "ready_to_quote":
        checks["amount"] = (result.get("quote_draft") or {}).get("total_cents") == expected["total_cents"]
    if "within_budget" in expected:
        checks["budget"] = (result.get("quote_draft") or {}).get("within_budget") == expected["within_budget"]
    if "over_budget_cents" in expected:
        checks["over_budget"] = over_budget(result) == expected["over_budget_cents"]
    if expected.get("evidence_required"):
        citations = result.get("citations") or []
        checks["evidence"] = bool(citations) and (
            "sku" not in expected or any(row.get("sku") == expected["sku"] for row in citations)
        )
    if expected.get("status") in {"rule_violation", "invalid_quantity"}:
        checks["policy_block"] = checks["status"] and not result.get("quote_draft")
    failed = [name for name, passed in checks.items() if not passed]
    category = ""
    if failed:
        category = (
            "model_transport" if result.get("used_fallback") else
            "pricing_or_tool" if any(name in failed for name in ("amount", "budget", "over_budget")) else
            "tool_parameters" if "selection" in failed else
            "result_assembly" if "evidence" in failed else
            "requirements_or_state"
        )
    return {"case_id": case["case_id"], "checks": checks, "passed": not failed, "failed_checks": failed, "failure_category": category}


def rate(scored: list[dict[str, Any]], key: str) -> dict[str, Any]:
    values = [row["checks"][key] for row in scored if key in row["checks"]]
    return {"passed": sum(values), "total": len(values), "rate": (sum(values) / len(values)) if values else None}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--driver", choices=("offline", "gateway"), required=True)
    parser.add_argument("--gateway-url", default=os.getenv("LLM_GATEWAY_URL", ""))
    parser.add_argument("--model-id", default=os.getenv("LLM_MODEL", ""))
    parser.add_argument("--label", default="first-pass")
    args = parser.parse_args()
    gateway_key = os.getenv("LLM_GATEWAY_API_KEY", "")
    if args.driver == "gateway" and (not args.gateway_url or not gateway_key or not args.model_id):
        parser.error("gateway evaluation requires LLM_GATEWAY_URL, LLM_GATEWAY_API_KEY and LLM_MODEL")

    manifest = verify_manifest(require_review=args.driver == "gateway")
    cases = load_jsonl(SEALED_INPUTS)
    if len(cases) != manifest["case_count"]:
        raise SystemExit("sealed input count does not match the manifest")
    driver = OfflineDriver() if args.driver == "offline" else GatewayDriver(
        base_url=args.gateway_url, api_key=gateway_key, model=args.model_id
    )
    started = datetime.now(timezone.utc)
    run_id = started.strftime("%Y%m%dT%H%M%SZ") + f"-{args.driver}-{args.label}"
    out = RUNS / run_id
    out.mkdir(parents=True, exist_ok=False)

    raw: list[dict[str, Any]] = []
    with (out / "raw_results.jsonl").open("x", encoding="utf-8") as stream:
        for case in cases:
            tick = time.perf_counter()
            agent = driver.run(case["user_turns"])
            result = agent.to_dict()
            result["configured_driver"] = args.driver
            result["used_fallback"] = has_fallback(result)
            row = {
                "case_id": case["case_id"], "category": case["category"],
                "latency_ms": round((time.perf_counter() - tick) * 1000, 3), "result": result,
            }
            raw.append(row)
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    # The answer key is intentionally opened only after all model outputs are durable.
    if manifest.get("answer_key_sha256") != sha256(SEALED_EXPECTED):
        raise SystemExit("sealed answer-key hash does not match the manifest")
    expected = {row["case_id"]: row["expected"] for row in load_jsonl(SEALED_EXPECTED)}
    if set(expected) != {case["case_id"] for case in cases}:
        raise SystemExit("sealed input and answer-key IDs do not match")
    raw_by_id = {row["case_id"]: row for row in raw}
    scored = [score(case, raw_by_id[case["case_id"]]["result"], expected[case["case_id"]]) for case in cases]
    fallback_count = sum(bool(row["result"].get("used_fallback")) for row in raw)
    gateway_traces = [gateway_trace_counts(row["result"]) for row in raw]
    gateway_started_count = sum(started for started, _ in gateway_traces)
    gateway_tool_call_count = sum(count for _, count in gateway_traces)
    metrics = {
        "run_id": run_id,
        "label": args.label,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "driver": args.driver,
        "model_id": args.model_id or None,
        "gateway_url_sha256": hashlib.sha256(args.gateway_url.encode()).hexdigest() if args.gateway_url else None,
        "git_commit": git_head(),
        "dataset_version": cases[0]["dataset_version"],
        "price_version": "demo-v1",
        "rule_version": "demo-v1",
        "sealed_inputs_sha256": sha256(SEALED_INPUTS),
        "sealed_expected_sha256": sha256(SEALED_EXPECTED),
        "answer_key_loaded_after_inference": True,
        "case_count": len(cases),
        "fallback_count": fallback_count,
        "gateway_started_count": gateway_started_count,
        "gateway_tool_call_count": gateway_tool_call_count,
        "valid_real_model_run": (
            args.driver == "gateway"
            and fallback_count == 0
            and gateway_started_count == len(cases)
            and gateway_tool_call_count > 0
        ),
        "metrics": {key: rate(scored, key) for key in ("status", "clarification", "selection", "amount", "policy_block", "evidence")},
        "all_machine_checks": {"passed": sum(row["passed"] for row in scored), "total": len(scored), "rate": sum(row["passed"] for row in scored) / len(scored)},
        "failure_categories": {name: sum(row["failure_category"] == name for row in scored) for name in sorted({row["failure_category"] for row in scored if row["failure_category"]})},
        "cases": scored,
    }
    metrics.update(git_state())
    (out / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        f"# Formal evaluation — {run_id}", "",
        f"- Driver: `{args.driver}`", f"- Model: `{args.model_id or 'none'}`",
        f"- Valid real-model run: **{metrics['valid_real_model_run']}**", f"- Fallbacks: **{fallback_count}**", "",
        "## Metrics", "", "| Metric | Passed | Total | Rate |", "|---|---:|---:|---:|",
    ]
    for key, value in metrics["metrics"].items():
        shown = "n/a" if value["rate"] is None else f"{value['rate']:.1%}"
        lines.append(f"| {key} | {value['passed']} | {value['total']} | {shown} |")
    lines += ["", "## Failures", ""]
    failures = [row for row in scored if not row["passed"]]
    lines += [f"- `{row['case_id']}`: {', '.join(row['failed_checks'])} ({row['failure_category']})" for row in failures] or ["- None"]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out.relative_to(ROOT))
    return 0 if (args.driver == "offline" or metrics["valid_real_model_run"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
