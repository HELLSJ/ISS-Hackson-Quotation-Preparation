"""Provider-neutral function schemas for the quotation tools."""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import List

_DATA_AGENT_DIR = Path(__file__).resolve().parent.parent / "data" / "agent"
DEFAULT_TOOL_SCHEMAS_PATH = _DATA_AGENT_DIR / "tool_schemas.json"


class ToolSchemaError(Exception):
    """Raised when the tool schema document cannot be loaded."""


@lru_cache(maxsize=1)
def _load() -> dict:
    """Read, validate and cache the schema document."""
    path = DEFAULT_TOOL_SCHEMAS_PATH
    try:
        with path.open("r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError as exc:
        raise ToolSchemaError(f"Tool schema file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ToolSchemaError(f"Invalid JSON in {path}: {exc}") from exc

    if not isinstance(doc, dict) or not isinstance(doc.get("tools"), list):
        raise ToolSchemaError(f"Tool schema {path} must contain a 'tools' array.")
    for entry in doc["tools"]:
        function = entry.get("function") if isinstance(entry, dict) else None
        if not isinstance(entry, dict) or entry.get("type") != "function" or not isinstance(function, dict):
            raise ToolSchemaError(f"Invalid function schema in {path}.")
        if not isinstance(function.get("name"), str) or not isinstance(function.get("parameters"), dict):
            raise ToolSchemaError(f"Function name/parameters missing in {path}.")
    return doc


def tool_schemas() -> list[dict]:
    """Return a copy of the OpenAI/Ollama compatible function list."""
    return copy.deepcopy(_load()["tools"])


def tool_names() -> List[str]:
    """Return the tool names declared in the configuration, in file order."""
    names: List[str] = []
    for entry in _load().get("tools", []):
        function = entry.get("function") if isinstance(entry, dict) else None
        if isinstance(function, dict) and "name" in function:
            names.append(function["name"])
    return names


def reload() -> None:
    """Clear the cached tool configuration so the next access reloads it."""
    _load.cache_clear()
