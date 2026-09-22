"""Catalogue loading and cached access.

Parses ``catalog.json`` (the evidence-backed source of truth) into typed
:class:`~dell_agent.models.Product` objects and loads the synthetic pricing
:class:`~dell_agent.models.Rules`. Uses only the Python standard library
(``json``, ``dataclasses``, ``functools``, ``pathlib``).

Design principle (Req 1.3, 1.4): unknown facts stay ``None`` (never coerced to
``0`` / ``False``); ``screen_inches`` keeps its precise manual value and is never
rounded to a marketed size class.

Fail-fast schema validation (Req 1.6) is layered on top of this module in
task 3.2; :class:`CatalogError` is defined here so it can be imported now.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dell_agent.models import Evidence, Product, Rules

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

_DATA_DIR = Path(__file__).resolve().parent
DEFAULT_CATALOG_PATH = _DATA_DIR / "agent" / "catalog.json"
DEFAULT_RULES_PATH = _DATA_DIR / "processed" / "pricing_rules.json"


class CatalogError(Exception):
    """Raised when the catalogue or rules cannot be loaded or validated.

    Fail-fast semantics (Req 1.6): the system refuses to serve partial data
    rather than silently degrading.
    """


# --------------------------------------------------------------------------- #
# Builders (JSON dict -> typed dataclass)
# --------------------------------------------------------------------------- #

# Fields consumed directly off each product record; ``price`` and ``evidence``
# are handled separately. Any other JSON keys (retrieved_at, notes,
# dataset_version, source_type, ...) are intentionally ignored.
_PRODUCT_FIELDS = (
    "sku",
    "model",
    "name",
    "brand",
    "category",
    "unit",
    "resolution",
    "usb_c_video",
    "usb_c_pd_watts",
    "usb_c_downstream_charge_watts",
    "video_inputs",
    "aliases",
    "source_id",
    "source_url",
)


def _build_evidence(raw: dict) -> Evidence:
    """Build an :class:`Evidence` from a catalog evidence entry.

    ``pdf_page`` may legitimately be ``None`` (Req 3.2 allows null pages).
    """
    return Evidence(
        sku=raw["sku"],
        field=raw["field"],
        value=raw.get("value"),
        source_id=raw["source_id"],
        pdf_page=raw.get("pdf_page"),  # may be None
        source_url=raw.get("source_url", ""),
        method=raw.get("method", ""),
        note=raw.get("note", "") or "",
    )


def _build_product(raw: dict) -> Product:
    """Build a :class:`Product` from a catalog product record.

    Lifts ``price.unit_price_cents`` onto the product and converts the
    ``evidence[]`` array into :class:`Evidence` objects. ``screen_inches`` is
    read verbatim (kept precise, never rounded). Unknown facts stay ``None``.
    """
    price = raw.get("price") or {}
    unit_price_cents = price.get("unit_price_cents")

    evidence: List[Evidence] = [
        _build_evidence(e) for e in raw.get("evidence", []) or []
    ]

    # Keep screen_inches precise: preserve the manual value as given. JSON may
    # encode it as an int (e.g. 27) or float (e.g. 23.81); we do not round.
    screen_inches = raw.get("screen_inches")

    return Product(
        sku=raw["sku"],
        model=raw["model"],
        name=raw["name"],
        brand=raw["brand"],
        category=raw["category"],
        unit=raw["unit"],
        screen_inches=screen_inches,
        resolution=raw["resolution"],
        max_refresh_hz=raw.get("max_refresh_hz"),  # may be None
        usb_c_video=raw["usb_c_video"],
        usb_c_pd_watts=raw["usb_c_pd_watts"],
        usb_c_downstream_charge_watts=raw["usb_c_downstream_charge_watts"],
        video_inputs=list(raw.get("video_inputs") or []),
        aliases=list(raw.get("aliases") or []),
        source_id=raw["source_id"],
        source_url=raw["source_url"],
        unit_price_cents=unit_price_cents,
        evidence=evidence,
        # Unknown facts preserved as None (Req 1.3); never coerce to 0/false.
        stock_quantity=raw.get("stock_quantity"),
        delivery_lead_days=raw.get("delivery_lead_days"),
    )


def _build_rules(raw: dict) -> Rules:
    """Build a :class:`Rules` from a rules block (embedded or standalone)."""
    return Rules(
        currency=raw["currency"],
        discount_limit_bps=raw["discount_limit_bps"],
        default_discount_bps=raw["default_discount_bps"],
        rounding=raw["rounding"],
        shipping_fee_cents=raw["shipping_fee_cents"],
        validity_days=raw["validity_days"],
        tax_mode=raw["tax_mode"],
        source_type=raw["source_type"],
        rule_version=raw["rule_version"],
        price_version=raw["price_version"],
        effective_date=raw["effective_date"],
        tax_note=raw["tax_note"],
        confirmation_required=raw["confirmation_required"],
        inventory_mode=raw["inventory_mode"],
        delivery_commitment=raw["delivery_commitment"],
    )


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #

# Number of SKUs the frozen catalogue must contain (Req 1.1, 1.6).
EXPECTED_PRODUCT_COUNT = 50

# The synthetic discount ceiling the rules block must declare (Req 1.5, 1.6).
EXPECTED_DISCOUNT_LIMIT_BPS = 500


def doc_version_is_valid(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


# Product-record keys that must be present for a record to be usable. Mirrors
# the model contract in Req 1.2 (``price`` supplies ``unit_price_cents`` and is
# validated separately below).
_REQUIRED_PRODUCT_KEYS = (
    "sku",
    "model",
    "name",
    "brand",
    "category",
    "unit",
    "screen_inches",
    "resolution",
    "usb_c_video",
    "usb_c_pd_watts",
    "usb_c_downstream_charge_watts",
    "video_inputs",
    "aliases",
    "source_id",
    "source_url",
)


def _validate_catalog(raw_products: List[dict], raw_rules: Optional[dict], path: Path) -> None:
    """Fail-fast schema validation for the raw catalogue (Req 1.6).

    Raises :class:`CatalogError` if any of the following hold:
      * the product count is not exactly :data:`EXPECTED_PRODUCT_COUNT`;
      * two records share a SKU (duplicate SKUs);
      * a record is missing a required field (including ``price.unit_price_cents``);
      * the rules block declares ``discount_limit_bps`` != 500.

    The system refuses to serve partial or corrupted data rather than silently
    degrading.
    """
    if len(raw_products) != EXPECTED_PRODUCT_COUNT:
        raise CatalogError(
            f"Catalogue {path} must contain exactly {EXPECTED_PRODUCT_COUNT} "
            f"products, found {len(raw_products)}."
        )

    seen: set = set()
    for raw in raw_products:
        for key in _REQUIRED_PRODUCT_KEYS:
            if key not in raw:
                raise CatalogError(
                    f"Catalogue record missing required field '{key}' in {path}."
                )
        sku = raw["sku"]
        if sku in seen:
            raise CatalogError(f"Duplicate SKU '{sku}' in catalogue {path}.")
        seen.add(sku)

        price = raw.get("price")
        if not isinstance(price, dict) or price.get("unit_price_cents") is None:
            raise CatalogError(
                f"Catalogue record '{sku}' missing required field "
                f"'price.unit_price_cents' in {path}."
            )

    # The discount ceiling and provenance fields are hard invariants of the
    # synthetic rule set used in quote snapshots.
    if raw_rules is not None:
        limit = raw_rules.get("discount_limit_bps")
        if limit != EXPECTED_DISCOUNT_LIMIT_BPS:
            raise CatalogError(
                f"Rules discount_limit_bps must be {EXPECTED_DISCOUNT_LIMIT_BPS}, "
                f"found {limit!r}."
            )
        required_rule_fields = (
            "rule_version", "price_version", "effective_date", "tax_note",
            "confirmation_required", "inventory_mode", "delivery_commitment",
        )
        missing = [field for field in required_rule_fields if field not in raw_rules]
        if missing:
            raise CatalogError(
                "Rules block missing snapshot metadata: " + ", ".join(missing) + "."
            )
        if not doc_version_is_valid(raw_rules.get("rule_version")) or not doc_version_is_valid(raw_rules.get("price_version")):
            raise CatalogError("Rules version fields must be non-empty strings.")


def _read_json(path: Path) -> dict:
    """Read and parse a JSON file, raising :class:`CatalogError` on failure."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError as exc:
        raise CatalogError(f"Catalogue data file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CatalogError(f"Invalid JSON in {path}: {exc}") from exc


def load_catalog(
    path: Optional[Path] = None,
    rules_path: Optional[Path] = None,
) -> Tuple[Dict[str, Product], Rules]:
    """Load the catalogue and rules from disk.

    Parses ``catalog.json`` into a ``{sku: Product}`` mapping and loads the
    pricing :class:`Rules` from the catalog's embedded ``rules`` block, falling
    back to a standalone ``pricing_rules.json`` when the embedded block is
    absent.

    Args:
        path: Optional override for ``catalog.json``.
        rules_path: Optional override for the standalone ``pricing_rules.json``
            fallback.

    Returns:
        A tuple of ``(products_by_sku, rules)``.

    Raises:
        CatalogError: if a data file is missing, is not valid JSON, or a record
            is missing a required field.
    """
    catalog_path = Path(path) if path is not None else DEFAULT_CATALOG_PATH
    rules_file = Path(rules_path) if rules_path is not None else DEFAULT_RULES_PATH

    doc = _read_json(catalog_path)
    dataset_version = doc.get("dataset_version")
    if not doc_version_is_valid(dataset_version):
        raise CatalogError(
            f"Catalogue {catalog_path} requires a non-empty dataset_version."
        )

    raw_products = doc.get("products")
    if not isinstance(raw_products, list):
        raise CatalogError(
            f"Catalogue {catalog_path} has no 'products' array."
        )

    # Rules: prefer the embedded block, fall back to standalone file (Req 1.5).
    raw_rules = doc.get("rules")
    if not raw_rules:
        raw_rules = _read_json(rules_file)

    # Fail-fast schema validation before building any typed objects (Req 1.6).
    _validate_catalog(raw_products, raw_rules, catalog_path)

    products: Dict[str, Product] = {}
    try:
        for raw in raw_products:
            product = _build_product(raw)
            products[product.sku] = product
    except KeyError as exc:
        raise CatalogError(
            f"Catalogue record missing required field {exc} in {catalog_path}."
        ) from exc

    try:
        rules = _build_rules(raw_rules)
    except KeyError as exc:
        raise CatalogError(f"Rules block missing required field {exc}.") from exc

    return products, rules


# --------------------------------------------------------------------------- #
# Module-level cached access
# --------------------------------------------------------------------------- #

@lru_cache(maxsize=1)
def _cache() -> Tuple[Dict[str, Product], Rules]:
    """Load the catalogue once and cache it for the process lifetime."""
    return load_catalog()


def all_products() -> List[Product]:
    """Return all catalogue products (Req 1.1)."""
    products, _ = _cache()
    return list(products.values())


def get(sku: str) -> Optional[Product]:
    """Return the product for ``sku`` or ``None`` if it is not in the catalogue."""
    products, _ = _cache()
    return products.get(sku)


def rules() -> Rules:
    """Return the synthetic pricing/rule metadata (Req 1.5)."""
    _, r = _cache()
    return r


@lru_cache(maxsize=1)
def dataset_version() -> str:
    """Return the frozen catalogue dataset version used by quote snapshots."""
    doc = _read_json(DEFAULT_CATALOG_PATH)
    version = doc.get("dataset_version")
    if not doc_version_is_valid(version):
        raise CatalogError("Catalogue requires a non-empty dataset_version.")
    return version


def pricing_context() -> dict:
    """Return immutable server-owned pricing provenance for a quote draft."""
    current = rules()
    return {
        "dataset_version": dataset_version(),
        "price_version": current.price_version,
        "rule_version": current.rule_version,
        "price_effective_date": current.effective_date,
        "rounding": current.rounding,
        "tax_mode": current.tax_mode,
        "source_type": current.source_type,
        "inventory": current.inventory_mode,
        "delivery": current.delivery_commitment,
    }


def reload() -> None:
    """Clear the module-level cache so the next access reloads from disk.

    Primarily useful for tests that swap in a different catalogue file.
    """
    _cache.cache_clear()
    dataset_version.cache_clear()
