"""FastAPI entry point for the quotation workbench."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from dell_agent.agent.tools import dispatch
from dell_agent.data.catalog import dataset_version

from .config import load_settings
from .quote_diff import compare_quotes
from .quote_pdf import PdfRenderError, render_confirmed_quote, safe_filename
from .repository import Repository
from .service import QuotationService

settings = load_settings()
repository = Repository(settings.app_db_path)
service = QuotationService(repository, settings)
STATIC_DIR = Path(__file__).resolve().parent / "static"
app = FastAPI(
    title="Monitor Quotation Workbench",
    version="0.1.0",
    description="Evidence-backed product selection and deterministic demo pricing.",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ConversationCreate(BaseModel):
    driver: Literal["offline", "gateway"] | None = None


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class QuoteRequest(BaseModel):
    items: list[dict[str, Any]] = Field(min_length=1)
    budget_cents: int | None = Field(default=None, ge=0)


class SaveQuoteRequest(BaseModel):
    result_message_id: str = Field(min_length=1)
    customer_display_name: str | None = Field(default=None, max_length=200)


class ConfirmQuoteRequest(BaseModel):
    snapshot_token: str = Field(min_length=64, max_length=64)
    customer_display_name: str = Field(min_length=1, max_length=200)
    confirmed_by: str = Field(min_length=1, max_length=120)


def fail(status: int, error: str, message: str, **extra: Any) -> None:
    detail: dict[str, Any] = {"error": error, "message": message}
    detail.update(extra)
    raise HTTPException(status_code=status, detail=detail)


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
        "dataset_version": dataset_version(),
        "configured_driver": settings.agent_driver,
        "gateway_configured": bool(
            settings.gateway_url and settings.gateway_api_key and settings.llm_model
        ),
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
    return result


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
    quote, error = repository.save_latest_quote(
        conversation_id, body.result_message_id, body.customer_display_name
    )
    if error == "not_found":
        fail(404, "not_found", "Conversation was not found.")
    if error == "stale_draft":
        fail(409, "stale_draft", "The displayed draft is no longer the latest result. Refresh before saving.")
    if error == "save_conflict":
        fail(409, "save_conflict", "This Agent result was already saved with different metadata.")
    if error in {"invalid_snapshot", "not_confirmable"}:
        fail(409, error, "The calculated draft is incomplete or inconsistent and cannot be saved.")
    if error == "no_draft":
        fail(409, "no_draft", "The latest turn has no calculated quote to save.")
    return quote  # type: ignore[return-value]


@app.get("/api/quotes/{quote_id}")
def quote(quote_id: str) -> dict[str, Any]:
    result = repository.get_quote(quote_id)
    if result is None:
        fail(404, "not_found", "Quote version was not found.")
    return result


@app.post("/api/quotes/{quote_id}/confirm")
def confirm_quote(quote_id: str, body: ConfirmQuoteRequest) -> dict[str, Any]:
    result, error, missing_fields = repository.confirm_quote(
        quote_id,
        body.snapshot_token,
        body.customer_display_name,
        body.confirmed_by,
    )
    if error == "not_found":
        fail(404, "not_found", "Quote version was not found.")
    if error == "already_confirmed":
        fail(409, "already_confirmed", "This quote was already confirmed with different confirmation details.")
    if error == "stale_confirmation":
        fail(409, "stale_confirmation", "This is not the latest unconfirmed snapshot or the token is stale.")
    if error in {"not_confirmable", "invalid_snapshot"}:
        fail(409, error, "The saved snapshot is incomplete and cannot be confirmed.", missing_fields=missing_fields)
    return result  # type: ignore[return-value]


@app.get("/api/quotes/{from_quote_id}/diff/{to_quote_id}")
def quote_diff(from_quote_id: str, to_quote_id: str) -> dict[str, Any]:
    before = repository.get_quote(from_quote_id)
    after = repository.get_quote(to_quote_id)
    if before is None or after is None:
        fail(404, "not_found", "One or both quote versions were not found.")
    try:
        return compare_quotes(before, after)
    except ValueError as exc:
        if str(exc) == "cross_conversation":
            fail(409, "cross_conversation", "Quote versions must belong to the same conversation.")
        raise


@app.get("/api/quotes/{quote_id}/pdf")
def quote_pdf(quote_id: str) -> StreamingResponse:
    quote = repository.get_quote(quote_id)
    if quote is None:
        fail(404, "not_found", "Quote version was not found.")
    if not quote["exportable"] or not quote["confirmation"]:
        fail(409, "not_exportable", "Only a confirmed schema-v2 quote can be exported.")
    snapshot = quote["confirmation"]["snapshot"]
    try:
        pdf = render_confirmed_quote(snapshot)
    except PdfRenderError as exc:
        fail(500, "pdf_generation_failed", str(exc))
    filename = safe_filename(snapshot)
    return StreamingResponse(
        iter([pdf]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
