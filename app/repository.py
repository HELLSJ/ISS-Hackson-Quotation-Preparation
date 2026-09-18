"""SQLite persistence for conversations, messages and quote snapshots."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Repository:
    """Small repository with one connection per operation.

    The application DB is intentionally separate from ``catalog.sqlite``. Quote
    payloads are immutable snapshots: later catalogue changes cannot rewrite an
    already saved version.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA journal_mode = WAL")
        return db

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    driver TEXT NOT NULL CHECK(driver IN ('offline','converse')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    seq INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user','assistant')),
                    content TEXT NOT NULL,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(conversation_id, seq)
                );
                CREATE TABLE IF NOT EXISTS quote_versions (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL,
                    fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(conversation_id, version),
                    UNIQUE(conversation_id, fingerprint)
                );
                CREATE INDEX IF NOT EXISTS idx_messages_conversation
                    ON messages(conversation_id, seq);
                CREATE INDEX IF NOT EXISTS idx_quotes_conversation
                    ON quote_versions(conversation_id, version);
                """
            )

    def create_conversation(self, driver: str) -> dict[str, Any]:
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
            exists = db.execute(
                "SELECT 1 FROM conversations WHERE id=?", (conversation_id,)
            ).fetchone()
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
                "INSERT INTO messages VALUES (?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), conversation_id, next_seq, "user", user_content, None, now),
            )
            db.execute(
                "INSERT INTO messages VALUES (?,?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    conversation_id,
                    next_seq + 1,
                    "assistant",
                    assistant_content,
                    canonical_json(result),
                    now,
                ),
            )
            db.execute(
                "UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id)
            )

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
                "SELECT id,version,payload_json,created_at FROM quote_versions WHERE conversation_id=? ORDER BY version",
                (conversation_id,),
            ).fetchall()

        messages: list[dict[str, Any]] = []
        latest_result = None
        latest_result_message_id = None
        for row in message_rows:
            message = {
                "id": row["id"],
                "seq": row["seq"],
                "role": row["role"],
                "content": row["content"],
                "created_at": row["created_at"],
            }
            if row["result_json"]:
                message["result"] = json.loads(row["result_json"])
                latest_result = message["result"]
                latest_result_message_id = row["id"]
            messages.append(message)

        quotes = []
        for row in quote_rows:
            payload = json.loads(row["payload_json"])
            quotes.append(
                {
                    "id": row["id"],
                    "version": row["version"],
                    "total_cents": payload["total_cents"],
                    "currency": payload["currency"],
                    "line_count": len(payload.get("lines", [])),
                    "created_at": row["created_at"],
                }
            )
        return {
            **dict(conversation),
            "messages": messages,
            "latest_result": latest_result,
            "latest_result_message_id": latest_result_message_id,
            "quote_versions": quotes,
        }

    def save_latest_quote(
        self, conversation_id: str, result_message_id: str
    ) -> tuple[dict[str, Any] | None, str | None]:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            conversation = db.execute(
                "SELECT 1 FROM conversations WHERE id=?", (conversation_id,)
            ).fetchone()
            if not conversation:
                return None, "not_found"
            row = db.execute(
                "SELECT id,result_json FROM messages WHERE conversation_id=? AND role='assistant' ORDER BY seq DESC LIMIT 1",
                (conversation_id,),
            ).fetchone()
            if not row or row["id"] != result_message_id:
                return None, "stale_draft"
            result = json.loads(row["result_json"]) if row["result_json"] else {}
            draft = result.get("quote_draft")
            if not isinstance(draft, dict) or draft.get("total_cents") is None:
                return None, "no_draft"

            payload = dict(draft)
            payload["status"] = "saved_draft"
            payload["is_confirmed"] = False
            fingerprint = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
            existing = db.execute(
                "SELECT id,version,payload_json,created_at FROM quote_versions WHERE conversation_id=? AND fingerprint=?",
                (conversation_id, fingerprint),
            ).fetchone()
            if existing:
                return self._quote_row(existing, conversation_id), None

            version = int(
                db.execute(
                    "SELECT COALESCE(MAX(version),0)+1 FROM quote_versions WHERE conversation_id=?",
                    (conversation_id,),
                ).fetchone()[0]
            )
            quote_id = str(uuid.uuid4())
            now = utc_now()
            db.execute(
                "INSERT INTO quote_versions VALUES (?,?,?,?,?,?)",
                (quote_id, conversation_id, version, fingerprint, canonical_json(payload), now),
            )
            db.execute(
                "UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id)
            )
        return {
            "id": quote_id,
            "conversation_id": conversation_id,
            "version": version,
            "payload": payload,
            "created_at": now,
        }, None

    @staticmethod
    def _quote_row(row: sqlite3.Row, conversation_id: str) -> dict[str, Any]:
        return {
            "id": row["id"],
            "conversation_id": conversation_id,
            "version": row["version"],
            "payload": json.loads(row["payload_json"]),
            "created_at": row["created_at"],
        }

    def get_quote(self, quote_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT id,conversation_id,version,payload_json,created_at FROM quote_versions WHERE id=?",
                (quote_id,),
            ).fetchone()
        if not row:
            return None
        return self._quote_row(row, row["conversation_id"])
