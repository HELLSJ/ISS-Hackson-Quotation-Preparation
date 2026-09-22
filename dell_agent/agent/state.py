"""Agent status state machine and clarification/conflict detection.

A pure, deterministic classifier that maps a *resolved* customer turn to one of
the eight evaluation statuses used by ``expected_results.jsonl``:

    ready_to_quote, needs_clarification, explain_limitation,
    answer_with_evidence, no_match, budget_conflict, rule_violation,
    invalid_quantity

The design principle (Req 5, 6): the model understands and asks; deterministic
logic owns the classification and the clarification vocabulary. This module is
intentionally free of side effects and cloud dependencies so both the offline
planner (``agent/loop.py``) and the test suite can drive it directly. The LLM
path is steered toward the same outcomes via the system prompt.

Nothing here fabricates prices, quantities, or substitutions. Slot detection is
keyword/heuristic only — it never parses a full customer sentence into a tool
query (that translation is the caller's job via ``search_products``).

Uses only the Python standard library.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------- #
# Status constants
# --------------------------------------------------------------------------- #
#
# The eight statuses come verbatim from the frozen evaluation set. Exposed as
# module constants so callers and tests reference them symbolically rather than
# by bare string literals.

READY_TO_QUOTE = "ready_to_quote"
NEEDS_CLARIFICATION = "needs_clarification"
EXPLAIN_LIMITATION = "explain_limitation"
ANSWER_WITH_EVIDENCE = "answer_with_evidence"
NO_MATCH = "no_match"
BUDGET_CONFLICT = "budget_conflict"
RULE_VIOLATION = "rule_violation"
INVALID_QUANTITY = "invalid_quantity"

STATUSES = frozenset(
    {
        READY_TO_QUOTE,
        NEEDS_CLARIFICATION,
        EXPLAIN_LIMITATION,
        ANSWER_WITH_EVIDENCE,
        NO_MATCH,
        BUDGET_CONFLICT,
        RULE_VIOLATION,
        INVALID_QUANTITY,
    }
)

# --------------------------------------------------------------------------- #
# ask_for slot vocabulary
# --------------------------------------------------------------------------- #
#
# These are the exact slot names emitted in the DEV/HOLDOUT ``ask_for`` arrays.
# They are surfaced as constants so ``missing_slots`` and the classifier speak a
# single, checkable vocabulary.

SLOT_QUANTITY = "quantity"
SLOT_PRODUCT_OR_MODEL = "product_specification_or_model"
SLOT_USB_C_VIDEO = "usb_c_video_requirement"
SLOT_HOST_CHARGING = "host_charging_requirement"
SLOT_ACTUAL_VS_MARKETED = "actual_vs_marketed_diagonal"
SLOT_MIN_HOST_PD = "minimum_host_pd_watts"


# --------------------------------------------------------------------------- #
# Discount ceiling (mirrors the synthetic rules; Req 6.1)
# --------------------------------------------------------------------------- #

DISCOUNT_LIMIT_BPS = 500


# --------------------------------------------------------------------------- #
# Resolved turn structure
# --------------------------------------------------------------------------- #

@dataclass
class RequestedItem:
    """A single product line a caller has (partially) resolved from the turn.

    ``sku`` / ``model`` name the product when the customer picked one; either may
    be ``None`` when the turn only describes specs. ``quantity`` is whatever the
    caller extracted — it is *not* validated here beyond the classifier's
    ``invalid_quantity`` check, and is never invented. ``discount_bps`` is the
    customer-requested discount (``None`` means none stated; the default is 0).
    """

    sku: Optional[str] = None
    model: Optional[str] = None
    quantity: Optional[Any] = None
    discount_bps: Optional[int] = None


@dataclass
class EnquiryState:
    """A resolved snapshot of one customer turn, ready for classification.

    This is the pure input to :func:`classify_status`. The caller (offline
    planner or LLM post-processing) is responsible for populating it from the
    raw turn plus any structured tool results (e.g. ``search_products`` output).
    The classifier reads only these fields and never calls a tool itself.

    Attributes:
        text: The raw customer text for the turn (used by the keyword
            detectors and the injection guard).
        items: Requested product lines resolved so far.
        budget_cents: The customer's stated budget in integer cents, if any.
        is_factual_question: True when the turn asks a factual spec question
            (e.g. "which port?", "is X the same as Y?") rather than requesting a
            quote (Req 5.5 / DEV-011, DEV-012).
        named_sku_limitation: Set when the turn names a specific SKU that cannot
            meet a stated requirement (e.g. a data-only USB-C port asked to carry
            video/charge). Drives ``explain_limitation`` (Req 6.2 / DEV-009,010).
        search_yielded_empty: True when the caller ran a structured
            ``search_products`` over concrete constraints and got ``[]``. Drives
            ``no_match`` (Req 2.6 / DEV-013).
        has_concrete_constraints: True when the turn carried concrete structured
            constraints (so an empty search is a genuine ``no_match`` rather than
            missing information).
        cheapest_matching_total_cents: When a budget is present and a cheapest
            matching option was priced, the total for that option. If it exceeds
            ``budget_cents`` the classifier reports ``budget_conflict``
            (Req 5.6 / DEV-014).
        clarify_slots_override: Optional explicit slot list. When provided it is
            used verbatim by :func:`missing_slots`, letting a caller inject slots
            it derived from richer context.
    """

    text: str = ""
    items: List[RequestedItem] = field(default_factory=list)
    budget_cents: Optional[int] = None
    is_factual_question: bool = False
    named_sku_limitation: bool = False
    search_yielded_empty: bool = False
    has_concrete_constraints: bool = False
    cheapest_matching_total_cents: Optional[int] = None
    clarify_slots_override: Optional[List[str]] = None


# --------------------------------------------------------------------------- #
# Quantity / discount helpers
# --------------------------------------------------------------------------- #

def _is_positive_int_quantity(value: Any) -> bool:
    """True only for a genuine integer quantity >= 1 (``bool`` excluded)."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _has_invalid_quantity(state: EnquiryState) -> bool:
    """True when any *stated* quantity is non-positive or non-integer.

    A ``None`` quantity is *missing* (handled by clarification), not invalid, so
    it is skipped here. A stated quantity of 0, a negative, a float, or a
    non-numeric value is invalid (Req 4.7 / DEV-020).
    """
    for item in state.items:
        qty = item.quantity
        if qty is None:
            continue
        if not _is_positive_int_quantity(qty):
            return True
    return False


