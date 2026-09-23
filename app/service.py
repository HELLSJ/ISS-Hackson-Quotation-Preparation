"""Application service: stateful replay around the stateless Agent drivers."""
from __future__ import annotations

import re
import threading
from typing import Any

from dell_agent.agent.loop import GatewayDriver, OfflineDriver
from dell_agent.agent.tools import dispatch

from .config import Settings
from .repository import Repository

_SLOT_QUESTIONS = {
    "quantity": "How many monitors should the quotation include?",
    "product_specification_or_model": "Which model should I quote? You can also select a catalogue candidate.",
    "usb_c_video_requirement": "Must USB-C carry the laptop's video signal?",
    "host_charging_requirement": "Should the same cable charge the laptop, and what minimum wattage is required?",
    "actual_vs_marketed_diagonal": "Is the marketed size class acceptable, or is the exact viewable diagonal a strict minimum?",
    "minimum_host_pd_watts": "What minimum USB-C host charging power is required?",
}


class QuotationService:
    def __init__(self, repository: Repository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings
        self.offline = OfflineDriver()
        self.gateway = GatewayDriver(
            base_url=settings.gateway_url,
            api_key=settings.gateway_api_key,
            model=settings.llm_model,
        )
        self._message_lock = threading.Lock()

    def driver(self, name: str):
        return self.gateway if name == "gateway" else self.offline

    def process_message(self, conversation_id: str, content: str) -> dict[str, Any] | None:
        """Replay all durable user turns and atomically append the new exchange."""
        with self._message_lock:
            conversation = self.repository.get_conversation(conversation_id)
            if conversation is None:
                return None
            turns = self.repository.get_user_turns(conversation_id) or []
            turns.append(content)
            agent_result = self.driver(conversation["driver"]).run(turns)
            result = agent_result.to_dict()
            result["configured_driver"] = conversation["driver"]
            result["used_fallback"] = any(
                isinstance(row, dict) and row.get("step") == "gateway_fallback"
                for row in result.get("trace", [])
            )
            requirement_text = "\n".join(turns)
            result["conflicts"] = self._identify_conflicts(requirement_text, result)
            result["suggestions"] = self._suggest_alternatives(requirement_text, result)
            assistant = self._assistant_message(result)
            self.repository.append_exchange(conversation_id, content, assistant, result)
            return self.repository.get_conversation(conversation_id)

    @staticmethod
    def _identify_conflicts(content: str, result: dict[str, Any]) -> list[dict[str, Any]]:
        if result.get("status") != "explain_limitation":
            return []
        wants_video = bool(re.search(r"\b(video|display|screen\s*out|displayport)\b", content, re.IGNORECASE))
        wants_charging = bool(re.search(r"\b(charg\w*|power\s*deliver\w*|\bpd\b|\d{2,3}\s*w)\b", content, re.IGNORECASE))
        watts_match = re.search(r"(\d{2,3})\s*w", content, re.IGNORECASE)
        min_watts = int(watts_match.group(1)) if watts_match else (1 if wants_charging else 0)
        conflicts = []
        for product in result.get("candidates") or []:
            reasons = []
            if wants_video and not product.get("usb_c_video"):
                reasons.append("usb_c_video")
            if wants_charging and (product.get("usb_c_pd_watts") or 0) < min_watts:
                reasons.append("usb_c_pd_watts")
            if reasons:
                conflicts.append({"sku": product["sku"], "model": product["model"], "reasons": reasons})
        return conflicts

    @staticmethod
    def _suggest_alternatives(content: str, result: dict[str, Any]) -> list[dict[str, Any]]:
        """Offer deterministic alternatives for a failed named-product constraint.

        Suggestions are never quoted or selected automatically. The user must
        explicitly choose one in a subsequent turn.
        """
        if result.get("status") != "explain_limitation":
            return []
        conflicts = result.get("conflicts") or []
        failed_sku = conflicts[0]["sku"] if conflicts else None
        failed = next(
            (candidate for candidate in result.get("candidates") or [] if candidate.get("sku") == failed_sku),
            None,
        )
        if not isinstance(failed, dict):
            return []
        watts_match = re.search(r"(\d{2,3})\s*w", content, re.IGNORECASE)
        min_watts = int(watts_match.group(1)) if watts_match else 65
        filters = {
            "usb_c_video": True,
            "min_pd_watts": min_watts,
            "min_screen_inches": failed.get("screen_inches"),
            "max_screen_inches": failed.get("screen_inches"),
            "resolution": failed.get("resolution"),
        }
        filters = {key: value for key, value in filters.items() if value is not None}
        candidates = dispatch("search_products", filters)
        if not isinstance(candidates, list):
            return []
        return [row for row in candidates if row["sku"] != failed.get("sku")][:3]

    @staticmethod
    def _assistant_message(result: dict[str, Any]) -> str:
        status = result.get("status")
        candidates = result.get("candidates") or []
        suggestions = result.get("suggestions") or []
        if (
            result.get("configured_driver") == "gateway"
            and not result.get("used_fallback")
            and status in {"answer_with_evidence", "explain_limitation"}
        ):
            model_notes = [
                note for note in result.get("notes", [])
                if "synthetic/demo data" not in note.lower()
                and "the named product cannot meet the stated" not in note.lower()
            ]
            if model_notes:
                return model_notes[0]
        if status == "needs_clarification":
            questions = [
                _SLOT_QUESTIONS[slot]
                for slot in result.get("ask_for", [])
                if slot in _SLOT_QUESTIONS
            ]
            lead = (
                f"I found {len(candidates)} matching catalogue models. "
                if candidates
                else ""
            )
            return lead + (" ".join(questions) or "Please provide the missing quotation details.")
        if status == "ready_to_quote":
            draft = result.get("quote_draft") or {}
            total = draft.get("total_cents", 0) / 100
            budget = ""
            if draft.get("within_budget") is False:
                budget = f" It is SGD {draft.get('over_budget_cents', 0) / 100:,.2f} over budget."
            return f"Draft calculated by the pricing tool: SGD {total:,.2f}.{budget} Review it before saving."
        if status == "explain_limitation":
            conflict_models = [item["model"] for item in result.get("conflicts") or []]
            model = ", ".join(conflict_models) or "The selected model"
            alternative = (
                f" {len(suggestions)} compatible alternative is available for your review."
                if len(suggestions) == 1
                else f" {len(suggestions)} compatible alternatives are available for your review."
                if suggestions
                else ""
            )
            return f"{model} cannot meet the stated one-cable video or host-charging requirement. Check the cited specification.{alternative}"
        if status == "rule_violation":
            return "The requested discount exceeds the 5% policy limit, so no quote was calculated. Stock and delivery remain unconfirmed."
        if status == "invalid_quantity":
            return "Quantity must be a positive whole number. No quote was calculated."
        if status == "no_match":
            return "No catalogue model satisfies all stated constraints. Change a requirement or select a model manually."
        if status == "budget_conflict":
            draft = result.get("quote_draft") or {}
            if draft:
                total = draft.get("total_cents", 0) / 100
                over = draft.get("over_budget_cents", 0) / 100
                return (
                    f"Draft calculated by the pricing tool: SGD {total:,.2f}. "
                    f"It is SGD {over:,.2f} over budget. Review it before saving."
                )
            return "The cheapest matching model exceeds the budget. Review the budget gap before changing any requirement."
        if status == "answer_with_evidence":
            return "The catalogue evidence for the named model is ready. Open a specification row to inspect the source PDF page."
        return "The request needs review before a quote can be prepared."
