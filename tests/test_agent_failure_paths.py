"""Gateway driver integration and failure-path checks."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from dell_agent.agent.loop import GatewayClient, GatewayDriver


class _SequenceClient:
    protocol = "injected"

    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.messages: list[list[dict]] = []

    def chat(self, messages: list[dict], _tools: list[dict]) -> dict:
        self.messages.append(list(messages))
        return self.responses.pop(0)


class _OpenAISequenceClient(_SequenceClient):
    protocol = "openai"


class _TimeoutClient:
    protocol = "injected"

    def chat(self, _messages: list[dict], _tools: list[dict]) -> dict:
        raise TimeoutError("injected gateway timeout")


class _Response:
    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.payload


class AgentFailurePathTests(unittest.TestCase):
    def test_gateway_timeout_is_visible_and_falls_back_without_losing_quote(self) -> None:
        result = GatewayDriver(
            base_url="https://gateway.example", api_key="secret", model="test-model",
            client=_TimeoutClient(),
        ).run("Quote 8 P2425HE. Budget SGD 2500.")
        self.assertEqual(result.status, "ready_to_quote")
        self.assertEqual(result.quote_draft["total_cents"], 231200)
        self.assertTrue(any("TimeoutError" in note for note in result.notes))
        self.assertEqual(result.trace[-1]["step"], "gateway_fallback")
        self.assertNotIn("secret", json.dumps(result.to_dict()))

    def test_missing_gateway_configuration_falls_back(self) -> None:
        result = GatewayDriver().run("Quote 1 S2425H.")
        self.assertEqual(result.status, "ready_to_quote")
        self.assertEqual(result.trace[-1]["step"], "gateway_fallback")

    def test_native_tool_call_uses_local_pricing(self) -> None:
        client = _SequenceClient([
            {"message": {"content": "", "tool_calls": [{
                "id": "call-1", "type": "function", "function": {
                    "name": "calculate_quote",
                    "arguments": {"items": [{"sku": "MON-007", "quantity": 8}]},
                },
            }]}},
            {"message": {"content": "The draft is ready.", "tool_calls": []}},
        ])
        result = GatewayDriver(
            base_url="https://gateway.example", api_key="secret", model="test-model", client=client
        ).run("Quote 8 P2425HE.")
        self.assertEqual(result.status, "ready_to_quote")
        self.assertEqual(result.quote_draft["total_cents"], 231200)
        self.assertTrue(any(row.get("role") == "tool" for row in client.messages[-1]))

    def test_openai_transcript_serializes_tool_arguments(self) -> None:
        client = _OpenAISequenceClient([
            {"message": {"content": "", "tool_calls": [{
                "id": "call-1", "type": "function", "function": {
                    "name": "calculate_quote",
                    "arguments": {"items": [{"sku": "MON-001", "quantity": 1}]},
                },
            }]}},
            {"message": {"content": "Done.", "tool_calls": []}},
        ])
        GatewayDriver(
            base_url="https://gateway.example/v1", api_key="secret",
            model="test-model", client=client,
        ).run("Quote 1 S2425H.")
        second_request = client.messages[-1]
        assistant = next(row for row in second_request if row.get("tool_calls"))
        tool_result = next(row for row in second_request if row.get("role") == "tool")
        self.assertIsInstance(assistant["tool_calls"][0]["function"]["arguments"], str)
        self.assertEqual(tool_result["tool_call_id"], "call-1")

    def test_manual_json_tool_call_is_supported(self) -> None:
        client = _SequenceClient([
            {"message": {"content": '{"tool":"calculate_quote","args":{"items":[{"sku":"MON-001","quantity":2}]}}', "tool_calls": []}},
            {"message": {"content": "Done.", "tool_calls": []}},
        ])
        result = GatewayDriver(
            base_url="https://gateway.example", api_key="secret", model="test-model", client=client
        ).run("Quote 2 S2425H.")
        self.assertEqual(result.status, "ready_to_quote")
        self.assertEqual(result.quote_draft["total_cents"], 29800)

    def test_structured_clarification_populates_ask_for(self) -> None:
        client = _SequenceClient([{"message": {
            "content": json.dumps({
                "status": "needs_clarification",
                "ask_for": ["quantity"],
                "message": "How many monitors should the quotation include?",
            }),
            "tool_calls": [],
        }}])
        result = GatewayDriver(
            base_url="https://gateway.example", api_key="secret",
            model="test-model", client=client,
        ).run("Quote P2425HE.")
        self.assertEqual(result.status, "needs_clarification")
        self.assertEqual(result.ask_for, ["quantity"])
        self.assertIn("How many monitors", result.notes[-1])

    def test_evidence_tool_can_resolve_to_limitation_status(self) -> None:
        client = _SequenceClient([
            {"message": {"content": "", "tool_calls": [{
                "id": "call-1", "type": "function", "function": {
                    "name": "get_product", "arguments": {"sku": "MON-010"},
                },
            }]}},
            {"message": {"content": json.dumps({
                "status": "explain_limitation", "ask_for": [],
                "message": "U2724D USB-C is data-only.",
            }), "tool_calls": []}},
        ])
        result = GatewayDriver(
            base_url="https://gateway.example", api_key="secret",
            model="test-model", client=client,
        ).run("Can U2724D carry laptop video and power?")
        self.assertEqual(result.status, "explain_limitation")
        self.assertTrue(result.citations)

    def test_budget_conflict_keeps_tool_quote_and_status(self) -> None:
        client = _SequenceClient([
            {"message": {"content": "", "tool_calls": [{
                "id": "call-1", "type": "function", "function": {
                    "name": "calculate_quote", "arguments": {
                        "items": [{"sku": "MON-009", "quantity": 9}],
                        "budget_cents": 300000,
                    },
                },
            }]}},
            {"message": {"content": json.dumps({
                "status": "budget_conflict", "ask_for": [],
                "message": "The requested quote exceeds budget.",
            }), "tool_calls": []}},
        ])
        result = GatewayDriver(
            base_url="https://gateway.example", api_key="secret",
            model="test-model", client=client,
        ).run("Quote nine P2725HE against SGD 3000.")
        self.assertEqual(result.status, "budget_conflict")
        self.assertEqual(result.quote_draft["over_budget_cents"], 14100)

    def test_multiple_product_evidence_is_accumulated(self) -> None:
        client = _SequenceClient([
            {"message": {"content": "", "tool_calls": [
                {"id": "call-1", "type": "function", "function": {
                    "name": "get_product", "arguments": {"sku": "MON-005"},
                }},
                {"id": "call-2", "type": "function", "function": {
                    "name": "get_product", "arguments": {"sku": "MON-008"},
                }},
            ]}},
            {"message": {"content": json.dumps({
                "status": "answer_with_evidence", "ask_for": [],
                "message": "The models have different USB-C video capability.",
            }), "tool_calls": []}},
        ])
        result = GatewayDriver(
            base_url="https://gateway.example", api_key="secret",
            model="test-model", client=client,
        ).run("Compare P2425 and P2425E USB-C video.")
        self.assertEqual(result.status, "answer_with_evidence")
        self.assertEqual({row["sku"] for row in result.candidates}, {"MON-005", "MON-008"})
        self.assertEqual({row["sku"] for row in result.citations}, {"MON-005", "MON-008"})

    def test_named_product_final_answer_without_tool_is_retried(self) -> None:
        client = _SequenceClient([
            {"message": {"content": json.dumps({
                "status": "explain_limitation", "ask_for": [],
                "message": "The product cannot meet the requirement.",
            }), "tool_calls": []}},
            {"message": {"content": "", "tool_calls": [{
                "id": "call-1", "type": "function", "function": {
                    "name": "get_product", "arguments": {"sku": "MON-010"},
                },
            }]}},
            {"message": {"content": json.dumps({
                "status": "explain_limitation", "ask_for": [],
                "message": "U2724D cannot meet the one-cable requirement.",
            }), "tool_calls": []}},
        ])
        result = GatewayDriver(
            base_url="https://gateway.example", api_key="secret",
            model="test-model", client=client,
        ).run("Can U2724D provide one-cable video and 90W charging?")
        self.assertEqual(result.status, "explain_limitation")
        self.assertTrue(result.citations)
        self.assertTrue(any(row.get("result") == "tool_required_retry" for row in result.trace))

    def test_local_policy_guard_overrides_model_clarification(self) -> None:
        client = _SequenceClient([
            {"message": {"content": "", "tool_calls": [{
                "id": "call-1", "type": "function", "function": {
                    "name": "get_product", "arguments": {"sku": "MON-010"},
                },
            }]}},
            {"message": {"content": json.dumps({
                "status": "needs_clarification",
                "ask_for": ["product_specification_or_model"],
                "message": "Would you like a different model?",
            }), "tool_calls": []}},
        ])
        result = GatewayDriver(
            base_url="https://gateway.example", api_key="secret",
            model="test-model", client=client,
        ).run("Quote 4 U2724D for one-cable laptop video and 90W charging.")
        self.assertEqual(result.status, "explain_limitation")
        self.assertIsNone(result.quote_draft)
        self.assertTrue(any(row.get("step") == "local_policy_guard" for row in result.trace))

    def test_complete_multi_product_order_repairs_missing_quote_tool(self) -> None:
        client = _SequenceClient([
            {"message": {"content": "", "tool_calls": [{
                "id": "call-1", "type": "function", "function": {
                    "name": "get_product", "arguments": {"sku": "MON-001"},
                },
            }, {
                "id": "call-2", "type": "function", "function": {
                    "name": "get_product", "arguments": {"sku": "MON-011"},
                },
            }]}},
            {"message": {"content": json.dumps({
                "status": "answer_with_evidence", "ask_for": [],
                "message": "The selected products are available in the catalogue.",
            }), "tool_calls": []}},
        ])
        result = GatewayDriver(
            base_url="https://gateway.example", api_key="secret",
            model="test-model", client=client,
        ).run("Our order needs one S2425H and two U2724DE monitors.")
        self.assertEqual(result.status, "ready_to_quote")
        self.assertEqual(result.quote_draft["total_cents"], 140700)
        self.assertTrue(any(row.get("step") == "gateway_local_tool_repair" for row in result.trace))

    def test_budget_conflict_is_owned_by_local_quote(self) -> None:
        client = _SequenceClient([
            {"message": {"content": "", "tool_calls": [{
                "id": "call-1", "type": "function", "function": {
                    "name": "calculate_quote", "arguments": {
                        "items": [{"sku": "MON-009", "quantity": 9}],
                        "budget_cents": 300000,
                    },
                },
            }]}},
            {"message": {"content": json.dumps({
                "status": "ready_to_quote", "ask_for": [], "message": "Draft ready.",
            }), "tool_calls": []}},
        ])
        result = GatewayDriver(
            base_url="https://gateway.example", api_key="secret",
            model="test-model", client=client,
        ).run("We need nine P2725HE monitors with no discount and cannot exceed SGD 3,000.")
        self.assertEqual(result.status, "budget_conflict")
        self.assertEqual(result.quote_draft["over_budget_cents"], 14100)

    def test_word_discount_and_negative_word_quantity_use_hard_guards(self) -> None:
        for prompt, expected in (
            ("Apply a seven percent discount to five S2725QC monitors.", "rule_violation"),
            ("Quote negative three P2425E displays.", "invalid_quantity"),
        ):
            with self.subTest(prompt=prompt):
                client = _SequenceClient([{"message": {"content": json.dumps({
                    "status": "needs_clarification", "ask_for": ["quantity"],
                    "message": "Please clarify.",
                }), "tool_calls": []}}])
                result = GatewayDriver(
                    base_url="https://gateway.example", api_key="secret",
                    model="test-model", client=client,
                ).run(prompt)
                self.assertEqual(result.status, expected)
                self.assertIsNone(result.quote_draft)

    def test_ollama_client_uses_gateway_header_and_endpoint(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["key"] = request.get_header("X-api-key")
            captured["timeout"] = timeout
            return _Response({"message": {"content": "ok", "tool_calls": []}})

        client = GatewayClient("https://gateway.example", "team-key", "model", timeout=7)
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            response = client.chat([{"role": "user", "content": "hi"}], [])
        self.assertEqual(captured, {"url": "https://gateway.example/api/chat", "key": "team-key", "timeout": 7})
        self.assertEqual(response["message"]["content"], "ok")

    def test_gateway_transport_retries_once(self) -> None:
        client = GatewayClient(
            "https://gateway.example", "team-key", "model",
            max_retries=1, retry_delay=0,
        )
        outcomes = [
            TimeoutError("first request timed out"),
            _Response({"message": {"content": "ok", "tool_calls": []}}),
        ]
        with patch("urllib.request.urlopen", side_effect=outcomes) as request:
            response = client.chat([{"role": "user", "content": "hi"}], [])
        self.assertEqual(request.call_count, 2)
        self.assertEqual(response["message"]["content"], "ok")

    def test_openai_client_uses_v1_endpoint_and_normalizes_arguments(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["authorization"] = request.get_header("Authorization")
            captured["key"] = request.get_header("X-api-key")
            return _Response({"choices": [{"message": {
                "content": None,
                "tool_calls": [{"id": "call-1", "type": "function", "function": {
                    "name": "get_product", "arguments": '{"sku":"MON-001"}',
                }}],
            }}]})

        client = GatewayClient("https://gateway.example/v1", "team-key", "model")
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            response = client.chat([{"role": "user", "content": "hi"}], [])
        self.assertEqual(captured["url"], "https://gateway.example/v1/chat/completions")
        self.assertEqual(captured["authorization"], "Bearer team-key")
        self.assertEqual(captured["key"], "team-key")
        self.assertEqual(
            response["message"]["tool_calls"][0]["function"]["arguments"],
            {"sku": "MON-001"},
        )


if __name__ == "__main__":
    unittest.main()
