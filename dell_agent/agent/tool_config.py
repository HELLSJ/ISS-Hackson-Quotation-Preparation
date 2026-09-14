"""Bedrock Converse ``toolConfig`` loader.

Loads ``data/agent/bedrock_tool_config.json`` verbatim and exposes it as the
Converse ``toolConfig`` (Req 7.1). The file describes the three frozen tools —
``search_products``, ``get_product`` and ``calculate_quote`` — with their input
schemas.

The parsed configuration is cached for the process lifetime and MUST NOT be
mutated (the file is the source of truth). Uses only the Python standard
library (``json``, ``functools``, ``pathlib``, ``copy``).
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import List

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

# dell_agent/agent/tool_config.py -> dell_agent/data/agent/bedrock_tool_config.json
_AGENT_DIR = Path(__file__).resolve().parent
_DATA_AGENT_DIR = _AGENT_DIR.parent / "data" / "agent"
DEFAULT_TOOL_CONFIG_PATH = _DATA_AGENT_DIR / "bedrock_tool_config.json"


class ToolConfigError(Exception):
    """Raised when the Bedrock tool configuration cannot be loaded."""


@lru_cache(maxsize=1)
def _load() -> dict:
    """Read and parse ``bedrock_tool_config.json`` once, verbatim.

    The parsed document is cached and treated as immutable. Callers receive a
    deep copy via :func:`tool_config` so the cached original is never mutated.
    """
    path = DEFAULT_TOOL_CONFIG_PATH
    try:
        with path.open("r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError as exc:
        raise ToolConfigError(f"Tool configuration file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ToolConfigError(f"Invalid JSON in {path}: {exc}") from exc

    if not isinstance(doc, dict) or not isinstance(doc.get("tools"), list):
        raise ToolConfigError(
            f"Tool configuration {path} must be an object with a 'tools' array."
        )
    return doc


def tool_config() -> dict:
    """Return the Bedrock Converse ``toolConfig`` (Req 7.1).

    The returned value is a deep copy of the parsed
    ``bedrock_tool_config.json`` so mutating it never affects the cached
    source of truth. The shape is ``{"tools": [{"toolSpec": {...}}, ...]}``,
    suitable to pass directly as the Converse ``toolConfig``.
    """
    return copy.deepcopy(_load())


def tool_names() -> List[str]:
    """Return the tool names declared in the configuration, in file order."""
    names: List[str] = []
    for entry in _load().get("tools", []):
        spec = entry.get("toolSpec") if isinstance(entry, dict) else None
        if isinstance(spec, dict) and "name" in spec:
            names.append(spec["name"])
    return names


def reload() -> None:
    """Clear the cached tool configuration so the next access reloads it."""
    _load.cache_clear()
