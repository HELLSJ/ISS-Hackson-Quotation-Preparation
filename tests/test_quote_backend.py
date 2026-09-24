"""Application integration tests for immutable quote lifecycle, diff, and PDF."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfReader

import app.main as main_module
from app.config import load_settings
from app.quote_diff import compare_quotes
from app.quote_pdf import PdfRenderError, render_confirmed_quote
from app.repository import Repository
from app.service import QuotationService
from dell_agent.agent.loop import OfflineDriver


def _agent_result(turns: list[str]) -> dict:
    return OfflineDriver().run(turns).to_dict()


class RepositoryLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Repository(Path(self.temp.name) / "app.sqlite")
        self.conversation = self.repo.create_conversation("offline")
        self.turns: list[str] = []

    def tearDown(self) -> None:
        self.temp.cleanup()

    def add_quote_turn(self, text: str, customer: str = "Example Customer") -> dict:
        self.turns.append(text)
        result = _agent_result(self.turns)
        self.repo.append_exchange(self.conversation["id"], text, "draft ready", result)
        state = self.repo.get_conversation(self.conversation["id"])
        quote, error = self.repo.save_latest_quote(
            self.conversation["id"], state["latest_result_message_id"], customer
        )
        self.assertIsNone(error)
        return quote

    def test_current_schema_snapshot_has_complete_server_metadata(self) -> None:
        quote = self.add_quote_turn("Quote 8 P2425HE. Budget SGD 2500.")
        snapshot = quote["payload"]
        self.assertEqual(quote["snapshot_schema_version"], 2)
        self.assertEqual(quote["status"], "saved_draft")
        self.assertFalse(quote["exportable"])
        self.assertEqual(snapshot["customer"]["display_name"], "Example Customer")
        self.assertEqual(snapshot["pricing_context"]["dataset_version"], "2026-09-22")
        self.assertEqual(snapshot["pricing_context"]["price_version"], "demo-2026-09-22")
        self.assertEqual(snapshot["pricing_context"]["rule_version"], "demo-policy-2026-09-14")
        self.assertEqual(snapshot["source"]["result_message_id"], self.repo.get_conversation(self.conversation["id"])["latest_result_message_id"])
        self.assertEqual(snapshot["validity_days"], 7)
        self.assertNotEqual(snapshot["quote_date"], snapshot["valid_until"])
        self.assertEqual(snapshot["lines"][0]["model"], "P2425HE")
        self.assertEqual(snapshot["total_cents"], 231200)

    def test_save_is_idempotent_and_conflicting_customer_is_rejected(self) -> None:
        quote = self.add_quote_turn("Quote 8 P2425HE.")
        state = self.repo.get_conversation(self.conversation["id"])
        again, error = self.repo.save_latest_quote(
            self.conversation["id"], state["latest_result_message_id"], "Example Customer"
        )
        self.assertIsNone(error)
        self.assertEqual(again["id"], quote["id"])
        conflict, error = self.repo.save_latest_quote(
            self.conversation["id"], state["latest_result_message_id"], "Other Customer"
        )
        self.assertIsNone(conflict)
        self.assertEqual(error, "save_conflict")

    def test_idempotent_save_rejects_adding_customer_metadata_after_the_fact(self) -> None:
        self.turns.append("Quote 8 P2425HE.")
        self.repo.append_exchange(
            self.conversation["id"], self.turns[-1], "draft", _agent_result(self.turns)
        )
        state = self.repo.get_conversation(self.conversation["id"])
        quote, error = self.repo.save_latest_quote(
            self.conversation["id"], state["latest_result_message_id"], None
        )
        self.assertIsNone(error)
        conflict, error = self.repo.save_latest_quote(
            self.conversation["id"], state["latest_result_message_id"], "Late Customer"
        )
        self.assertIsNone(conflict)
        self.assertEqual(error, "save_conflict")
        self.assertIsNone(quote["payload"]["customer"]["display_name"])

    def test_parallel_saves_return_one_version(self) -> None:
        self.turns.append("Quote 8 P2425HE.")
        self.repo.append_exchange(self.conversation["id"], self.turns[-1], "draft", _agent_result(self.turns))
        result_id = self.repo.get_conversation(self.conversation["id"])["latest_result_message_id"]
        def save():
            return self.repo.save_latest_quote(self.conversation["id"], result_id, "Example Customer")
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: save(), range(4)))
        self.assertEqual({quote["id"] for quote, error in results if not error}, {results[0][0]["id"]})
        self.assertEqual(len(self.repo.get_conversation(self.conversation["id"])["quote_versions"]), 1)

    def test_malformed_agent_draft_is_not_persisted(self) -> None:
        result = _agent_result(["Quote 8 P2425HE."])
        result["quote_draft"]["lines"][0]["gross_cents"] += 1
        self.repo.append_exchange(self.conversation["id"], "bad", "bad", result)
        state = self.repo.get_conversation(self.conversation["id"])
        quote, error = self.repo.save_latest_quote(
            self.conversation["id"], state["latest_result_message_id"], "Example Customer"
        )
        self.assertIsNone(quote)
        self.assertEqual(error, "invalid_snapshot")
        self.assertEqual(state["quote_versions"], [])

    def test_confirmation_is_append_only_exactly_idempotent_and_exportable(self) -> None:
        quote = self.add_quote_turn("Quote 8 P2425HE. Budget SGD 2500.")
        original_payload = json.dumps(quote["payload"], sort_keys=True)
        confirmed, error, missing = self.repo.confirm_quote(
            quote["id"], quote["snapshot_token"], "Example Customer", "Sales Admin"
        )
        self.assertIsNone(error)
        self.assertEqual(missing, [])
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertTrue(confirmed["exportable"])
        self.assertEqual(confirmed["confirmation"]["snapshot"]["total_cents"], 231200)
        self.assertEqual(json.dumps(confirmed["payload"], sort_keys=True), original_payload)
        retry, error, _ = self.repo.confirm_quote(
            quote["id"], quote["snapshot_token"], "Example Customer", "Sales Admin"
        )
        self.assertIsNone(error)
        self.assertEqual(retry["confirmation"]["id"], confirmed["confirmation"]["id"])
        changed, error, _ = self.repo.confirm_quote(
            quote["id"], quote["snapshot_token"], "Other Customer", "Sales Admin"
        )
        self.assertIsNone(changed)
        self.assertEqual(error, "already_confirmed")

    def test_old_unconfirmed_version_and_wrong_token_are_rejected(self) -> None:
        first_quote = self.add_quote_turn("Quote 8 P2425HE. Budget SGD 2500.")
        second_quote = self.add_quote_turn("Change quantity to 10 units.")
        result, error, _ = self.repo.confirm_quote(
            first_quote["id"], first_quote["snapshot_token"], "Example Customer", "Sales Admin"
        )
        self.assertIsNone(result)
        self.assertEqual(error, "stale_confirmation")
        result, error, _ = self.repo.confirm_quote(
            second_quote["id"], "0" * 64, "Example Customer", "Sales Admin"
        )
        self.assertIsNone(result)
        self.assertEqual(error, "stale_confirmation")

    def test_story_a_diff_uses_only_stored_snapshots(self) -> None:
        first_quote = self.add_quote_turn("Quote 8 P2425HE. Budget SGD 2500.")
        second_quote = self.add_quote_turn("Change quantity to 10 units.")
        diff = compare_quotes(first_quote, second_quote)
        self.assertEqual(diff["identity_quality"], "stable_line_id")
        self.assertEqual(diff["lines"]["added"], [])
        self.assertEqual(diff["lines"]["removed"], [])
        self.assertEqual(diff["lines"]["changed"][0]["changes"]["quantity"], {"from": 8, "to": 10, "delta": 2})
        self.assertEqual(diff["totals"]["total_cents"]["delta"], 57800)
        self.assertTrue(diff["has_changes"])

    def test_stale_save_and_latest_non_quote_are_rejected(self) -> None:
        self.turns.append("Quote 8 P2425HE.")
        self.repo.append_exchange(self.conversation["id"], self.turns[-1], "draft", _agent_result(self.turns))
        first_state = self.repo.get_conversation(self.conversation["id"])
        first_result_id = first_state["latest_result_message_id"]
        self.turns.append("What resolution does P2425HE support?")
        self.repo.append_exchange(self.conversation["id"], self.turns[-1], "clarify", _agent_result(self.turns))
        quote, error = self.repo.save_latest_quote(
            self.conversation["id"], first_result_id, "Example Customer"
        )
        self.assertIsNone(quote)
        self.assertEqual(error, "stale_draft")
        latest = self.repo.get_conversation(self.conversation["id"])
        quote, error = self.repo.save_latest_quote(
            self.conversation["id"], latest["latest_result_message_id"], "Example Customer"
        )
        self.assertIsNone(quote)
        self.assertEqual(error, "no_draft")

    def test_parallel_confirmation_creates_one_append_only_record(self) -> None:
        quote = self.add_quote_turn("Quote 8 P2425HE.")
        def confirm():
            return self.repo.confirm_quote(
                quote["id"], quote["snapshot_token"], "Example Customer", "Sales Admin"
            )
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: confirm(), range(4)))
        ids = {result[0]["confirmation"]["id"] for result in results if result[1] is None}
        self.assertEqual(len(ids), 1)
        with self.repo.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM quote_confirmations").fetchone()[0], 1)

    def test_confirmed_pdf_contains_snapshot_amounts(self) -> None:
        quote = self.add_quote_turn("Quote 8 P2425HE. Budget SGD 2500.")
        quote, error, _ = self.repo.confirm_quote(
            quote["id"], quote["snapshot_token"], "Café Example", "Sales Admin"
        )
        self.assertIsNone(error)
        pdf = render_confirmed_quote(quote["confirmation"]["snapshot"])
        self.assertEqual(pdf, render_confirmed_quote(quote["confirmation"]["snapshot"]))
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertGreater(len(pdf), 10_000)
        reader = PdfReader(io.BytesIO(pdf))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        self.assertIn("Café Example", text)
        self.assertIn("P2425HE", text)
        self.assertIn("SGD 2,312.00", text)
        self.assertIn("demo quotation", text.lower())

    def test_pdf_paginates_long_confirmed_snapshot(self) -> None:
        quote = self.add_quote_turn("Quote 8 P2425HE.")
        quote, error, _ = self.repo.confirm_quote(
            quote["id"], quote["snapshot_token"], "Long Customer", "Sales Admin"
        )
        self.assertIsNone(error)
        snapshot = copy.deepcopy(quote["confirmation"]["snapshot"])
        original = snapshot["lines"][0]
        snapshot["lines"] = []
        for index in range(45):
            line = copy.deepcopy(original)
            line["line_id"] = f"line-{index:03d}"
            line["name"] = f"Dell P2425HE Monitor - long descriptive line {index + 1}"
            snapshot["lines"].append(line)
        subtotal = sum(line["net_cents"] for line in snapshot["lines"])
        snapshot["subtotal_cents"] = subtotal
        snapshot["total_cents"] = subtotal + snapshot["shipping_fee_cents"]
        pdf = render_confirmed_quote(snapshot)
        reader = PdfReader(io.BytesIO(pdf))
        self.assertGreater(len(reader.pages), 1)
        for page in reader.pages:
            self.assertIn("Product", page.extract_text() or "")


class DiffEdgeCaseTests(unittest.TestCase):
    @staticmethod
    def quote(identifier: str, conversation: str, lines: list[dict], currency: str = "SGD") -> dict:
        total = sum(line["net_cents"] for line in lines)
        return {
            "id": identifier,
            "conversation_id": conversation,
            "version": 1 if identifier == "a" else 2,
            "status": "saved_draft",
            "snapshot_schema_version": 2,
            "payload": {
                "currency": currency, "lines": lines,
                "subtotal_cents": total, "shipping_fee_cents": 0,
                "total_cents": total,
            },
            "confirmation": None,
        }

    def test_added_removed_and_cross_currency_are_explicit(self) -> None:
        first_line = {"line_id": "line-a", "sku": "A", "model": "A", "name": "A", "quantity": 1, "unit_price_cents": 100, "discount_bps": 0, "gross_cents": 100, "discount_cents": 0, "net_cents": 100}
        second_line = {"line_id": "line-b", "sku": "B", "model": "B", "name": "B", "quantity": 1, "unit_price_cents": 200, "discount_bps": 0, "gross_cents": 200, "discount_cents": 0, "net_cents": 200}
        before = self.quote("a", "c", [first_line])
        after = self.quote("b", "c", [second_line])
        diff = compare_quotes(before, after)
        self.assertEqual([line["line_id"] for line in diff["lines"]["removed"]], ["line-a"])
        self.assertEqual([line["line_id"] for line in diff["lines"]["added"]], ["line-b"])
        foreign = self.quote("b", "c", [second_line], currency="USD")
        currency_diff = compare_quotes(before, foreign)
        self.assertFalse(currency_diff["comparable"])
        self.assertNotIn("delta", currency_diff["totals"]["total_cents"])


class LegacyMigrationTests(unittest.TestCase):
    def test_legacy_driver_rows_migrate_to_gateway_without_losing_messages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "converse.sqlite"
            with closing(sqlite3.connect(path)) as db:
                with db:
                    db.executescript(
                        """PRAGMA foreign_keys=ON;
                        CREATE TABLE conversations(
                            id TEXT PRIMARY KEY,
                            driver TEXT NOT NULL CHECK(driver IN ('offline','converse')),
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        );
                        CREATE TABLE messages(
                            id TEXT PRIMARY KEY,
                            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                            seq INTEGER NOT NULL,
                            role TEXT NOT NULL,
                            content TEXT NOT NULL,
                            result_json TEXT,
                            created_at TEXT NOT NULL
                        );"""
                    )
                    db.execute("INSERT INTO conversations VALUES ('c','converse','t','t')")
                    db.execute("INSERT INTO messages VALUES ('m','c',1,'user','hello',NULL,'t')")
            repo = Repository(path)
            with repo.connect() as db:
                self.assertEqual(db.execute("SELECT driver FROM conversations WHERE id='c'").fetchone()[0], "gateway")
                self.assertEqual(db.execute("SELECT content FROM messages WHERE id='m'").fetchone()[0], "hello")
                self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_legacy_row_is_byte_preserved_and_not_confirmable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.sqlite"
            payload = '{"status":"saved_draft","currency":"SGD","lines":[],"total_cents":100}'
            token = hashlib.sha256(payload.encode()).hexdigest()
            with closing(sqlite3.connect(path)) as db:
                with db:
                    db.executescript(
                        """CREATE TABLE conversations(id TEXT PRIMARY KEY,driver TEXT,created_at TEXT,updated_at TEXT);
                        CREATE TABLE messages(id TEXT PRIMARY KEY,conversation_id TEXT,seq INTEGER,role TEXT,content TEXT,result_json TEXT,created_at TEXT);
                        CREATE TABLE quote_versions(id TEXT PRIMARY KEY,conversation_id TEXT,version INTEGER,fingerprint TEXT,payload_json TEXT,created_at TEXT,UNIQUE(conversation_id,version),UNIQUE(conversation_id,fingerprint));"""
                    )
                    db.execute("INSERT INTO conversations VALUES ('c','offline','t','t')")
                    db.execute("INSERT INTO quote_versions VALUES ('q','c',1,?,?, 't')", (token, payload))
            repo = Repository(path)
            with repo.connect() as db:
                stored = db.execute("SELECT payload_json,fingerprint,snapshot_schema_version FROM quote_versions WHERE id='q'").fetchone()
                self.assertEqual(stored["payload_json"], payload)
                self.assertEqual(stored["fingerprint"], token)
                self.assertEqual(stored["snapshot_schema_version"], 1)
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)
            quote = repo.get_quote("q")
            self.assertEqual(quote["status"], "legacy_saved_draft")
            self.assertFalse(quote["confirmable"])
            result, error, missing = repo.confirm_quote("q", token, "Customer", "Reviewer")
            self.assertIsNone(result)
            self.assertEqual(error, "not_confirmable")
            self.assertEqual(missing, ["schema_version"])


class AssistantMessageTests(unittest.TestCase):
    def test_broad_office_brief_requests_decision_details_before_model_selection(self) -> None:
        prompt = QuotationService._clarification_prompt(
            "We need around 8 monitors for one-cable video and charging. Budget SGD 2500.",
            {"status": "needs_clarification", "candidates": [{}] * 18},
        )
        self.assertIn("18 technically compatible models", prompt)
        self.assertIn("minimum laptop charging wattage", prompt)
        self.assertIn("preferred screen size or resolution", prompt)
        self.assertIn("whether the quantity is exact", prompt)

    def test_gateway_clarification_preserves_specific_model_question(self) -> None:
        result = {
            "status": "needs_clarification",
            "configured_driver": "gateway",
            "used_fallback": False,
            "ask_for": ["product_specification_or_model"],
            "candidates": [{"sku": "MON-007"}, {"sku": "MON-010"}],
            "notes": [
                "Prices and rules are synthetic/demo data; this is not a tax invoice.",
                "Please confirm the minimum laptop charging wattage and preferred screen size.",
            ],
        }
        self.assertEqual(
            QuotationService._assistant_message(result),
            "Please confirm the minimum laptop charging wattage and preferred screen size.",
        )

    def test_gateway_policy_boundary_uses_deterministic_complete_message(self) -> None:
        result = {
            "status": "rule_violation",
            "configured_driver": "gateway",
            "used_fallback": False,
            "notes": [
                "Prices and rules are synthetic/demo data; this is not a tax invoice.",
                "Would you like me to apply the maximum discount?",
                "Stock and delivery timing are unknown; a human must confirm availability.",
                "Requested discount exceeds the 5% (500 bps) limit; it cannot be applied or approved.",
            ],
        }
        message = QuotationService._assistant_message(result)
        self.assertIn("exceeds the 5% policy limit", message)
        self.assertIn("delivery remain unconfirmed", message)
        self.assertNotIn("maximum discount", message)

    def test_gateway_evidence_message_preserves_model_markdown(self) -> None:
        result = {
            "status": "answer_with_evidence",
            "configured_driver": "gateway",
            "used_fallback": False,
            "notes": [
                "Prices and rules are synthetic/demo data; this is not a tax invoice.",
                "**Verified:** USB-C video is supported.",
            ],
        }
        self.assertEqual(
            QuotationService._assistant_message(result),
            "**Verified:** USB-C video is supported.",
        )


class QuoteApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.original_repository = main_module.repository
        self.original_service = main_module.service
        repository = Repository(Path(self.temp.name) / "api.sqlite")
        settings = replace(load_settings(), app_db_path=repository.path, agent_driver="offline")
        main_module.repository = repository
        main_module.service = QuotationService(repository, settings)
        self.client = TestClient(main_module.app)

    def tearDown(self) -> None:
        self.client.close()
        main_module.repository = self.original_repository
        main_module.service = self.original_service
        self.temp.cleanup()

    def create_saved_quote(self) -> dict:
        conversation = self.client.post("/api/conversations", json={"driver": "offline"}).json()
        state = self.client.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={"content": "Quote 8 P2425HE. Budget SGD 2500."},
        ).json()
        response = self.client.post(
            f"/api/conversations/{conversation['id']}/quotes",
            json={
                "result_message_id": state["latest_result_message_id"],
                "customer_display_name": "Example Customer",
            },
        )
        self.assertEqual(response.status_code, 201)
        return response.json()

    def test_health_does_not_expose_server_database_path(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("database", response.json())

    def test_product_evidence_uses_official_source_without_local_pdf_route(self) -> None:
        response = self.client.get("/api/products/MON-007")
        self.assertEqual(response.status_code, 200)
        evidence = response.json()["evidence"]
        self.assertEqual(len(evidence), 8)
        self.assertTrue(all(item["source_url"].startswith("https://dl.dell.com/") for item in evidence))
        self.assertTrue(all(f"#page={item['pdf_page']}" in item["source_url"] for item in evidence))
        self.assertTrue(all("local_pdf_url" not in item for item in evidence))
        self.assertEqual(self.client.get("/api/sources/DELL-P25HE/pdf").status_code, 404)

    def test_confirm_diff_and_pdf_http_contract(self) -> None:
        saved = self.create_saved_quote()
        blocked = self.client.get(f"/api/quotes/{saved['id']}/pdf")
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()["detail"]["error"], "not_exportable")
        confirmation = self.client.post(
            f"/api/quotes/{saved['id']}/confirm",
            json={
                "snapshot_token": saved["snapshot_token"],
                "customer_display_name": "Example Customer",
                "confirmed_by": "Sales Admin",
            },
        )
        self.assertEqual(confirmation.status_code, 200)
        self.assertTrue(confirmation.json()["exportable"])
        pdf = self.client.get(f"/api/quotes/{saved['id']}/pdf")
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf.headers["content-type"], "application/pdf")
        self.assertIn("attachment", pdf.headers["content-disposition"])
        self.assertTrue(pdf.content.startswith(b"%PDF-"))
        same = self.client.get(f"/api/quotes/{saved['id']}/diff/{saved['id']}")
        self.assertEqual(same.status_code, 200)
        self.assertFalse(same.json()["has_changes"])

    def test_story_a_version_handoff_over_http(self) -> None:
        conversation = self.client.post("/api/conversations", json={"driver": "offline"}).json()
        conversation_url = f"/api/conversations/{conversation['id']}"
        first_turn = self.client.post(
            f"{conversation_url}/messages",
            json={"content": "Quote 8 P2425HE. Budget SGD 2500."},
        ).json()
        first_response = self.client.post(
            f"{conversation_url}/quotes",
            json={"result_message_id": first_turn["latest_result_message_id"], "customer_display_name": "Example Customer"},
        )
        self.assertEqual(first_response.status_code, 201)
        first_quote = first_response.json()
        self.assertEqual(first_quote["payload"]["total_cents"], 231200)

        second_turn = self.client.post(
            f"{conversation_url}/messages",
            json={"content": "Change quantity to 10 units."},
        ).json()
        second_response = self.client.post(
            f"{conversation_url}/quotes",
            json={"result_message_id": second_turn["latest_result_message_id"], "customer_display_name": "Example Customer"},
        )
        self.assertEqual(second_response.status_code, 201)
        second_quote = second_response.json()
        self.assertEqual(second_quote["version"], 2)
        self.assertEqual(second_quote["payload"]["total_cents"], 289000)

        versions = self.client.get(conversation_url).json()["quote_versions"]
        self.assertEqual({item["id"] for item in versions}, {first_quote["id"], second_quote["id"]})
        diff = self.client.get(f"/api/quotes/{first_quote['id']}/diff/{second_quote['id']}")
        self.assertEqual(diff.status_code, 200)
        self.assertEqual(diff.json()["totals"]["total_cents"]["delta"], 57800)
        self.assertEqual(diff.json()["lines"]["changed"][0]["changes"]["quantity"]["delta"], 2)

        stale = self.client.post(
            f"/api/quotes/{first_quote['id']}/confirm",
            json={"snapshot_token": first_quote["snapshot_token"], "customer_display_name": "Example Customer", "confirmed_by": "Sales Admin"},
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["detail"]["error"], "stale_confirmation")
        confirmed = self.client.post(
            f"/api/quotes/{second_quote['id']}/confirm",
            json={"snapshot_token": second_quote["snapshot_token"], "customer_display_name": "Example Customer", "confirmed_by": "Sales Admin"},
        )
        self.assertEqual(confirmed.status_code, 200)
        self.assertTrue(confirmed.json()["exportable"])
        self.assertEqual(confirmed.json()["pdf_url"], f"/api/quotes/{second_quote['id']}/pdf")
        pdf = self.client.get(confirmed.json()["pdf_url"])
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b"%PDF-"))

    def test_cross_conversation_diff_is_rejected(self) -> None:
        first = self.create_saved_quote()
        second = self.create_saved_quote()
        response = self.client.get(f"/api/quotes/{first['id']}/diff/{second['id']}")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["error"], "cross_conversation")

    def test_database_save_failure_preserves_draft_and_allows_retry(self) -> None:
        conversation = self.client.post("/api/conversations", json={"driver": "offline"}).json()
        state = self.client.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={"content": "Quote 8 P2425HE. Budget SGD 2500."},
        ).json()
        result_id = state["latest_result_message_id"]
        self.assertEqual(state["latest_result"]["quote_draft"]["total_cents"], 231200)
        with main_module.repository.connect() as db:
            db.execute(
                """CREATE TRIGGER fail_quote_save BEFORE INSERT ON quote_versions
                BEGIN SELECT RAISE(ABORT, 'injected database failure'); END"""
            )

        body = {"result_message_id": result_id, "customer_display_name": "Example Customer"}
        with TestClient(main_module.app, raise_server_exceptions=False) as failure_client:
            failed = failure_client.post(f"/api/conversations/{conversation['id']}/quotes", json=body)
        self.assertEqual(failed.status_code, 500)
        retained = self.client.get(f"/api/conversations/{conversation['id']}").json()
        self.assertEqual(retained["latest_result_message_id"], result_id)
        self.assertEqual(retained["latest_result"]["quote_draft"]["total_cents"], 231200)
        self.assertEqual(retained["quote_versions"], [])

        with main_module.repository.connect() as db:
            db.execute("DROP TRIGGER fail_quote_save")
        saved = self.client.post(f"/api/conversations/{conversation['id']}/quotes", json=body)
        self.assertEqual(saved.status_code, 201)
        self.assertEqual(saved.json()["version"], 1)

    def test_pdf_failure_preserves_confirmation_and_allows_retry(self) -> None:
        saved = self.create_saved_quote()
        confirmed = self.client.post(
            f"/api/quotes/{saved['id']}/confirm",
            json={
                "snapshot_token": saved["snapshot_token"],
                "customer_display_name": "Example Customer",
                "confirmed_by": "Sales Admin",
            },
        ).json()
        confirmation_id = confirmed["confirmation"]["id"]
        with patch.object(main_module, "render_confirmed_quote", side_effect=PdfRenderError("injected render failure")):
            failed = self.client.get(f"/api/quotes/{saved['id']}/pdf")
        self.assertEqual(failed.status_code, 500)
        self.assertEqual(failed.json()["detail"]["error"], "pdf_generation_failed")
        retained = self.client.get(f"/api/quotes/{saved['id']}").json()
        self.assertTrue(retained["exportable"])
        self.assertEqual(retained["confirmation"]["id"], confirmation_id)
        retried = self.client.get(f"/api/quotes/{saved['id']}/pdf")
        self.assertEqual(retried.status_code, 200)
        self.assertTrue(retried.content.startswith(b"%PDF-"))


if __name__ == "__main__":
    unittest.main()
