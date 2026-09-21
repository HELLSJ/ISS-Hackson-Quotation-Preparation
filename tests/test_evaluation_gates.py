from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import prepare_sealed_holdout_review as prepare
from scripts import run_efficiency_timing as timing
from scripts import run_formal_evaluation as formal


class EvaluationGateTests(unittest.TestCase):
    def test_fallback_detection_uses_trace_marker(self):
        fallback = {"trace": [{"step": "gateway_fallback", "result": "failure"}], "notes": []}
        ordinary = {"trace": [], "notes": ["offline driver text is not a trace marker"]}
        self.assertTrue(formal.has_fallback(fallback))
        self.assertTrue(timing.has_fallback(fallback))
        self.assertFalse(formal.has_fallback(ordinary))
        self.assertFalse(timing.has_fallback(ordinary))
        real_trace = {
            "trace": [
                {"step": "gateway_start", "result": {"model": "test"}},
                {"step": "gateway_turn_0", "tool": "calculate_quote", "result": "ok"},
            ]
        }
        self.assertEqual(formal.gateway_trace_counts(real_trace), (True, 1))
        self.assertEqual(timing.gateway_trace_counts(real_trace), (True, 1))

    def test_gateway_preflight_rejects_pending_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "inputs.jsonl"
            manifest = root / "manifest.json"
            inputs.write_text("sealed input\n", encoding="utf-8")
            manifest.write_text(
                json.dumps(
                    {
                        "case_count": 20,
                        "status": "SEALED_READY_PENDING_INDEPENDENT_REVIEW",
                        "inputs_sha256": hashlib.sha256(inputs.read_bytes()).hexdigest(),
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(formal, "SEALED_INPUTS", inputs), patch.object(
                formal, "SEALED_MANIFEST", manifest
            ):
                with self.assertRaises(SystemExit):
                    formal.verify_manifest(require_review=True)

    def test_review_summary_requires_signed_matching_rows(self):
        inputs = [{"case_id": "SEALED-001", "user_turns": ["quote one"]}]
        expected = {"SEALED-001": {"status": "ready_to_quote"}}
        with tempfile.TemporaryDirectory() as directory:
            review = Path(directory) / "review.csv"
            fields = [
                "case_id", "prompt_sha256", "expected_sha256", "review_status",
                "reviewer", "reviewed_at",
            ]
            with review.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerow(
                    {
                        "case_id": "SEALED-001",
                        "prompt_sha256": prepare.digest(inputs[0]["user_turns"]),
                        "expected_sha256": prepare.digest(expected["SEALED-001"]),
                        "review_status": "PASS",
                        "reviewer": "Independent Reviewer",
                        "reviewed_at": "2026-09-21",
                    }
                )
            summary = prepare.review_summary(review, inputs, expected)
            self.assertTrue(summary["complete"])

    def test_manual_comparison_requires_all_correct_signed_rows(self):
        rows = [
            {
                "case_id": case_id,
                "operator": "Reviewer",
                "started_at": "2026-09-21T00:00:00+00:00",
                "finished_at": "2026-09-21T00:01:00+00:00",
                "result_check": "PASS",
            }
            for case_id in sorted(timing.CASE_IDS)
        ]
        self.assertTrue(timing.manual_is_complete(rows))
        rows[-1]["result_check"] = "FAIL"
        self.assertFalse(timing.manual_is_complete(rows))


if __name__ == "__main__":
    unittest.main()
