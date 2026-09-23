"""SQLite persistence for conversations and immutable quote snapshots."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .snapshots import SnapshotError, build_confirmed_snapshot, build_saved_snapshot

SCHEMA_VERSION = 3


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class Repository:
    """Application repository; catalogue data lives in a separate database."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA journal_mode = WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def initialize(self) -> None:
        """Create a fresh schema or migrate the original quote_versions table.

        Existing payload_json and fingerprints are never rewritten. They remain
        schema-v1 legacy saved drafts and are readable/diffable but not confirmable.
        """
        self._migrate_conversation_drivers()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    driver TEXT NOT NULL CHECK(driver IN ('offline','gateway')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    seq INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user','assistant')),
                    content TEXT NOT NULL,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(conversation_id, seq)
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS quote_versions (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL,
                    fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    snapshot_schema_version INTEGER NOT NULL DEFAULT 1,
                    source_result_message_id TEXT,
                    UNIQUE(conversation_id, version),
                    UNIQUE(conversation_id, fingerprint)
                )"""
            )
            columns = {
                row["name"] for row in db.execute("PRAGMA table_info(quote_versions)").fetchall()
            }
            if "snapshot_schema_version" not in columns:
                db.execute(
                    "ALTER TABLE quote_versions ADD COLUMN snapshot_schema_version INTEGER NOT NULL DEFAULT 1"
                )
            if "source_result_message_id" not in columns:
                db.execute("ALTER TABLE quote_versions ADD COLUMN source_result_message_id TEXT")
            db.execute(
                """CREATE TABLE IF NOT EXISTS quote_confirmations (
                    id TEXT PRIMARY KEY,
                    quote_version_id TEXT NOT NULL UNIQUE REFERENCES quote_versions(id) ON DELETE CASCADE,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    snapshot_token TEXT NOT NULL,
                    confirmed_snapshot_json TEXT NOT NULL,
                    confirmed_fingerprint TEXT NOT NULL,
                    confirmed_at TEXT NOT NULL,
                    UNIQUE(quote_version_id, snapshot_token)
                )"""
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, seq)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_quotes_conversation ON quote_versions(conversation_id, version)"
            )
            db.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS uq_quote_source_result
                ON quote_versions(conversation_id, source_result_message_id)
                WHERE source_result_message_id IS NOT NULL"""
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_confirmations_conversation ON quote_confirmations(conversation_id, confirmed_at)"
            )
            db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _migrate_conversation_drivers(self) -> None:
        """Rebuild the driver constraint and map legacy ``converse`` rows."""
        db = sqlite3.connect(self.path, timeout=15)
        try:
            row = db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='conversations'"
            ).fetchone()
            if row is None or "'gateway'" in (row[0] or ""):
                return
            db.execute("PRAGMA foreign_keys = OFF")
            with db:
                db.execute(
                    """CREATE TABLE conversations_v3 (
                        id TEXT PRIMARY KEY,
                        driver TEXT NOT NULL CHECK(driver IN ('offline','gateway')),
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )"""
                )
                db.execute(
                    """INSERT INTO conversations_v3(id,driver,created_at,updated_at)
                    SELECT id, CASE WHEN driver='converse' THEN 'gateway' ELSE driver END,
                           created_at, updated_at
                    FROM conversations"""
                )
                db.execute("DROP TABLE conversations")
                db.execute("ALTER TABLE conversations_v3 RENAME TO conversations")
        finally:
            db.close()

    def create_conversation(self, driver: str) -> dict[str, Any]:
        if driver not in {"offline", "gateway"}:
            raise ValueError("driver must be 'offline' or 'gateway'")
        conversation_id = str(uuid.uuid4())
        now = utc_now()
        with self.connect() as db:
            db.execute(
                "INSERT INTO conversations(id,driver,created_at,updated_at) VALUES (?,?,?,?)",
                (conversation_id, driver, now, now),
            )
        return self.get_conversation(conversation_id)  # type: ignore[return-value]

    def list_conversations(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT id,driver,created_at,updated_at FROM conversations ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_user_turns(self, conversation_id: str) -> list[str] | None:
        with self.connect() as db:
            exists = db.execute("SELECT 1 FROM conversations WHERE id=?", (conversation_id,)).fetchone()
            if not exists:
                return None
            rows = db.execute(
                "SELECT content FROM messages WHERE conversation_id=? AND role='user' ORDER BY seq",
                (conversation_id,),
            ).fetchall()
        return [row["content"] for row in rows]

    def append_exchange(
        self,
        conversation_id: str,
        user_content: str,
        assistant_content: str,
        result: dict[str, Any],
    ) -> None:
        now = utc_now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT COALESCE(MAX(seq),0) AS seq FROM messages WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()
            next_seq = int(row["seq"]) + 1
            db.execute(
                "INSERT INTO messages(id,conversation_id,seq,role,content,result_json,created_at) VALUES (?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), conversation_id, next_seq, "user", user_content, None, now),
            )
            db.execute(
                "INSERT INTO messages(id,conversation_id,seq,role,content,result_json,created_at) VALUES (?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), conversation_id, next_seq + 1, "assistant", assistant_content, canonical_json(result), now),
            )
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id))

    @staticmethod
    def _quote_select(where: str) -> str:
        return f"""SELECT q.id,q.conversation_id,q.version,q.fingerprint,q.payload_json,q.created_at,
            q.snapshot_schema_version,q.source_result_message_id,
            c.id AS confirmation_id,c.snapshot_token,c.confirmed_snapshot_json,
            c.confirmed_fingerprint,c.confirmed_at
            FROM quote_versions q
            LEFT JOIN quote_confirmations c ON c.quote_version_id=q.id
            WHERE {where}"""

    @classmethod
    def _quote_row(cls, row: sqlite3.Row) -> dict[str, Any]:
        payload = json.loads(row["payload_json"])
        schema_version = int(row["snapshot_schema_version"] or 1)
        confirmation = None
        if row["confirmation_id"]:
            confirmed_snapshot = json.loads(row["confirmed_snapshot_json"])
            confirmation = {
                "id": row["confirmation_id"],
                "confirmed_at": row["confirmed_at"],
                "confirmed_by": confirmed_snapshot["confirmation"]["confirmed_by"],
                "fingerprint": row["confirmed_fingerprint"],
                "snapshot": confirmed_snapshot,
            }
        status = "confirmed" if confirmation else (
            "saved_draft" if schema_version == 2 else "legacy_saved_draft"
        )
        return {
            "id": row["id"],
            "conversation_id": row["conversation_id"],
            "version": row["version"],
            "status": status,
            "is_confirmed": confirmation is not None,
            "snapshot_schema_version": schema_version,
            "snapshot_token": row["fingerprint"],
            "confirmable": schema_version == 2 and confirmation is None,
            "exportable": confirmation is not None,
            "payload": payload,
            "confirmation": confirmation,
            "pdf_url": f"/api/quotes/{row['id']}/pdf" if confirmation else None,
            "created_at": row["created_at"],
        }

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            conversation = db.execute(
                "SELECT id,driver,created_at,updated_at FROM conversations WHERE id=?",
                (conversation_id,),
            ).fetchone()
            if not conversation:
                return None
            message_rows = db.execute(
                "SELECT id,seq,role,content,result_json,created_at FROM messages WHERE conversation_id=? ORDER BY seq",
                (conversation_id,),
            ).fetchall()
            quote_rows = db.execute(
                self._quote_select("q.conversation_id=?") + " ORDER BY q.version",
                (conversation_id,),
            ).fetchall()

        messages: list[dict[str, Any]] = []
        latest_result = None
        latest_result_message_id = None
        for row in message_rows:
            message = {
                "id": row["id"], "seq": row["seq"], "role": row["role"],
                "content": row["content"], "created_at": row["created_at"],
            }
            if row["result_json"]:
                message["result"] = json.loads(row["result_json"])
                latest_result = message["result"]
                latest_result_message_id = row["id"]
            messages.append(message)

        quotes = []
        latest_quote_version = max((row["version"] for row in quote_rows), default=0)
        for row in quote_rows:
            quote = self._quote_row(row)
            if not quote["is_confirmed"] and quote["version"] != latest_quote_version:
                quote["confirmable"] = False
            payload = quote["confirmation"]["snapshot"] if quote["confirmation"] else quote["payload"]
            quotes.append(
                {
                    "id": quote["id"], "version": quote["version"],
                    "status": quote["status"], "is_confirmed": quote["is_confirmed"],
                    "confirmable": quote["confirmable"], "exportable": quote["exportable"],
                    "total_cents": payload.get("total_cents"),
                    "currency": payload.get("currency"),
                    "line_count": len(payload.get("lines", [])),
                    "created_at": quote["created_at"],
                }
            )
        return {
            **dict(conversation), "messages": messages, "latest_result": latest_result,
            "latest_result_message_id": latest_result_message_id, "quote_versions": quotes,
        }

    def save_latest_quote(
        self,
        conversation_id: str,
        result_message_id: str,
        customer_display_name: str | None = None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        customer = customer_display_name.strip() if customer_display_name else None
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM conversations WHERE id=?", (conversation_id,)).fetchone():
                return None, "not_found"
            row = db.execute(
                "SELECT id,result_json FROM messages WHERE conversation_id=? AND role='assistant' ORDER BY seq DESC LIMIT 1",
                (conversation_id,),
            ).fetchone()
            if not row or row["id"] != result_message_id:
                return None, "stale_draft"

            existing = db.execute(
                self._quote_select("q.conversation_id=? AND q.source_result_message_id=?"),
                (conversation_id, result_message_id),
            ).fetchone()
            if existing:
                quote = self._quote_row(existing)
                existing_customer = (quote["payload"].get("customer") or {}).get("display_name")
                if customer != existing_customer:
                    return None, "save_conflict"
                return quote, None

            result = json.loads(row["result_json"]) if row["result_json"] else {}
            draft = result.get("quote_draft")
            if not isinstance(draft, dict):
                return None, "no_draft"
            version = int(
                db.execute(
                    "SELECT COALESCE(MAX(version),0)+1 FROM quote_versions WHERE conversation_id=?",
                    (conversation_id,),
                ).fetchone()[0]
            )
            quote_id = str(uuid.uuid4())
            now = utc_now()
            quote_number = f"Q-{now[:10].replace('-', '')}-{conversation_id[:8].upper()}-V{version}"
            try:
                payload = build_saved_snapshot(
                    draft, quote_id=quote_id, quote_number=quote_number,
                    quote_version=version, source_result_message_id=result_message_id,
                    created_at=now, customer_display_name=customer,
                )
            except SnapshotError as exc:
                return None, exc.code
            token = fingerprint(payload)
            try:
                db.execute(
                    """INSERT INTO quote_versions
                    (id,conversation_id,version,fingerprint,payload_json,created_at,
                     snapshot_schema_version,source_result_message_id)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        quote_id, conversation_id, version, token, canonical_json(payload), now,
                        payload["schema_version"], result_message_id,
                    ),
                )
            except sqlite3.IntegrityError:
                winner = db.execute(
                    self._quote_select("q.conversation_id=? AND q.source_result_message_id=?"),
                    (conversation_id, result_message_id),
                ).fetchone()
                if winner:
                    return self._quote_row(winner), None
                raise
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id))
            saved = db.execute(self._quote_select("q.id=?"), (quote_id,)).fetchone()
            return self._quote_row(saved), None

    def confirm_quote(
        self,
        quote_id: str,
        snapshot_token: str,
        customer_display_name: str,
        confirmed_by: str,
    ) -> tuple[dict[str, Any] | None, str | None, list[str]]:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(self._quote_select("q.id=?"), (quote_id,)).fetchone()
            if not row:
                return None, "not_found", []
            quote = self._quote_row(row)
            if quote["confirmation"]:
                confirmed_snapshot = quote["confirmation"]["snapshot"]
                same_confirmation = (
                    snapshot_token == quote["snapshot_token"]
                    and (confirmed_snapshot.get("customer") or {}).get("display_name") == customer_display_name.strip()
                    and (confirmed_snapshot.get("confirmation") or {}).get("confirmed_by") == confirmed_by.strip()
                )
                if same_confirmation:
                    return quote, None, []
                return None, "already_confirmed", []
            if snapshot_token != quote["snapshot_token"]:
                return None, "stale_confirmation", []
            if quote["snapshot_schema_version"] != 2:
                return None, "not_confirmable", ["schema_version"]
            latest = db.execute(
                "SELECT MAX(version) FROM quote_versions WHERE conversation_id=?",
                (quote["conversation_id"],),
            ).fetchone()[0]
            if quote["version"] != latest:
                return None, "stale_confirmation", []
            now = utc_now()
            try:
                confirmed = build_confirmed_snapshot(
                    quote["payload"], customer_display_name=customer_display_name,
                    confirmed_by=confirmed_by, confirmed_at=now,
                )
            except SnapshotError as exc:
                return None, exc.code, exc.missing_fields
            confirmation_id = str(uuid.uuid4())
            confirmed_fingerprint = fingerprint(confirmed)
            try:
                db.execute(
                    """INSERT INTO quote_confirmations
                    (id,quote_version_id,conversation_id,snapshot_token,
                     confirmed_snapshot_json,confirmed_fingerprint,confirmed_at)
                    VALUES (?,?,?,?,?,?,?)""",
                    (
                        confirmation_id, quote_id, quote["conversation_id"], snapshot_token,
                        canonical_json(confirmed), confirmed_fingerprint, now,
                    ),
                )
            except sqlite3.IntegrityError:
                winner = db.execute(self._quote_select("q.id=?"), (quote_id,)).fetchone()
                if winner and winner["confirmation_id"]:
                    return self._quote_row(winner), None, []
                raise
            confirmed_row = db.execute(self._quote_select("q.id=?"), (quote_id,)).fetchone()
            return self._quote_row(confirmed_row), None, []

    def get_quote(self, quote_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(self._quote_select("q.id=?"), (quote_id,)).fetchone()
            if not row:
                return None
            quote = self._quote_row(row)
            latest = db.execute(
                "SELECT MAX(version) FROM quote_versions WHERE conversation_id=?",
                (quote["conversation_id"],),
            ).fetchone()[0]
        if not quote["is_confirmed"] and quote["version"] != latest:
            quote["confirmable"] = False
        return quote
