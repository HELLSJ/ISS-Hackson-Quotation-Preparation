"""Render one immutable confirmed snapshot as PDF; no catalogue or pricing imports."""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


class PdfRenderError(ValueError):
    pass


def _register_font() -> str:
    candidates = (
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    )
    for path in candidates:
        if path.is_file():
            try:
                pdfmetrics.registerFont(TTFont("QuoteUnicode", str(path)))
                return "QuoteUnicode"
            except Exception:
                continue
    return "Helvetica"


def format_money(cents: int, currency: str) -> str:
    sign = "-" if cents < 0 else ""
    value = abs(cents)
    return f"{sign}{currency} {value // 100:,}.{value % 100:02d}"


def safe_filename(snapshot: dict[str, Any]) -> str:
    number = str(snapshot.get("quote_number") or "quotation")
    safe = "".join(char for char in number if char.isalnum() or char in ("-", "_"))
    return f"{safe or 'quotation'}.pdf"


def render_confirmed_quote(snapshot: dict[str, Any]) -> bytes:
    """Generate a deterministic-layout PDF from frozen confirmed JSON only."""
    if snapshot.get("status") != "confirmed" or snapshot.get("is_confirmed") is not True:
        raise PdfRenderError("Only a confirmed snapshot can be rendered.")
    lines = snapshot.get("lines")
    if not isinstance(lines, list) or not lines:
        raise PdfRenderError("Confirmed snapshot has no quote lines.")

    font = _register_font()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=17 * mm,
        bottomMargin=18 * mm,
        title=str(snapshot.get("quote_number", "Quotation")),
        author="Quotation Preparation Agent",
    )
    styles = getSampleStyleSheet()
    normal = ParagraphStyle("QuoteNormal", parent=styles["BodyText"], fontName=font, fontSize=8.5, leading=11)
    small = ParagraphStyle("QuoteSmall", parent=normal, fontSize=7.5, leading=9, textColor=colors.HexColor("#53616d"))
    heading = ParagraphStyle("QuoteHeading", parent=styles["Title"], fontName=font, fontSize=20, leading=24, textColor=colors.HexColor("#18232e"))
    right = ParagraphStyle("QuoteRight", parent=normal, alignment=TA_RIGHT)
    story = [Paragraph("QUOTATION", heading), Spacer(1, 5 * mm)]

    confirmation = snapshot.get("confirmation") or {}
    customer = snapshot.get("customer") or {}
    meta = [
        ["Quotation", escape(str(snapshot.get("quote_number", ""))), "Version", str(snapshot.get("quote_version", ""))],
        ["Customer", escape(str(customer.get("display_name", ""))), "Currency", escape(str(snapshot.get("currency", "")))],
        ["Quote date", escape(str(snapshot.get("quote_date", ""))), "Valid until", escape(str(snapshot.get("valid_until", "")))],
        ["Confirmed by", escape(str(confirmation.get("confirmed_by", ""))), "Confirmed at", escape(str(confirmation.get("confirmed_at", "")))],
    ]
    meta_table = Table(meta, colWidths=[25 * mm, 62 * mm, 24 * mm, 50 * mm])
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#65727e")),
        ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#65727e")),
        ("LINEBELOW", (0, -1), (-1, -1), 0.6, colors.HexColor("#aab4bd")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.extend([meta_table, Spacer(1, 7 * mm)])

    currency = str(snapshot["currency"])
    rows: list[list[Any]] = [[
        Paragraph("Product", small), Paragraph("Qty", small), Paragraph("Unit price", small),
        Paragraph("Discount", small), Paragraph("Net", small),
    ]]
    for line in lines:
        product = f"<b>{escape(str(line.get('model', '')))}</b><br/>{escape(str(line.get('name', '')))}<br/><font color='#65727e'>{escape(str(line.get('sku', '')))}</font>"
        rows.append([
            Paragraph(product, normal), Paragraph(str(line["quantity"]), right),
            Paragraph(format_money(int(line["unit_price_cents"]), currency), right),
            Paragraph(f"{line['discount_bps'] / 100:.2f}%", right),
            Paragraph(format_money(int(line["net_cents"]), currency), right),
        ])
    item_table = Table(rows, repeatRows=1, colWidths=[76 * mm, 14 * mm, 31 * mm, 22 * mm, 34 * mm])
    item_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf1f4")),
        ("FONTNAME", (0, 0), (-1, -1), font), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#c9d1d8")),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
    ]))
    story.extend([item_table, Spacer(1, 6 * mm)])

    totals = [
        ["Subtotal", format_money(int(snapshot["subtotal_cents"]), currency)],
        ["Shipping", format_money(int(snapshot["shipping_fee_cents"]), currency)],
        ["TOTAL", format_money(int(snapshot["total_cents"]), currency)],
    ]
    total_table = Table(totals, colWidths=[45 * mm, 40 * mm], hAlign="RIGHT")
    total_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#18232e")),
        ("FONTNAME", (0, -1), (-1, -1), font), ("FONTSIZE", (0, -1), (-1, -1), 11),
        ("TOPPADDING", (0, -1), (-1, -1), 7),
    ]))
    story.extend([total_table, Spacer(1, 8 * mm)])

    context = snapshot.get("pricing_context") or {}
    terms = snapshot.get("terms") or {}
    story.extend([
        Paragraph("Terms and provenance", ParagraphStyle("TermsHeading", parent=normal, fontSize=10, leading=13)),
        Spacer(1, 2 * mm),
        Paragraph(escape(str(terms.get("tax_note", snapshot.get("tax_note", "")))), small),
        Paragraph(escape(str(terms.get("disclaimer", snapshot.get("disclaimer", "")))), small),
        Paragraph("Stock and delivery timing: not available; human confirmation required.", small),
        Paragraph(
            "Dataset: " + escape(str(context.get("dataset_version", "unknown")))
            + " · Price: " + escape(str(context.get("price_version", "unknown")))
            + " · Rules: " + escape(str(context.get("rule_version", "unknown"))),
            small,
        ),
    ])

    def page_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(font, 7)
        canvas.setFillColor(colors.HexColor("#65727e"))
        canvas.drawString(16 * mm, 10 * mm, "Synthetic demo quotation · Not a tax invoice")
        canvas.drawRightString(A4[0] - 16 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    return buffer.getvalue()
