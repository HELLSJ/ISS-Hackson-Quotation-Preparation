"""Report whether every A-role evidence gate has authoritative passing evidence."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports/evaluation/a-completion-status.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def latest(pattern: str) -> Path | None:
    matches = sorted(ROOT.glob(pattern))
    return matches[-1] if matches else None


def signed_csv(path: Path, expected_rows: int) -> tuple[bool, str]:
    if not path.is_file():
        return False, "missing"
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    passed = [
        row for row in rows
        if row.get("review_status") == "PASS" and row.get("reviewer") and row.get("reviewed_at")
    ]
    return len(rows) == expected_rows and len(passed) == expected_rows, f"{len(passed)}/{expected_rows} signed PASS"


def main() -> int:
    freeze = read_json(ROOT / "reports/evaluation/freeze-manifest.json")
    sealed = read_json(ROOT / "reports/evaluation/sealed-holdout-manifest.json")
    browser_path = latest("reports/evaluation/browser_acceptance/*/result.json")
    formal_path = latest("reports/evaluation/runs/*-converse-first-pass/metrics.json")
    timing_path = latest("reports/evaluation/timing/*-converse-first-pass/summary.json")
    pdf_signed, pdf_detail = signed_csv(
        ROOT / "reports/evaluation/pdf-template-review.csv", 8
    )

    browser = read_json(browser_path) if browser_path else {}
    formal = read_json(formal_path) if formal_path else {}
    timing = read_json(timing_path) if timing_path else {}
    gates = {
        "data_freeze": {
            "passed": freeze.get("status") == "FROZEN_INDEPENDENT_HUMAN_REVIEW_PASSED",
            "evidence": "reports/evaluation/freeze-manifest.json",
        },
        "sealed_non_author_review": {
            "passed": sealed.get("status") == "SEALED_REVIEW_PASSED",
            "evidence": "reports/evaluation/sealed-holdout-manifest.json",
        },
        "real_model_first_pass": {
            "passed": bool(formal.get("valid_real_model_run")),
            "evidence": str(formal_path.relative_to(ROOT)) if formal_path else "missing",
        },
        "formal_metrics": {
            "passed": bool(formal.get("metrics")) and formal.get("case_count") == 20,
            "evidence": str(formal_path.relative_to(ROOT)) if formal_path else "missing",
        },
        "browser_acceptance": {
            "passed": bool(browser.get("passed")),
            "evidence": str(browser_path.relative_to(ROOT)) if browser_path else "missing",
        },
        "pdf_independent_review": {
            "passed": pdf_signed,
            "evidence": f"reports/evaluation/pdf-template-review.csv ({pdf_detail})",
        },
        "five_case_efficiency": {
            "passed": bool(timing.get("comparison_complete")),
            "evidence": str(timing_path.relative_to(ROOT)) if timing_path else "missing",
        },
    }
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "complete": all(gate["passed"] for gate in gates.values()),
        "gates": gates,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
