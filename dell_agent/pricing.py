"""Deterministic pricing core (Decimal half-up).

The money core of the Dell Quotation Agent. All monetary values are integer
cents; discount rounding uses ``Decimal`` with ``ROUND_HALF_UP`` applied
per-line (Req 4.2, 4.3, 4.4). No third-party dependencies — only the standard
library ``decimal`` module.

Design principle (Req 4): deterministic tools own all money. Nothing here does
floating-point arithmetic on cents, and every value returned is a Python ``int``
(no ``float``/``Decimal`` leaking out).
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional

from .models import QuoteDraft, QuoteLine, Rules

_DISCLAIMER = "synthetic demo, not a tax invoice"
_DEFAULT_TAX_NOTE = "tax not modelled (synthetic demo)"


def line_discount_cents(gross_cents: int, discount_bps: int) -> int:
    """Half-up rounded discount amount in integer cents (Req 4.3, Property 4).

    Computes ``round_half_up(gross_cents * discount_bps / 10000)`` using
    ``Decimal`` so the result is deterministic and independently reproducible.
    """
    raw = Decimal(gross_cents) * Decimal(discount_bps) / Decimal(10000)
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_line(
    sku: str,
    name: str,
    unit_price_cents: int,
    quantity: int,
    discount_bps: int,
) -> QuoteLine:
    """Compute one quote line (Req 4.3, Property 1).

    gross = unit_price_cents * quantity; discount = half-up(gross, bps);
    net = gross - discount. All values are integer cents.
    """
    gross_cents = unit_price_cents * quantity
    discount_cents = line_discount_cents(gross_cents, discount_bps)
    net_cents = gross_cents - discount_cents
    return QuoteLine(
        sku=sku,
        name=name,
        quantity=quantity,
        unit_price_cents=unit_price_cents,
        discount_bps=discount_bps,
        gross_cents=gross_cents,
        discount_cents=discount_cents,
        net_cents=net_cents,
    )


def compute_quote(
    lines: List[QuoteLine],
    rules: Rules,
    budget_cents: Optional[int] = None,
) -> QuoteDraft:
    """Aggregate lines into a draft quote (Req 4.4, 4.8, 4.10).

    total = sum(line nets) + shipping_fee_cents (0); tax is not modelled. When
    ``budget_cents`` is provided, reports ``within_budget`` and
    ``over_budget_cents`` (Property 10); otherwise both are ``None``.
    """
    subtotal_cents = sum(line.net_cents for line in lines)
    total_cents = int(subtotal_cents + rules.shipping_fee_cents)

    within_budget: Optional[bool] = None
    over_budget_cents: Optional[int] = None
    if budget_cents is not None:
        within_budget = total_cents <= budget_cents
        over_budget_cents = max(total_cents - budget_cents, 0)

    tax_note = getattr(rules, "tax_note", None) or _DEFAULT_TAX_NOTE

    return QuoteDraft(
        currency=rules.currency,
        lines=list(lines),
        total_cents=total_cents,
        within_budget=within_budget,
        over_budget_cents=over_budget_cents,
        validity_days=rules.validity_days,
        tax_note=tax_note,
        disclaimer=_DISCLAIMER,
        status="draft",
        is_confirmed=False,
    )
