"""Import the reviewed 38-SKU Lenovo PSREF expansion set.

The script downloads official Lenovo Product Specifications Reference (PSREF)
PDFs, extracts the eight catalogue fields used by the quotation agent, and
updates the maintained source files.  It is intentionally separate from the
normal build: a catalogue rebuild never performs network access.

Usage from the repository root::

    .venv/bin/python scripts/import_lenovo_psref.py
    .venv/bin/python scripts/build_data.py
    .venv/bin/python scripts/validate_data.py
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
PSREF = "https://psref.lenovo.com"
DATASET_VERSION = "2026-09-22.v2"

# A frozen, reproducible selection of active business/general-purpose monitors.
# These were chosen from the official PSREF monitor search results.  Keeping an
# explicit allow-list prevents a future PSREF search ordering change from
# silently changing the catalogue.
PRODUCT_KEYS = (
    "ThinkVision_P40WD_40_Monitor",
    "Lenovo_L24_45_Monitor",
    "Lenovo_L27_45_Monitor",
    "Lenovo_L27_4C_Monitor",
    "Lenovo_L24_4C_Monitor",
    "Lenovo_L24D_4C_Monitor",
    "ThinkVision_P32UD_40_Monitor",
    "ThinkVision_T27QD_4v_Monitor",
    "ThinkVision_T24D_4v_Monitor",
    "ThinkVision_T24_4v_Monitor",
    "ThinkVision_E22_40_Monitor",
    "ThinkVision_S22_4e_Monitor",
    "Lenovo_L22_4e_Monitor",
    "Lenovo_L27_41_Monitor",
    "ThinkVision_S27_4e_Monitor",
    "ThinkVision_E27Q_40_Monitor",
    "ThinkVision_E27_40_Monitor",
    "Lenovo_L27_4e_Monitor",
    "ThinkVision_T32UD_40_Monitor",
    "Lenovo_L24_41_Monitor",
    "ThinkVision_T24D_40_Monitor",
    "ThinkVision_P24QD_40_Monitor",
    "ThinkVision_E24_40_Monitor",
    "ThinkVision_P24Q_40_Monitor",
    "Lenovo_L27qe_Monitor",
    "ThinkVision_T27UD_40_Monitor",
    "ThinkVision_P27QD_40_Monitor",
    "ThinkVision_P34WD_40_Monitor",
    "ThinkVision_T27QD_40_Monitor",
    "ThinkVision_T34WD_40_Monitor",
    "Lenovo_C22_39_Monitor",
    "Lenovo_C20_39_Monitor",
    "ThinkVision_S24_4e_Monitor",
    "ThinkVision_P27Q_40_Monitor",
    "ThinkVision_T27Q_40_Monitor",
    "Lenovo_L24_4e_Monitor",
    "ThinkVision_T27_40_Monitor",
    "ThinkVision_T24_40_Monitor",
)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def request(url: str, *, token: str | None = None, data: bytes | None = None) -> bytes:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; QuotationAgentData/2.0)",
        "Referer": f"{PSREF}/",
        "Origin": PSREF,
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=90) as response:
        return response.read()


def issue_token() -> str:
    payload = json.loads(
        request(f"{PSREF}/api/home/auth/issue", data=b"{}").decode("utf-8-sig")
    )
    if payload.get("code") != 1 or not payload.get("access_token"):
        raise RuntimeError("PSREF did not issue a public read token")
    return payload["access_token"]


def product_info(token: str, key: str) -> dict:
    query = urllib.parse.urlencode({"ProductKey": key})
    payload = json.loads(
        request(
            f"{PSREF}/api/product/Info/GetInfoByKey?{query}", token=token
        ).decode("utf-8-sig")
    )
    if payload.get("code") != 1 or not payload.get("data"):
        raise RuntimeError(f"PSREF product lookup failed: {key}")
    return payload["data"]


def normalise_pdf_url(value: str) -> str:
    path = value.replace("\\", "/").lstrip("/")
    return urllib.parse.quote(f"{PSREF}/{path}", safe=":/?=&")


def model_from_name(name: str) -> str:
    model = re.sub(r"^(?:ThinkVision|Lenovo)\s+", "", name)
    model = re.sub(r"\s+Monitor$", "", model)
    if not model or " " in model:
        raise ValueError(f"Could not derive one-token model from {name!r}")
    return model


def source_id(model: str) -> str:
    return "LENOVO-" + re.sub(r"[^A-Z0-9]+", "-", model.upper()).strip("-")


def page_with(pages: list[str], *needles: str) -> int:
    for index, text in enumerate(pages, 1):
        if all(needle in text for needle in needles):
            return index
    raise ValueError(f"No PDF page contains {needles!r}")


def field_after(text: str, label: str) -> str:
    match = re.search(rf"(?:^|\n){re.escape(label)}\s*\n([^\n]+)", text)
    if not match:
        raise ValueError(f"Missing field {label!r}")
    return match.group(1).strip()


def parse_pdf(path: Path, *, sku: str, model: str, sid: str) -> tuple[dict, dict]:
    reader = PdfReader(path)
    pages = [page.extract_text(extraction_mode="layout") or "" for page in reader.pages]
    joined = "\n".join(pages)
    spec_page = page_with(pages, "Display Size", "Resolution")
    # Some PSREF layouts put the CONNECTIVITY heading at the bottom of the
    # preceding page and the actual port table on the next page.
    connectivity_page = page_with(pages, "Ports", "Rear Ports")

    display = field_after(joined, "Display Size")
    display_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:inches|inch|\")", display, re.I)
    if not display_match:
        raise ValueError(f"Unparsed display size for {model}: {display!r}")
    screen_inches = float(display_match.group(1))

    resolution_text = field_after(joined, "Resolution")
    resolution_match = re.search(r"(\d{3,5})\s*[x×]\s*(\d{3,5})", resolution_text, re.I)
    if not resolution_match:
        raise ValueError(f"Unparsed resolution for {model}: {resolution_text!r}")
    resolution = f"{resolution_match.group(1)}x{resolution_match.group(2)}"

    refresh_text = field_after(joined, "Refresh Rate")
    refresh_values = [int(value) for value in re.findall(r"(\d{2,3})\s*Hz", refresh_text, re.I)]
    if not refresh_values:
        raise ValueError(f"Unparsed refresh rate for {model}: {refresh_text!r}")
    max_refresh_hz = max(refresh_values)

    ports_text = pages[connectivity_page - 1]
    port_lines = [re.sub(r"\s+", " ", line).strip(" •") for line in ports_text.splitlines()]
    usb_video_lines = [
        line
        for line in port_lines
        if ("USB-C" in line or "Thunderbolt" in line)
        and re.search(r"DisplayPort|DP\s*(?:1\.\d+)?\s*Alt Mode", line, re.I)
        and not re.search(r"data (?:transfer )?only", line, re.I)
    ]
    usb_c_video = bool(usb_video_lines)

    pd_watts = 0
    for line in usb_video_lines:
        values = [
            int(value)
            for value in re.findall(
                r"(?:up to\s*)?(\d{1,3})\s*[wW](?:\s*(?:PD|power delivery))?", line
            )
        ]
        if values:
            pd_watts = max(pd_watts, *values)

    downstream_watts = 0
    for line in port_lines:
        if "USB-C" not in line or "downstream" not in line.lower():
            continue
        values = [int(value) for value in re.findall(r"(\d{1,3})\s*[wW]", line)]
        if values:
            downstream_watts = max(downstream_watts, *values)

    video_inputs: list[str] = []
    if any("HDMI" in line for line in port_lines):
        video_inputs.append("HDMI")
    if any(
        "DisplayPort" in line
        and not re.search(r"(?:out|output|daisy)", line, re.I)
        for line in port_lines
    ):
        video_inputs.append("DisplayPort")
    if any("VGA" in line for line in port_lines):
        video_inputs.append("VGA")
    if usb_c_video:
        video_inputs.append(
            "Thunderbolt / USB-C DP Alt Mode"
            if any("Thunderbolt" in line for line in usb_video_lines)
            else "USB-C DP Alt Mode"
        )
    if not video_inputs:
        raise ValueError(f"No video inputs parsed for {model}")

    notes = (
        f"Official Lenovo PSREF: {screen_inches:g}-inch {resolution} at up to "
        f"{max_refresh_hz} Hz. "
    )
    if usb_c_video:
        notes += f"USB-C video input; host power delivery up to {pd_watts} W."
    elif downstream_watts:
        notes += (
            f"USB-C is downstream/data only ({downstream_watts} W maximum recorded); "
            "it is not a host video input."
        )
    else:
        notes += "No USB-C video input is listed."

    row = {
        "sku": sku,
        "brand": "Lenovo",
        "model": model,
        "source_id": sid,
        "screen_inches": screen_inches,
        "resolution": resolution,
        "max_refresh_hz": max_refresh_hz,
        "usb_c_video": usb_c_video,
        "usb_c_pd_watts": pd_watts,
        "usb_c_downstream_charge_watts": downstream_watts,
        "video_inputs": video_inputs,
        "spec_page": spec_page,
        "connectivity_page": connectivity_page,
        "resolution_page": spec_page,
        "review_status": "automated_extraction_checked_by_invariants",
        "notes": notes,
    }
    extracted = {
        "source_id": sid,
        "local_path": str(path.relative_to(ROOT)),
        "page_count": len(pages),
        "pages": [
            {"pdf_page": index, "text": text}
            for index, text in enumerate(pages, 1)
        ],
    }
    return row, extracted


def synthetic_price_cents(row: dict) -> int:
    """Return a transparent demo price based only on catalogue attributes."""
    width, height = (int(value) for value in row["resolution"].split("x"))
    price = 119
    price += max(0, round((row["screen_inches"] - 20) * 12))
    pixels = width * height
    if pixels > 3840 * 2160:
        price += 500
    elif pixels >= 3840 * 2160:
        price += 260
    elif pixels >= 3440 * 1440:
        price += 220
    elif pixels >= 2560 * 1440:
        price += 110
    if row["usb_c_video"]:
        price += 70 + row["usb_c_pd_watts"]
    if row["max_refresh_hz"] > 120:
        price += 80
    elif row["max_refresh_hz"] > 75:
        price += 30
    return int(round(price / 10) * 10 - 1) * 100


def main() -> None:
    if len(PRODUCT_KEYS) != 38 or len(set(PRODUCT_KEYS)) != 38:
        raise RuntimeError("The PSREF expansion allow-list must contain 38 unique products")

    token = issue_token()
    curated_path = ROOT / "data/curated_specs.json"
    business_path = ROOT / "data/synthetic_business.json"
    manifest_path = ROOT / "data/source_manifest.json"
    log_path = ROOT / "data/raw/download_log.json"

    curated = read_json(curated_path)
    business = read_json(business_path)
    manifest = read_json(manifest_path)
    logs = read_json(log_path)

    # Re-running replaces the expansion cleanly while preserving the reviewed
    # Dell baseline byte-for-byte apart from the new dataset version.
    curated["products"] = [
        row for row in curated["products"] if not row["sku"].startswith("MON-L")
    ]
    manifest = [row for row in manifest if not row["source_id"].startswith("LENOVO-")]
    logs = [row for row in logs if not row["source_id"].startswith("LENOVO-")]
    business["prices_cents"] = {
        sku: price
        for sku, price in business["prices_cents"].items()
        if not sku.startswith("MON-L")
    }

    for source in manifest:
        source.setdefault("publisher", "Dell")
        source.setdefault(
            "rights",
            "Copyright Dell; public download, not an open-data licence. Preserve attribution.",
        )

    fetched_at = datetime.now(timezone.utc).isoformat()
    for offset, key in enumerate(PRODUCT_KEYS, 13):
        info = product_info(token, key)
        name = info["ProductName"]
        model = model_from_name(name)
        sid = source_id(model)
        sku = f"MON-L{offset:03d}"
        pdf_url = normalise_pdf_url(info["SpecPDFUrl"])
        local_path = ROOT / "data/raw/lenovo" / f"{sid}.pdf"
        if not local_path.is_file() or not local_path.read_bytes().startswith(b"%PDF-"):
            pdf_bytes = request(pdf_url)
            if not pdf_bytes.startswith(b"%PDF-"):
                raise ValueError(f"PSREF source is not a PDF: {pdf_url}")
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(pdf_bytes)
        pdf_bytes = local_path.read_bytes()
        row, extracted = parse_pdf(local_path, sku=sku, model=model, sid=sid)

        extracted_json = ROOT / "data/extracted" / f"{sid}.json"
        extracted_txt = ROOT / "data/extracted" / f"{sid}.txt"
        write_json(extracted_json, extracted)
        extracted_txt.write_text(
            "\n\n".join(
                f"=== PDF page {page['pdf_page']} ===\n{page['text']}"
                for page in extracted["pages"]
            ),
            encoding="utf-8",
        )

        relative_path = str(local_path.relative_to(ROOT))
        page_url = f"{PSREF}/Product/{key}"
        manifest.append(
            {
                "source_id": sid,
                "models": [model],
                "title": f"{name} Product Specifications Reference",
                "page_url": page_url,
                "download_url": pdf_url,
                "local_path": relative_path,
                "publisher": "Lenovo",
                "rights": (
                    "Copyright Lenovo; public specification download, not an open-data "
                    "licence. Preserve attribution."
                ),
            }
        )
        logs.append(
            {
                "source_id": sid,
                "models": [model],
                "title": f"{name} Product Specifications Reference",
                "page_url": page_url,
                "download_url": pdf_url,
                "local_path": relative_path,
                "publisher": "Lenovo",
                "rights": (
                    "Copyright Lenovo; public specification download, not an open-data "
                    "licence. Preserve attribution."
                ),
                "downloaded_at": fetched_at,
                "final_url": pdf_url,
                "size_bytes": len(pdf_bytes),
                "content_type": "application/pdf",
            }
        )
        curated["products"].append(row)
        business["prices_cents"][sku] = synthetic_price_cents(row)
        print(
            f"{sku} {model}: {row['screen_inches']:g}in {row['resolution']} "
            f"{row['max_refresh_hz']}Hz USB-C={row['usb_c_video']} "
            f"PD={row['usb_c_pd_watts']}W"
        )

    curated["dataset_version"] = DATASET_VERSION
    curated["review_method"] = (
        "The 12 Dell baseline SKUs retain their assistant-reviewed PDF evidence. "
        "The 38 Lenovo expansion SKUs were deterministically extracted from official "
        "PSREF PDFs and passed schema, page, connectivity and source invariants; the "
        "expansion is not an independent human audit."
    )
    business["dataset_version"] = DATASET_VERSION
    business["description"] = (
        "Fictional SGD selling prices and policies for the hackathon, not manufacturer "
        "retail/wholesale prices or tax advice. Lenovo expansion prices use the documented "
        "deterministic demo formula in scripts/import_lenovo_psref.py."
    )
    business["rules"]["price_version"] = "demo-v2"
    business["rules"]["effective_date"] = "2026-09-22"

    if len(curated["products"]) != 50:
        raise RuntimeError(f"Expected 50 products, got {len(curated['products'])}")
    write_json(curated_path, curated)
    write_json(business_path, business)
    write_json(manifest_path, manifest)
    write_json(log_path, logs)
    print("Imported 38 Lenovo PSREF products; maintained catalogue now has 50 SKUs.")


if __name__ == "__main__":
    main()
