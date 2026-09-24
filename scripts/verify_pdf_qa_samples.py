"""Machine-check the stable PDF samples before independent visual review."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
STANDARD = ROOT / "output/pdf/quotation-qa-standard.pdf"
LONG = ROOT / "output/pdf/quotation-qa-long.pdf"
REPORT = ROOT / "reports/evaluation/pdf-machine-precheck.json"


def page_texts(path: Path) -> list[str]:
    return [page.extract_text() or "" for page in PdfReader(str(path)).pages]


def main() -> int:
    standard = page_texts(STANDARD)
    long = page_texts(LONG)
    all_long = "\n".join(long)
    checks = {
        "standard_is_one_page": len(standard) == 1,
        "standard_metadata": all(
            value in standard[0]
            for value in ("Q-20260920-QA-R1", "Café Example", "Sales Admin", "2026-09-27")
        ),
        "standard_line_and_amounts": all(
            value in standard[0]
            for value in ("MON-007", "P2425HE", "SGD 289.00", "SGD 2,312.00")
        ),
        "standard_terms_and_provenance": all(
            value in standard[0]
            for value in ("not a tax invoice", "Stock and delivery timing", "2026-09-14", "demo-policy-2026-09-14")
        ),
        "long_is_five_pages": len(long) == 5,
        "long_header_on_every_page": all("Product" in text and "Unit price" in text for text in long),
        "long_footer_on_every_page": all(
            "Synthetic demo quotation" in text and f"Page {index}" in text
            for index, text in enumerate(long, 1)
        ),
        "long_all_45_rows_present": all(f"line {index}" in all_long for index in range(1, 46)),
        "long_total_and_terms_on_last_page": all(
            value in long[-1]
            for value in ("SGD 104,040.00", "Terms and provenance", "Stock and delivery timing")
        ),
    }
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": {
            str(STANDARD.relative_to(ROOT)): {"pages": len(standard)},
            str(LONG.relative_to(ROOT)): {"pages": len(long)},
        },
        "checks": checks,
        "passed": all(checks.values()),
        "scope": "Machine extraction checks; independent human visual sign-off remains required.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
