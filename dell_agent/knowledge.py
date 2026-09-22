"""Spec-card knowledge retrieval (knowledge/ only, allow-listed).

Indexes ONLY the monitor specification cards under
``data/agent/knowledge/MON-*.md`` and provides a simple, stdlib-only keyword
retrieval over them.

Safety invariant (Req 7.4, 8.5): evaluation data, validation reports and
expected answers MUST NEVER be ingested into the runtime knowledge store. An
explicit allow-list (:func:`_is_allowed`) gates every path: a file is indexable
only when it lives directly inside the knowledge directory AND its name matches
the ``MON-*.md`` pattern. Anything under ``data/evaluation`` (or anywhere else)
is rejected.

Uses only the Python standard library (``json`` is unused here; ``pathlib``,
``functools``, ``re``).
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

# --------------------------------------------------------------------------- #
# Paths and allow-list
# --------------------------------------------------------------------------- #

# dell_agent/knowledge.py -> dell_agent/data/agent/knowledge
_PKG_DIR = Path(__file__).resolve().parent
KNOWLEDGE_DIR = _PKG_DIR / "data" / "agent" / "knowledge"

# The ONLY files that may be indexed: MON-<something>.md directly inside the
# knowledge directory. This deliberately excludes README.md, evaluation JSONL,
# expected answers, validation reports, etc.
_ALLOWED_GLOB = "MON-*.md"
_ALLOWED_NAME_RE = re.compile(r"^MON-.+\.md$")

# Number of spec cards the frozen data package ships.
EXPECTED_CARD_COUNT = 50

# Match a SKU id embedded in a card, e.g. "MON-007" or "MON-L013".
_SKU_RE = re.compile(r"\bMON-(?:L)?\d+\b")

# Tokeniser for keyword scoring: alphanumeric runs, keeping hyphenated tokens
# (e.g. "usb-c", "23.81") mostly intact by splitting on whitespace/punctuation
# except '-' and '.'.
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]*")


def _is_allowed(path) -> bool:
    """Return ``True`` only for indexable knowledge cards.

    A path is allowed IFF, after resolving:
      * it is a file whose name matches ``MON-*.md``; AND
      * its parent directory is exactly :data:`KNOWLEDGE_DIR`.

    Everything else — notably anything under ``data/evaluation`` — returns
    ``False`` (Req 7.4, 8.5). The check is purely structural so it works for
    non-existent paths in tests as well.
    """
    p = Path(path)
    try:
        resolved = p.resolve()
    except (OSError, RuntimeError):
        return False

    if not _ALLOWED_NAME_RE.match(resolved.name):
        return False

    # Parent must be the knowledge directory itself (no nesting, no siblings
    # such as data/evaluation/).
    if resolved.parent != KNOWLEDGE_DIR.resolve():
        return False

    return True


def _tokenize(text: str) -> List[str]:
    """Lowercase alphanumeric tokenisation used for scoring and indexing."""
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(text)]


def _sku_from(path: Path, text: str) -> str:
    """Derive the SKU for a card from its filename (fallback: file content)."""
    stem = path.stem  # e.g. "MON-007"
    if _SKU_RE.fullmatch(stem):
        return stem
    m = _SKU_RE.search(text)
    return m.group(0) if m else stem


class _Card:
    """A single indexed spec card."""

    __slots__ = ("sku", "path", "text", "tokens")

    def __init__(self, sku: str, path: Path, text: str) -> None:
        self.sku = sku
        self.path = path
        self.text = text
        self.tokens = _tokenize(text)


# --------------------------------------------------------------------------- #
# Indexing (allow-listed)
# --------------------------------------------------------------------------- #

@lru_cache(maxsize=1)
def _index() -> List[_Card]:
    """Build the in-memory index from allow-listed knowledge cards only.

    Every candidate path is re-checked through :func:`_is_allowed` before being
    read, so no evaluation/validation file can ever enter the store even if the
    glob or directory layout changes (Req 7.4, 8.5).
    """
    cards: List[_Card] = []
    if not KNOWLEDGE_DIR.exists():
        return cards

    for path in sorted(KNOWLEDGE_DIR.glob(_ALLOWED_GLOB)):
        # Defence in depth: the glob already restricts to the knowledge dir,
        # but re-verify each path through the explicit guard.
        if not _is_allowed(path):
            continue
        text = path.read_text(encoding="utf-8")
        cards.append(_Card(sku=_sku_from(path, text), path=path, text=text))
    return cards


def _snippet(text: str, query_tokens: List[str], width: int = 160) -> str:
    """Return a short snippet around the first matching query token.

    Falls back to the leading portion of the card when nothing matches.
    """
    lowered = text.lower()
    best = -1
    for tok in query_tokens:
        idx = lowered.find(tok)
        if idx != -1 and (best == -1 or idx < best):
            best = idx
    if best == -1:
        snippet = text.strip()[:width]
    else:
        start = max(0, best - width // 3)
        snippet = text[start : start + width].strip()
    # Collapse whitespace/newlines for a compact one-line snippet.
    return re.sub(r"\s+", " ", snippet)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def all_cards() -> List[Dict[str, str]]:
    """Return every indexed card as ``{"sku", "path", "text"}`` dicts."""
    return [
        {"sku": c.sku, "path": str(c.path), "text": c.text}
        for c in _index()
    ]


def search(query: str, limit: Optional[int] = 5) -> List[Dict[str, object]]:
    """Keyword retrieval over the spec cards.

    Scores each card by token-overlap with the query (count of query token
    occurrences in the card, case-insensitive). Cards with a positive score are
    returned sorted by score descending, then SKU ascending for stability.

    Args:
        query: Free-text keyword query (e.g. ``"USB-C"`` or ``"Thunderbolt"``).
        limit: Maximum number of results to return; ``None`` returns all
            matches.

    Returns:
        A list of ``{"sku", "path", "score", "snippet"}`` dicts.
    """
    query_tokens = _tokenize(query or "")
    if not query_tokens:
        return []

    results: List[Dict[str, object]] = []
    for card in _index():
        text_lower = card.text.lower()
        score = 0
        for tok in query_tokens:
            # Count occurrences so repeated/prominent terms rank higher.
            score += text_lower.count(tok)
        if score > 0:
            results.append(
                {
                    "sku": card.sku,
                    "path": str(card.path),
                    "score": score,
                    "snippet": _snippet(card.text, query_tokens),
                }
            )

    results.sort(key=lambda r: (-int(r["score"]), str(r["sku"])))
    if limit is not None:
        results = results[:limit]
    return results


def reload() -> None:
    """Clear the cached index so the next access rebuilds it from disk."""
    _index.cache_clear()
