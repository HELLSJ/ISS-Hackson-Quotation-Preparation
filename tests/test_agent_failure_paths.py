"""Failure-path checks needed by the formal acceptance matrix."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from dell_agent.agent.loop import ConverseDriver


class _TimeoutClient:
    def converse(self, **_: object) -> dict:
        raise TimeoutError("injected Bedrock timeout")


class AgentFailurePathTests(unittest.TestCase):
    def test_bedrock_timeout_is_visible_and_falls_back_without_losing_quote(self) -> None:
        with patch("boto3.client", return_value=_TimeoutClient()):
            result = ConverseDriver(model_id="test-model", region="us-east-1").run(
                "Quote 8 P2425HE. Budget SGD 2500."
            )
        self.assertEqual(result.status, "ready_to_quote")
        self.assertEqual(result.quote_draft["total_cents"], 231200)
        self.assertTrue(any("TimeoutError" in note for note in result.notes))
        self.assertEqual(result.trace[-1]["step"], "converse_fallback")


if __name__ == "__main__":
    unittest.main()