def _has_rule_violation(state: EnquiryState) -> bool:
    """True when any requested discount exceeds the 500 bps ceiling (Req 6.1).

    The request is refused, never clamped (DEV-019 must not calculate/approve a
    6% discount).
    """
    for item in state.items:
        bps = item.discount_bps
        if bps is not None and bps > DISCOUNT_LIMIT_BPS:
            return True
    return False


def _item_names_product(item: RequestedItem) -> bool:
    """True when an item identifies a concrete product (sku or model)."""
    return bool((item.sku and str(item.sku).strip()) or (item.model and str(item.model).strip()))


# --------------------------------------------------------------------------- #
# Keyword detectors (Req 5.2, 5.3)
# --------------------------------------------------------------------------- #

# Marketed size like "24-inch", "27 inch", "24\"", "27in". We capture the
# leading number so the detector can distinguish a marketed size class from the
# precise viewable diagonal (e.g. 23.81) the catalogue stores.
_MARKETED_SIZE_RE = re.compile(
    r"(?<!\d)(\d{2}(?:\.\d+)?)\s*(?:-\s*)?(?:inch|inches|in\b|\")",
    re.IGNORECASE,
)

# "USB-C", "USB C", "USBC", "Type-C", "Thunderbolt", "TB4".
_USB_C_RE = re.compile(r"\b(usb[\s\-]?c|type[\s\-]?c|thunderbolt|tb[\s\-]?\d)\b", re.IGNORECASE)

# Words that make a USB-C mention concrete about *video* intent.
_VIDEO_INTENT_RE = re.compile(
    r"\b(video|picture|display|dp\s*alt|alt\s*mode|screen\s*out|carry\s*video|hdmi|displayport)\b",
    re.IGNORECASE,
)

