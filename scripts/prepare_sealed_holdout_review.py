"""Prepare hashes and a non-author review sheet for the sealed holdout."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "data/evaluation/sealed_holdout_enquiries.jsonl"
EXPECTED = ROOT / "reports/evaluation/sealed_holdout_expected.jsonl"
REPORTS = ROOT / "reports/evaluation"


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def digest(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review_summary(review_path: Path, inputs: list[dict], expected: dict[str, dict]) -> dict:
    with review_path.open(newline="", encoding="utf-8") as stream:
        review = list(csv.DictReader(stream))
    by_id = {row["case_id"]: row for row in review}
    expected_ids = {row["case_id"] for row in inputs}
    valid_hashes = len(review) == len(expected_ids) and set(by_id) == expected_ids
    for item in inputs:
        row = by_id.get(item["case_id"], {})
        valid_hashes = valid_hashes and row.get("prompt_sha256") == digest(item["user_turns"])
        valid_hashes = valid_hashes and row.get("expected_sha256") == digest(expected[item["case_id"]])
    passed = [
        row for row in review
        if row.get("review_status") == "PASS" and row.get("reviewer") and row.get("reviewed_at")
    ]
    return {
        "complete": bool(valid_hashes and len(passed) == len(expected_ids)),
        "valid_hashes": bool(valid_hashes),
        "passed_rows": len(passed),
        "total_rows": len(expected_ids),
        "reviewers": sorted({row["reviewer"] for row in passed}),
        "reviewed_at": sorted({row["reviewed_at"] for row in passed}),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--finalize", action="store_true",
        help="seal the manifest only when all 20 non-author review rows are signed PASS",
    )
    args = parser.parse_args()
    inputs = load(INPUTS)
    expected = {row["case_id"]: row["expected"] for row in load(EXPECTED)}
    if {row["case_id"] for row in inputs} != set(expected):
        raise SystemExit("sealed input and answer IDs do not match")
    review = REPORTS / "sealed-holdout-review.csv"
    if not review.exists():
        rows = [
            {
                "case_id": row["case_id"], "category": row["category"],
                "expected_status": expected[row["case_id"]]["status"],
                "prompt_sha256": digest(row["user_turns"]),
                "expected_sha256": digest(expected[row["case_id"]]),
                "review_status": "PENDING_INDEPENDENT_REVIEW", "reviewer": "", "reviewed_at": "",
                "review_note": "Confirm the enquiry is unambiguous and the expected outcome follows the frozen catalogue and rules.",
            }
            for row in inputs
        ]
        with review.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader(); writer.writerows(rows)
    summary = review_summary(review, inputs, expected)
    if args.finalize and not summary["complete"]:
        raise SystemExit(
            "cannot finalize: review must contain 20 matching rows signed PASS with reviewer and date"
        )
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "SEALED_REVIEW_PASSED" if args.finalize else "SEALED_READY_PENDING_INDEPENDENT_REVIEW",
        "case_count": len(inputs),
        "dataset_version": inputs[0]["dataset_version"],
        "inputs": str(INPUTS.relative_to(ROOT)), "inputs_sha256": file_digest(INPUTS),
        "answer_key": str(EXPECTED.relative_to(ROOT)), "answer_key_sha256": file_digest(EXPECTED),
        "review_sheet": str(review.relative_to(ROOT)),
        "review_sheet_sha256": file_digest(review),
        "inference_isolation": "run_formal_evaluation.py writes all raw model results before opening the answer key",
        "runtime_prompt_access": "Neither sealed file is imported by the application, Agent prompt, catalogue, or ordinary regression tests.",
    }
    if args.finalize:
        manifest["independent_review"] = {"result": "PASS", **summary}
    (REPORTS / "sealed-holdout-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
