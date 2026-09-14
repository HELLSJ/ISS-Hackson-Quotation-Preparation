"""Typed data models for the Dell Quotation Agent.

Frozen dataclasses describing the evidence-backed monitor catalogue, pricing
rules, and quote structures. Uses only the Python standard library
(``dataclasses`` + ``typing``); no third-party dependencies.

Design principle (Req 1.3, 4.2): unknown facts stay ``None`` and are never
coerced to ``0`` / ``False``; all monetary values are integer cents.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class Evidence:
    """Field-level citation to a source PDF/page (Req 2.2, 3.2, 3.3)."""

    sku: str
    field: str
    value: object
    source_id: str
    pdf_page: Optional[int]
    source_url: str
    method: str  # e.g. "direct_specification" | "standardized_derivation"
    note: str = ""


@dataclass(frozen=True)
class Product:
    """A single Dell monitor SKU with specs, synthetic price, and evidence.

    Unknown facts (``stock_quantity``, ``delivery_lead_days``,
    ``max_refresh_hz``) stay ``None`` and are never substituted with 0/false
    (Req 1.3, 3.5).
    """

    sku: str
    model: str
    name: str
    brand: str
    category: str
    unit: str
    screen_inches: float  # precise viewable diagonal, not rounded (Req 1.4)
    resolution: str  # e.g. "1920x1080"
    max_refresh_hz: Optional[int]
    usb_c_video: bool
    usb_c_pd_watts: int  # upstream host PD; 0 != "no USB charging"
    usb_c_downstream_charge_watts: int
    video_inputs: List[str]
    aliases: List[str]
    source_id: str
    source_url: str
    unit_price_cents: int  # synthetic SGD cents
    evidence: List[Evidence]
    stock_quantity: Optional[int] = None  # always None (Req 1.3, 3.5)
    delivery_lead_days: Optional[int] = None


@dataclass(frozen=True)
class Rules:
    """Synthetic pricing/rule metadata (Req 1.5)."""

    currency: str  # "SGD"
    discount_limit_bps: int  # 500
    default_discount_bps: int  # 0
    rounding: str  # "half_up_per_line_discount"
    shipping_fee_cents: int  # 0
    validity_days: int  # 7
    tax_mode: str  # "not_modelled"
    source_type: str  # "synthetic"


@dataclass(frozen=True)
class QuoteLine:
    """A single computed line of a quote draft (Req 4.3)."""

    sku: str
    name: str
    quantity: int
    unit_price_cents: int
    discount_bps: int
    gross_cents: int
    discount_cents: int
    net_cents: int


@dataclass(frozen=True)
class QuoteDraft:
    """A draft (unsaved, unconfirmed) quote calculation (Req 4.4, 4.8, 4.10)."""

    currency: str
    lines: List[QuoteLine]
    total_cents: int
    within_budget: Optional[bool]
    over_budget_cents: Optional[int]
    validity_days: int
    tax_note: str
    disclaimer: str
    status: str = "draft"
    is_confirmed: bool = False