_ONE_CABLE_RE = re.compile(r"\b(?:one|single)[\s-]+cable\b", re.IGNORECASE)

# Words that make a USB-C mention concrete about *host charging* intent, or that
# state an explicit power level (e.g. "90W", "65 watts").
_CHARGING_INTENT_RE = re.compile(
    r"\b(charg\w*|power\s*deliver\w*|\bpd\b|\d{2,3}\s*w(?:atts?)?\b)",
    re.IGNORECASE,
)


def size_needs_clarification(text: str) -> bool:
    """True when the text states a *marketed* monitor size (Req 5.3).

    A marketed size such as "24-inch" is ambiguous against the catalogue's
    precise viewable diagonal (e.g. 23.81"). When one is stated, the agent must
    clarify whether the marketed class is acceptable before applying a strict
    numeric minimum, rather than silently choosing one interpretation.
    """
    if not text:
        return False
    return _MARKETED_SIZE_RE.search(text) is not None


def usb_c_needs_clarification(text: str) -> bool:
    """True when "USB-C" is mentioned without explicit video/charging intent (Req 5.2).

    A bare "USB-C" is ambiguous: it may mean data-only, video (DP Alt Mode),
    host charging, or a mix, at an unspecified power. When neither video nor
    charging intent is expressed the agent must clarify both requirements and the
    minimum host power before recommending a product. If the customer already
    stated the intent (e.g. "USB-C for video and 90W charging") there is nothing
    to clarify.
    """
    if not text or _USB_C_RE.search(text) is None:
        return False
    has_video = _VIDEO_INTENT_RE.search(text) is not None
    has_charging = _CHARGING_INTENT_RE.search(text) is not None
    # Ambiguous only when *neither* intent is pinned down. If a customer says
    # "USB-C with charging" the charging axis is set but video is not; the size
    # ambiguity path below still gathers the remaining slots for that case.
    return not (has_video and has_charging)


def _usb_c_mentioned(text: str) -> bool:
    return bool(text) and _USB_C_RE.search(text) is not None


def _video_intent(text: str) -> bool:
    return bool(text) and _VIDEO_INTENT_RE.search(text) is not None


def _charging_intent(text: str) -> bool:
    return bool(text) and _CHARGING_INTENT_RE.search(text) is not None


# --------------------------------------------------------------------------- #
# Prompt-injection guard (Req 6.3)
# --------------------------------------------------------------------------- #

# Phrases that attempt to override tool policy or role. Matched case-insensitively
# on whole lines/segments; matches are neutralised, not obeyed.
_INJECTION_PATTERNS = (
    r"ignore (?:all |any |the )?(?:previous|prior|above|earlier) (?:instructions?|prompts?|rules?)",
    r"disregard (?:all |any |the )?(?:previous|prior|above|system) (?:instructions?|prompts?|rules?)",
    r"forget (?:everything|all|your) (?:instructions?|prompts?|rules?)?",
    r"you are now (?:a|an|the)\b.*",
    r"act as (?:a|an|the)\b.*",
    r"pretend (?:to be|you are)\b.*",
    r"(?:new|updated|revised) (?:system )?(?:instructions?|policy|policies|rules?)\s*[:\-].*",
    r"override (?:the )?(?:discount|pricing|policy|policies|rules?|limit)s?\b.*",
    r"(?:approve|allow|grant) (?:a |an )?(?:\d+%?\s*)?discount\b.*",  # only when embedded as an instruction; see guard
    r"(?:raise|increase|change|set) (?:the )?discount (?:limit|cap|ceiling)\b.*",
    r"do not (?:follow|apply|obey) (?:the )?(?:rules?|policy|policies|limit)\b.*",
    r"system\s*[:\-]\s*.*",
    r"assistant\s*[:\-]\s*.*",
)

_INJECTION_RE = re.compile("|".join(f"(?:{p})" for p in _INJECTION_PATTERNS), re.IGNORECASE)

_INJECTION_REDACTION = "[ignored-embedded-instruction]"


