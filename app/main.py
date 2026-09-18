"""FastAPI entry point for the quotation workbench."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from dell_agent.agent.tools import dispatch

from .config import ROOT, load_settings
from .repository import Repository
from .service import QuotationService

settings = load_settings()
repository = Repository(settings.app_db_path)
service = QuotationService(repository, settings)
STATIC_DIR = Path(__file__).resolve().parent / "static"
SOURCES = {
    row["source_id"]: row
    for row in json.loads((ROOT / "data/source_manifest.json").read_text(encoding="utf-8"))
}

app = FastAPI(
    title="Dell Quotation Workbench",
    version="0.1.0",
    description="Evidence-backed product selection and deterministic demo pricing.",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ConversationCreate(BaseModel):
    driver: Literal["offline", "converse"] | None = None


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class QuoteRequest(BaseModel):
    items: list[dict[str, Any]] = Field(min_length=1)
    budget_cents: int | None = Field(default=None, ge=0)


class SaveQuoteRequest(BaseModel):
    result_message_id: str = Field(min_length=1)


def fail(status: int, error: str, message: str) -> None:
    raise HTTPException(status_code=status, detail={"error": error, "message": message})


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    location = ".".join(str(part) for part in first.get("loc", []) if part != "body")
    message = first.get("msg", "Request validation failed.")
    if location:
        message = f"{location}: {message}"
    return JSONResponse(
        status_code=422,
        content={"detail": {"error": "bad_argument", "message": message}},
    )


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "dataset_version": "2026-09-14.v1",
        "configured_driver": settings.agent_driver,
        "bedrock_configured": bool(settings.bedrock_model_id and settings.aws_region),
        "database": str(settings.app_db_path),
    }


@app.get("/api/products")
def products(
    query: str | None = None,
    usb_c_video: bool | None = None,
    min_pd_watts: int | None = Query(default=None, ge=0),
    min_screen_inches: float | None = Query(default=None, gt=0),
    max_screen_inches: float | None = Query(default=None, gt=0),
    resolution: str | None = None,
    min_refresh_hz: int | None = Query(default=None, ge=0),
    max_unit_price_cents: int | None = Query(default=None, ge=0),
) -> list[dict[str, Any]]:
    arguments = {
        key: value
        for key, value in locals().items()
        if value is not None
    }
    result = dispatch("search_products", arguments)
    if isinstance(result, dict) and "error" in result:
        fail(422, result["error"], result.get("message", "Invalid product filter."))
    return result


@app.get("/api/products/{sku}")
def product(sku: str) -> dict[str, Any]:
    result = dispatch("get_product", {"sku": sku})
    if not result.get("found"):
        fail(404, "not_found", f"Product {sku} was not found.")
    source_id = result["evidence"][0]["source_id"] if result.get("evidence") else None
    if source_id:
        for evidence in result["evidence"]:
            evidence["local_pdf_url"] = f"/api/sources/{source_id}/pdf#page={evidence['pdf_page']}"
    return result


@app.get("/api/sources/{source_id}/pdf", include_in_schema=False)
def source_pdf(source_id: str) -> FileResponse:
    source = SOURCES.get(source_id)
    if source is None:
        fail(404, "not_found", "Source document was not found.")
    path = (ROOT / source["local_path"]).resolve()
    raw_root = (ROOT / "data/raw").resolve()
    if raw_root not in path.parents or not path.is_file():
        fail(404, "not_found", "Source document is unavailable.")
    return FileResponse(path, media_type="application/pdf")


@app.get("/api/conversations")
def conversations(limit: int = Query(default=20, ge=1, le=100)) -> list[dict[str, Any]]:
    return repository.list_conversations(limit)


@app.post("/api/conversations", status_code=201)
def create_conversation(body: ConversationCreate | None = None) -> dict[str, Any]:
    driver = body.driver if body and body.driver else settings.agent_driver
    return repository.create_conversation(driver)


@app.get("/api/conversations/{conversation_id}")
def conversation(conversation_id: str) -> dict[str, Any]:
    result = repository.get_conversation(conversation_id)
    if result is None:
        fail(404, "not_found", "Conversation was not found.")
    return result


@app.post("/api/conversations/{conversation_id}/messages")
def add_message(conversation_id: str, body: MessageCreate) -> dict[str, Any]:
    content = body.content.strip()
    if not content:
        fail(422, "bad_argument", "Message content cannot be blank.")
    result = service.process_message(conversation_id, content)
    if result is None:
        fail(404, "not_found", "Conversation was not found.")
    return result


@app.post("/api/quotes/calculate")
def calculate_quote(body: QuoteRequest) -> dict[str, Any]:
    arguments: dict[str, Any] = {"items": body.items}
    if body.budget_cents is not None:
        arguments["budget_cents"] = body.budget_cents
    result = dispatch("calculate_quote", arguments)
    if "error" in result:
        fail(422, result["error"], result.get("message", "Quote cannot be calculated."))
    return result


@app.post("/api/conversations/{conversation_id}/quotes", status_code=201)
def save_quote(conversation_id: str, body: SaveQuoteRequest) -> dict[str, Any]:
    quote, error = repository.save_latest_quote(conversation_id, body.result_message_id)
    if error == "not_found":
        fail(404, "not_found", "Conversation was not found.")
    if error == "stale_draft":
        fail(409, "stale_draft", "The displayed draft is no longer the latest result. Refresh before saving.")
    if error == "no_draft":
        fail(409, "no_draft", "The latest turn has no calculated quote to save.")
    return quote  # type: ignore[return-value]


@app.get("/api/quotes/{quote_id}")
def quote(quote_id: str) -> dict[str, Any]:
    result = repository.get_quote(quote_id)
    if result is None:
        fail(404, "not_found", "Quote version was not found.")
    return result
