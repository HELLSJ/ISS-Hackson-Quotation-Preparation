"""Gateway driver integration and failure-path checks."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from dell_agent.agent.loop import GatewayClient, GatewayDriver, OfflineDriver
from dell_agent.data.catalog import all_products


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
    def test_follow_up_refinement_keeps_prior_one_cable_constraints(self) -> None:
        result = OfflineDriver().run([
            "We need around 8 monitors for one-cable USB-C video and charging. Budget SGD 2500.",
            "Exactly 8. We need at least 90W charging; a 24-inch FHD screen is fine.",
        ])
        self.assertEqual(result.status, "needs_clarification")
        self.assertEqual([row["model"] for row in result.candidates], ["P2425HE", "T24D-4v", "T24D-40"])
        self.assertTrue(all(row["usb_c_video"] for row in result.candidates))
        self.assertTrue(all(row["usb_c_pd_watts"] >= 90 for row in result.candidates))
        self.assertTrue(all(row["resolution"] == "1920x1080" for row in result.candidates))
        search = [step for step in result.trace if step.get("tool") == "search_products"][-1]
        self.assertEqual(search["args"]["min_screen_inches"], 23.4)
        self.assertEqual(search["args"]["max_screen_inches"], 24.5)

    def test_model_generation_suffix_is_never_used_as_quantity(self) -> None:
        driver = OfflineDriver()
        for product in all_products():
            with self.subTest(model=product.model):
                result = driver.run(f"Choose {product.model} at zero discount.")
                self.assertEqual(result.status, "needs_clarification")
                self.assertEqual(result.ask_for, ["quantity"])
                self.assertIsNone(result.quote_draft)

    def test_explicit_single_sku_selection_quotes_exactly_one(self) -> None:
        driver = OfflineDriver()
        for product in all_products():
            with self.subTest(sku=product.sku):
                # A prior quantity must not leak into a later product-card
                # selection: every click emits an explicit quantity of one.
                result = driver.run([
                    "Quote 8 P2425HE at zero discount.",
                    f"Quote 1 {product.sku} at zero discount.",
                ])
                self.assertEqual(result.status, "ready_to_quote")
                self.assertEqual(result.quote_draft["lines"][0]["sku"], product.sku)
                self.assertEqual(result.quote_draft["lines"][0]["quantity"], 1)
                self.assertEqual(
                    result.quote_draft["total_cents"],
                    product.unit_price_cents,
                )

    def test_empty_turn_sequence_requests_missing_details_instead_of_crashing(self) -> None:
        result = OfflineDriver().run([])
        self.assertEqual(result.status, "needs_clarification")
        self.assertEqual(result.ask_for, ["product_specification_or_model"])

    def test_quantity_revisions_preserve_invalid_values_for_rejection(self) -> None:
        for revision in (
            "Change that to -3 units.",
            "Change that to negative three units.",
            "Change that to 2.5 units.",
        ):
            with self.subTest(revision=revision):
                result = OfflineDriver().run(["Quote 2 P2425HE.", revision])
                self.assertEqual(result.status, "invalid_quantity")
                self.assertIsNone(result.quote_draft)

    def test_symbolic_negative_initial_quantity_is_not_made_positive(self) -> None:
        for prompt in ("Quote -3 P2425HE.", "We need -3 monitors."):
            with self.subTest(prompt=prompt):
                result = OfflineDriver().run(prompt)
                self.assertEqual(result.status, "invalid_quantity")
                self.assertIsNone(result.quote_draft)

    def test_discount_can_be_revised_in_both_directions(self) -> None:
        driver = OfflineDriver()
        discounted = driver.run(["Quote 2 P2425HE at zero discount.", "Apply a 5% discount."])
        cleared = driver.run(["Quote 2 P2425HE at 5% discount.", "Apply zero discount."])
        self.assertEqual(discounted.quote_draft["lines"][0]["discount_bps"], 500)
        self.assertEqual(cleared.quote_draft["lines"][0]["discount_bps"], 0)

    def test_prior_turn_requirements_block_an_incompatible_later_selection(self) -> None:
        result = OfflineDriver().run([
            "We need 4 monitors for one-cable laptop video and 90W charging.",
            "Choose U2724D at zero discount.",
        ])
        self.assertEqual(result.status, "explain_limitation")
        self.assertIsNone(result.quote_draft)
        self.assertEqual([row["sku"] for row in result.candidates], ["MON-010"])

    def test_add_revision_preserves_existing_lines(self) -> None:
        result = OfflineDriver().run([
            "Quote one S2425H and two U2724DE monitors.",
            "Also add 3 P2425HE monitors.",
        ])
        self.assertEqual(result.status, "ready_to_quote")
        self.assertEqual(
            [(line["sku"], line["quantity"]) for line in result.quote_draft["lines"]],
            [("MON-001", 1), ("MON-011", 2), ("MON-007", 3)],
        )

    def test_added_line_without_quantity_requires_clarification(self) -> None:
        result = OfflineDriver().run([
            "Quote one S2425H monitor.",
            "Also add P2425HE.",
        ])
        self.assertEqual(result.status, "needs_clarification")
        self.assertEqual(result.ask_for, ["quantity"])
        self.assertIsNone(result.quote_draft)

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

    def test_gateway_cannot_invent_quantity_from_resolution(self) -> None:
        client = _SequenceClient([
            {"message": {"content": "", "tool_calls": [{
                "id": "call-1", "type": "function", "function": {
                    "name": "calculate_quote",
                    "arguments": {"items": [{"sku": "MON-001", "quantity": 1920}]},
                },
            }]}},
            {"message": {"content": json.dumps({
                "status": "ready_to_quote", "ask_for": [],
                "message": "The draft is ready.",
            }), "tool_calls": []}},
        ])
        result = GatewayDriver(
            base_url="https://gateway.example", api_key="secret", model="test-model", client=client
        ).run(["I need a 1920x1080 monitor.", "Choose S2425H at zero discount."])

        self.assertEqual(result.status, "needs_clarification")
        self.assertEqual(result.ask_for, ["quantity"])
        self.assertIsNone(result.quote_draft)
        self.assertTrue(any(
            row.get("tool") == "calculate_quote" and row.get("result") == "quote_not_ready"
            for row in result.trace
        ))

    def test_gateway_wrong_quantity_is_corrected_from_customer_turns(self) -> None:
        client = _SequenceClient([
            {"message": {"content": "", "tool_calls": [{
                "id": "call-1", "type": "function", "function": {
                    "name": "calculate_quote",
                    "arguments": {"items": [{"sku": "MON-001", "quantity": 1920}]},
                },
            }]}},
            {"message": {"content": json.dumps({
                "status": "ready_to_quote", "ask_for": [],
                "message": "The draft is ready.",
            }), "tool_calls": []}},
        ])
        result = GatewayDriver(
            base_url="https://gateway.example", api_key="secret", model="test-model", client=client
        ).run(["We need 8 monitors at 1920x1080.", "Choose S2425H at zero discount."])

        self.assertEqual(result.status, "ready_to_quote")
        self.assertEqual(result.quote_draft["lines"][0]["quantity"], 8)
        self.assertEqual(result.quote_draft["total_cents"], 119200)
        corrected = next(
            row for row in result.trace
            if row.get("tool") == "calculate_quote"
            and row.get("result") == "arguments_corrected_by_local_state"
        )
        self.assertEqual(corrected["requested_args"]["items"][0]["quantity"], 1920)
        self.assertEqual(corrected["args"]["items"][0]["quantity"], 8)

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

    def test_local_quote_repair_clears_stale_model_clarification(self) -> None:
        client = _SequenceClient([
            {"message": {"content": "", "tool_calls": [{
                "id": "call-1", "type": "function", "function": {
                    "name": "get_product", "arguments": {"sku": "MON-L044"},
                },
            }]}},
            {"message": {"content": json.dumps({
                "status": "needs_clarification",
                "ask_for": ["quantity"],
                "message": "Please provide quantity.",
            }), "tool_calls": []}},
        ])
        result = GatewayDriver(
            base_url="https://gateway.example", api_key="secret",
            model="test-model", client=client,
        ).run("Quote 1 MON-L044 at zero discount.")
        self.assertEqual(result.status, "ready_to_quote")
        self.assertEqual(result.ask_for, [])
        self.assertEqual(result.quote_draft["lines"][0]["quantity"], 1)

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

    def test_same_capability_question_remains_evidence_comparison(self) -> None:
        client = _SequenceClient([
            {"message": {"content": "", "tool_calls": [{
                "id": "call-1", "type": "function", "function": {
                    "name": "get_product", "arguments": {"sku": "MON-005"},
                },
            }, {
                "id": "call-2", "type": "function", "function": {
                    "name": "get_product", "arguments": {"sku": "MON-008"},
                },
            }]}},
            {"message": {"content": json.dumps({
                "status": "answer_with_evidence", "ask_for": [],
                "message": "Their USB-C video capabilities differ.",
            }), "tool_calls": []}},
        ])
        result = GatewayDriver(
            base_url="https://gateway.example", api_key="secret",
            model="test-model", client=client,
        ).run("Do P2425 and P2425E have the same USB-C video capability?")
        self.assertEqual(result.status, "answer_with_evidence")
        self.assertFalse(any(row.get("step") == "local_policy_guard" for row in result.trace))

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