@dataclass
class SanitizedText:
    """Result of :func:`injection_guard`.

    Attributes:
        text: The sanitized text, with any embedded instruction segments
            replaced by a redaction marker. Safe to treat as data.
        injection_detected: True when at least one instruction-like segment was
            found and neutralised.
    """

    text: str
    injection_detected: bool

    def __bool__(self) -> bool:  # pragma: no cover - convenience
        return self.injection_detected


def injection_guard(text: str) -> SanitizedText:
    """Neutralise embedded "instructions" in source/customer text (Req 6.3).

    All source and customer content is data, never instructions. This strips any
    segment that looks like an attempt to change tool policy, role, or the
    discount ceiling, replacing it with a redaction marker so the surrounding
    genuine request is preserved. Returns a :class:`SanitizedText` carrying the
    sanitized string and a flag; the caller uses the sanitized text for any
    downstream keyword detection and ignores the redacted directives.

    The guard only *neutralises*; it never applies the embedded directive. It
    truthy-evaluates to ``injection_detected`` for terse ``if injection_guard(x):``
    checks while still exposing ``.text`` for the sanitized content.
    """
    if not text:
        return SanitizedText(text=text or "", injection_detected=False)

    sanitized, count = _INJECTION_RE.subn(_INJECTION_REDACTION, text)
    # Collapse whitespace introduced around redactions for tidy downstream matching.
    sanitized = re.sub(r"[ \t]{2,}", " ", sanitized).strip()
    return SanitizedText(text=sanitized, injection_detected=count > 0)


# --------------------------------------------------------------------------- #
# Missing-slot detector (Req 5.1, 5.2, 5.3)
# --------------------------------------------------------------------------- #

def missing_slots(state: EnquiryState) -> List[str]:
    """Return the ``ask_for`` slot names a turn still needs clarified.

    Produces lists that match the DEV/HOLDOUT vocabulary exactly, e.g.::

        ["quantity"]
        ["product_specification_or_model"]
        ["usb_c_video_requirement", "host_charging_requirement"]
        ["actual_vs_marketed_diagonal", "minimum_host_pd_watts", "quantity"]

    Precedence mirrors the observed evaluation cases:

    1. A caller-supplied ``clarify_slots_override`` wins verbatim.
    2. A *marketed size* stated together with USB-C charging (but no precise
       diagonal / host power / quantity) asks for the diagonal, host power, and
       quantity in that order (DEV-008).
    3. A *bare USB-C* mention with neither video nor charging intent asks for the
       video and host-charging requirements (DEV-007).
    4. Otherwise the turn needs a product/spec and/or a quantity: if no product
       is identified at all, ask for ``product_specification_or_model``
       (DEV-006); if a product is named but no quantity is stated, ask for
       ``quantity`` (DEV-005).

    The order of the returned list is significant and is kept stable so callers
    can compare it directly against the expected arrays.
    """
    if state.clarify_slots_override is not None:
        return list(state.clarify_slots_override)

    text = state.text or ""

    any_product_named = any(_item_names_product(it) for it in state.items)
    any_quantity_stated = any(it.quantity is not None for it in state.items)

    # (2) Marketed size + USB-C charging, still under-specified (DEV-008:
    # "Find 24-inch USB-C displays with charging."). The precise diagonal, the
    # minimum host power, and the quantity are all outstanding.
    if size_needs_clarification(text) and (
        (_usb_c_mentioned(text) and _charging_intent(text))
        or _ONE_CABLE_RE.search(text)
    ):
        slots = [SLOT_ACTUAL_VS_MARKETED, SLOT_MIN_HOST_PD]
        if not any_quantity_stated:
            slots.append(SLOT_QUANTITY)
        return slots

    # (3) Bare USB-C, neither video nor charging intent pinned (DEV-007:
    # "We need 8 monitors with USB-C.").
    if usb_c_needs_clarification(text) and not _video_intent(text) and not _charging_intent(text):
        return [SLOT_USB_C_VIDEO, SLOT_HOST_CHARGING]

    # (4) Product / quantity gaps.
    slots: List[str] = []
    if not any_product_named:
        # No concrete product identified (DEV-006: "We need 10 monitors.").
        slots.append(SLOT_PRODUCT_OR_MODEL)
    elif not any_quantity_stated:
        # A product is named but the quantity is missing (DEV-005:
        # "Please quote P2425HE.").
        slots.append(SLOT_QUANTITY)
    return slots


