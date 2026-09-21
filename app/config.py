"""Environment-backed application settings."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    app_db_path: Path
    agent_driver: str
    gateway_url: str | None
    gateway_api_key: str | None
    llm_model: str | None


def load_settings() -> Settings:
    driver = os.getenv("AGENT_DRIVER", "offline").strip().lower()
    if driver not in {"offline", "gateway"}:
        driver = "offline"
    return Settings(
        app_db_path=Path(os.getenv("APP_DB_PATH", str(ROOT / "storage/app.sqlite"))).expanduser(),
        agent_driver=driver,
        gateway_url=os.getenv("LLM_GATEWAY_URL", "").strip() or None,
        gateway_api_key=os.getenv("LLM_GATEWAY_API_KEY", "").strip() or None,
        llm_model=os.getenv("LLM_MODEL", "").strip() or None,
    )
