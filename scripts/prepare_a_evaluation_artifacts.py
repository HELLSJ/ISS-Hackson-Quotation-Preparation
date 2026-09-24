"""Generate non-model A (data and evaluation) review artifacts.

This script never changes source data or expected fixtures. It creates review
workbooks under ``reports/evaluation`` and intentionally marks human decisions
as pending. Run it again after changing a frozen input to refresh hashes and
machine-generated rows.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports" / "evaluation"

# Twelve Lenovo expansion SKUs span the size, resolution, refresh and USB-C/PD
# boundaries. Each receives the two highest-risk port-direction fields, for 24
# independent review points. The original Dell baseline review remains preserved.
FREEZE_SAMPLE = {
    sku: ("usb_c_video", "usb_c_pd_watts")
    for sku in (
        "MON-L013", "MON-L014", "MON-L018", "MON-L019", "MON-L020", "MON-L023",
        "MON-L031", "MON-L034", "MON-L040", "MON-L042", "MON-L043", "MON-L044",
    )
}

KNOWN_OFFLINE_LIMITATIONS = {
    "DEV-015": "Unknown model token is classified as needs_clarification instead of no_match.",
    "HOLDOUT-008": "Strict 24.0-inch diagonal limitation is not detected.",
    "HOLDOUT-009": "Host-vs-downstream 90 W nuance is not detected.",
    "HOLDOUT-011": "Cable-vs-port 100 W nuance is not detected.",
    "HOLDOUT-013": "The composite 8K/exact-size/200 Hz constraint is not fully classified by the offline heuristic.",
    "HOLDOUT-014": "Named-SKU over-budget request is quoted rather than classified as budget_conflict.",
    "HOLDOUT-015": "Unknown model token is classified as needs_clarification instead of no_match.",
}

MACHINE_ASSERTED_FIELDS = {
    "status",
    "items",
    "total_cents",
    "within_budget",
    "over_budget_cents",
    "ask_for",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def as_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def calculate_total_cents(items: list[dict[str, Any]], prices: dict[str, int]) -> int:
    total = 0
    for item in items:
        price = prices[item["sku"]]
        quantity = int(item["quantity"])
        discount_bps = int(item.get("discount_bps", 0))
        gross = price * quantity
        discount = int(
            (Decimal(gross) * Decimal(discount_bps) / Decimal(10_000)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        total += gross - discount
    return total


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()

    curated_path = ROOT / "data" / "curated_specs.json"
    business_path = ROOT / "data" / "synthetic_business.json"
    evidence_path = ROOT / "data" / "processed" / "field_evidence.csv"
    prices_path = ROOT / "data" / "processed" / "prices.csv"
    rules_path = ROOT / "data" / "processed" / "pricing_rules.json"
    expected_path = ROOT / "data" / "evaluation" / "expected_results.jsonl"
    dev_path = ROOT / "data" / "evaluation" / "enquiries_dev.jsonl"
    holdout_path = ROOT / "data" / "evaluation" / "enquiries_holdout.jsonl"

    curated = load_json(curated_path)
    business = load_json(business_path)
    rules = load_json(rules_path)
    expected_records = load_jsonl(expected_path)
    dev_cases = load_jsonl(dev_path)
    holdout_cases = load_jsonl(holdout_path)
    expected_by_id = {record["case_id"]: record["expected"] for record in expected_records}

    with evidence_path.open(newline="", encoding="utf-8") as stream:
        evidence_rows = list(csv.DictReader(stream))
    evidence_by_key = {(row["sku"], row["field"]): row for row in evidence_rows}

    freeze_rows: list[dict[str, Any]] = []
    for sku, fields in FREEZE_SAMPLE.items():
        for field in fields:
            evidence = evidence_by_key[(sku, field)]
            freeze_rows.append(
                {
                    "dataset_version": curated["dataset_version"],
                    "sku": sku,
                    "field": field,
                    "expected_value": evidence["value"],
                    "source_id": evidence["source_id"],
                    "pdf_page": evidence["pdf_page"],
                    "local_pdf_path": evidence["local_path"],
                    "source_url": evidence["source_url"],
                    "derivation_method": evidence["method"],
                    "source_note": evidence["note"],
                    "machine_precheck": "prepared_from_field_evidence",
                    "independent_human_result": "PENDING",
                    "reviewer": "",
                    "reviewed_at": "",
                    "review_note": "Open the PDF page and verify model scope, value, and port direction.",
                }
            )
    write_csv(
        REPORTS / "data-freeze-review.csv",
        list(freeze_rows[0]),
        freeze_rows,
    )

    hashes = {
        str(path.relative_to(ROOT)): sha256(path)
        for path in (curated_path, business_path, evidence_path, prices_path, rules_path, expected_path, dev_path, holdout_path)
    }
    freeze_manifest = {
        "generated_at": generated_at,
        "status": "MACHINE_PREPARED_PENDING_INDEPENDENT_HUMAN_REVIEW",
        "dataset_version": curated["dataset_version"],
        "price_version": rules["price_version"],
        "rule_version": rules["rule_version"],
        "sample_size": len(freeze_rows),
        "sample_design": "12 Lenovo expansion SKUs x 2 fields = 24 review points, spanning resolution/size/PD boundaries; Dell baseline review remains preserved.",
        "input_sha256": hashes,
        "required_next_action": "An independent human reviewer must complete data-freeze-review.csv before calling this dataset frozen.",
    }
    (REPORTS / "freeze-manifest.json").write_text(
        json.dumps(freeze_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    split_by_id = {case["case_id"]: "dev" for case in dev_cases}
    split_by_id.update({case["case_id"]: "existing_holdout_regression" for case in holdout_cases})
    expected_review_rows: list[dict[str, Any]] = []
    for record in expected_records:
        case_id = record["case_id"]
        expected = record["expected"]
        expected_fields = set(expected)
        semantic_fields = sorted(expected_fields - MACHINE_ASSERTED_FIELDS)
        expected_review_rows.append(
            {
                "case_id": case_id,
                "split": split_by_id[case_id],
                "expected_status": expected["status"],
                "expected_fields": ";".join(sorted(expected_fields)),
                "machine_asserted_fields": ";".join(sorted(expected_fields & MACHINE_ASSERTED_FIELDS)),
                "human_semantic_review_fields": ";".join(semantic_fields),
                "offline_regression_status": "KNOWN_LIMITATION" if case_id in KNOWN_OFFLINE_LIMITATIONS else "MACHINE_RUNNABLE",
                "known_limitation": KNOWN_OFFLINE_LIMITATIONS.get(case_id, ""),
                "review_status": "PENDING_INDEPENDENT_HUMAN_REVIEW",
                "reviewer": "",
                "reviewed_at": "",
                "review_note": "Verify that the expected outcome follows the frozen catalogue and business rules. Existing holdout is exposed in repository tests and is regression-only, not blind evaluation.",
            }
        )
    write_csv(
        REPORTS / "expected-label-review.csv",
        list(expected_review_rows[0]),
        expected_review_rows,
    )

    coverage = {
        "generated_at": generated_at,
        "total_expected_cases": len(expected_records),
        "known_offline_limitations": KNOWN_OFFLINE_LIMITATIONS,
        "machine_asserted_fields": sorted(MACHINE_ASSERTED_FIELDS),
        "human_semantic_fields_by_case": {
            row["case_id"]: row["human_semantic_review_fields"].split(";")
            for row in expected_review_rows
            if row["human_semantic_review_fields"]
        },
        "warning": "Existing holdout cases are loaded by repository tests and must be described as a regression set, not a blind holdout.",
    }
    (REPORTS / "expected-coverage-gap.json").write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    with prices_path.open(newline="", encoding="utf-8") as stream:
        prices = {row["sku"]: int(row["unit_price_cents"]) for row in csv.DictReader(stream)}
    money_rows: list[dict[str, Any]] = []
    for case_id, expected in expected_by_id.items():
        items = expected.get("items")
        if not items:
            continue
        actual_total = calculate_total_cents(items, prices)
        expected_total = expected.get("total_cents")
        money_rows.append(
            {
                "case_id": case_id,
                "items": as_json(items),
                "price_version": rules["price_version"],
                "rule_version": rules["rule_version"],
                "rounding": rules["rounding"],
                "expected_total_cents": expected_total if expected_total is not None else "",
                "independent_decimal_total_cents": actual_total,
                "total_match": str(expected_total == actual_total).lower() if expected_total is not None else "not_applicable",
                "expected_over_budget_cents": expected.get("over_budget_cents", ""),
                "machine_precheck": "PASS" if expected_total in (None, actual_total) else "FAIL",
                "independent_human_result": "PENDING",
                "reviewer": "",
                "reviewed_at": "",
                "review_note": "Recalculate from frozen prices and rules; verify the original enquiry budget before signing off budget status.",
            }
        )
    write_csv(
        REPORTS / "money-reconciliation.csv",
        list(money_rows[0]),
        money_rows,
    )

    summary = {
        "generated_at": generated_at,
        "freeze_review_rows": len(freeze_rows),
        "expected_review_rows": len(expected_review_rows),
        "money_reconciliation_rows": len(money_rows),
        "money_machine_precheck_failures": [row["case_id"] for row in money_rows if row["machine_precheck"] == "FAIL"],
    }
    (REPORTS / "artifact-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