# --------------------------------------------------------------------------- #
# Status classifier (Req 5, 6, 8)
# --------------------------------------------------------------------------- #

def classify_status(state: EnquiryState) -> str:
    """Map a resolved turn to one of the eight evaluation statuses.

    Precedence (highest first), chosen to reproduce the DEV/HOLDOUT expectations:

    1. ``invalid_quantity`` — any *stated* quantity is non-positive/non-integer
       (DEV-020). A hard input error outranks everything else.
    2. ``rule_violation`` — a requested discount exceeds 500 bps (DEV-019); the
       request is refused, never clamped.
    3. ``explain_limitation`` — a named SKU cannot meet a stated requirement
       (DEV-009, DEV-010).
    4. ``answer_with_evidence`` — the turn is a factual spec question
       (DEV-011, DEV-012).
    5. ``no_match`` — a structured search over concrete constraints yielded ``[]``
       (DEV-013), or a named product does not exist (DEV-015).
    6. ``budget_conflict`` — the cheapest matching option still exceeds budget
       (DEV-014).
    7. ``needs_clarification`` — the turn is under-specified (missing product,
       quantity, USB-C intent, or marketed-size intent) (DEV-005..008).
    8. ``ready_to_quote`` — products, quantities, and any confirmed discount are
       all resolved (DEV-001..004).

    The clarification gate is placed *after* the resolved-signal statuses so a
    turn that carries a named-SKU limitation, a factual question, an empty
    structured search, or a priced-but-over-budget option is not misrouted as
    "under-specified".

    Args:
        state: The resolved :class:`EnquiryState` for the turn.

    Returns:
        One of the members of :data:`STATUSES`.
    """
    # (1) Invalid stated quantity outranks all else (Req 4.7).
    if _has_invalid_quantity(state):
        return INVALID_QUANTITY

    # (2) Discount over the ceiling: refuse (Req 6.1).
    if _has_rule_violation(state):
        return RULE_VIOLATION

    # (3) A named SKU that cannot meet a stated requirement (Req 6.2). This is a
    # resolved-enough signal (the customer named the product and the constraint
    # it fails), so it takes precedence over the generic clarification gate.
    if state.named_sku_limitation:
        return EXPLAIN_LIMITATION

    # (4) Factual spec question (Req 5.5). A question is not a quote turn, so it
    # is never routed through clarification.
    if state.is_factual_question:
        return ANSWER_WITH_EVIDENCE

    # (5) Concrete constraints that match nothing / an unknown product (Req 2.6).
    # The customer gave enough concrete detail to run a structured search; an
    # empty result is a genuine no_match, not missing information.
    if state.search_yielded_empty and state.has_concrete_constraints:
        return NO_MATCH

    # (6) Cheapest matching option still over budget (Req 5.6). A priced cheapest
    # option means the specs resolved to real candidates; the only conflict is
    # the budget, so this is not a clarification.
    if (
        state.budget_cents is not None
        and state.cheapest_matching_total_cents is not None
        and state.cheapest_matching_total_cents > state.budget_cents
    ):
        return BUDGET_CONFLICT

    # (7) Under-specified quote turns need clarification (Req 5.1-5.3).
    slots = missing_slots(state)
    if slots:
        return NEEDS_CLARIFICATION

    # (8) Everything resolved (Req 5.7).
    return READY_TO_QUOTE


# --------------------------------------------------------------------------- #
# Convenience: build the ask_for payload for a needs_clarification turn
# --------------------------------------------------------------------------- #

def clarification_payload(state: EnquiryState) -> Dict[str, Any]:
    """Return ``{"status": ..., "ask_for": [...]}`` for a turn.

    Convenience for callers assembling the ``AgentResult``: classifies the turn
    and, when it needs clarification, attaches the ordered slot list.
    """
    status = classify_status(state)
    payload: Dict[str, Any] = {"status": status}
    if status == NEEDS_CLARIFICATION:
        payload["ask_for"] = missing_slots(state)
    return payload
