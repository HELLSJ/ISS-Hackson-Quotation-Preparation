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
    bedrock_model_id: str | None
    aws_region: str | None


def load_settings() -> Settings:
    driver = os.getenv("AGENT_DRIVER", "offline").strip().lower()
    if driver not in {"offline", "converse"}:
        driver = "offline"
    model_id = os.getenv("BEDROCK_MODEL_ID", "").strip() or None
    region = (
        os.getenv("AWS_REGION", "").strip()
        or os.getenv("AWS_DEFAULT_REGION", "").strip()
        or None
    )
    return Settings(
        app_db_path=Path(os.getenv("APP_DB_PATH", str(ROOT / "storage/app.sqlite"))).expanduser(),
        agent_driver=driver,
        bedrock_model_id=model_id,
        aws_region=region,
    )
