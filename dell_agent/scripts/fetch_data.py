"""Fetch the frozen data package from the target repository.

This one-time script mirrors the required data files from
``lwd0110/ISS-Hackson-Quotation-Preparation`` into ``dell_agent/data/`` using
the GitHub CLI (``gh``). Relative paths are preserved so the layout matches the
target repo:

    data/agent/catalog.json
    data/agent/tool_schemas.json
    data/agent/instructions.md
    data/agent/knowledge/MON-*.md
    data/processed/pricing_rules.json
    data/evaluation/*.jsonl

Usage:
    python -m dell_agent.scripts.fetch_data

Requirements:
    - The ``gh`` CLI must be installed and authenticated
      (``gh auth login``) with read access to the target repo.

The fetched files are intended to be committed so that the offline tools and
tests run with only the Python standard library. All bundled prices/rules are
synthetic (demo) values.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

REPO = "lwd0110/ISS-Hackson-Quotation-Preparation"

# Destination root: dell_agent/data/  (this file lives in dell_agent/scripts/)
DATA_ROOT = Path(__file__).resolve().parent.parent / "data"

# Explicit single-file paths (repo-relative) to copy verbatim.
EXPLICIT_FILES = [
    "data/agent/catalog.json",
    "data/agent/tool_schemas.json",
    "data/agent/instructions.md",
    "data/processed/pricing_rules.json",
]

# Directories from which to copy files matching a set of glob-ish prefixes.
# (repo_dir, filename_predicate)
DIRECTORY_RULES = [
    ("data/agent/knowledge", lambda name: name.startswith("MON-") and name.endswith(".md")),
    ("data/evaluation", lambda name: name.endswith(".jsonl")),
]


class FetchError(RuntimeError):
    """Raised when the data fetch cannot be completed."""


def _run_gh(args: list[str]) -> str:
    """Run a ``gh`` command and return stdout, raising FetchError on failure."""
    try:
        proc = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:  # gh not installed / not on PATH
        raise FetchError(
            "The 'gh' CLI was not found on PATH. Install GitHub CLI and run "
            "'gh auth login' before running this script."
        ) from exc

    if proc.returncode != 0:
        raise FetchError(
            f"gh {' '.join(args)} failed (exit {proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout


def _api(endpoint: str) -> object:
    """Call the GitHub REST API via ``gh api`` and parse JSON."""
    out = _run_gh(["api", endpoint, "-H", "Accept: application/vnd.github+json"])
    return json.loads(out)


def _write_contents_entry(entry: dict) -> Path:
    """Given a GitHub 'contents' file entry, write it to the mirrored path."""
    repo_path = entry["path"]  # e.g. "data/agent/catalog.json"
    # Strip the leading "data/" so files land under DATA_ROOT preserving the rest.
    rel = repo_path
    if rel.startswith("data/"):
        rel = rel[len("data/") :]
    dest = DATA_ROOT / rel
    dest.parent.mkdir(parents=True, exist_ok=True)

    content_b64 = entry.get("content")
    if content_b64 is None:
        # Large files omit inline content; fetch raw via the download_url path.
        raw = _run_gh(["api", f"repos/{REPO}/contents/{repo_path}", "-H",
                       "Accept: application/vnd.github.raw"])
        dest.write_text(raw, encoding="utf-8")
    else:
        raw_bytes = base64.b64decode(content_b64)
        dest.write_bytes(raw_bytes)
    return dest


def _fetch_file(repo_path: str) -> Path:
    entry = _api(f"repos/{REPO}/contents/{repo_path}")
    if isinstance(entry, list):
        raise FetchError(f"Expected a file at {repo_path}, got a directory listing.")
    return _write_contents_entry(entry)


def _fetch_directory(repo_dir: str, predicate) -> list[Path]:
    listing = _api(f"repos/{REPO}/contents/{repo_dir}")
    if not isinstance(listing, list):
        raise FetchError(f"Expected a directory at {repo_dir}, got a file.")
    written: list[Path] = []
    for entry in listing:
        if entry.get("type") != "file":
            continue
        name = entry.get("name", "")
        if not predicate(name):
            continue
        # The directory listing does not include inline content; fetch each file.
        written.append(_fetch_file(entry["path"]))
    return written


def fetch_all() -> list[Path]:
    """Fetch every required data file. Returns the list of written paths."""
    written: list[Path] = []
    for repo_path in EXPLICIT_FILES:
        written.append(_fetch_file(repo_path))
    for repo_dir, predicate in DIRECTORY_RULES:
        written.extend(_fetch_directory(repo_dir, predicate))
    return written


def main() -> int:
    print(f"Fetching data package from {REPO} into {DATA_ROOT} ...")
    try:
        written = fetch_all()
    except FetchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print(
            "No data files were fabricated. Fix the gh CLI / access issue and "
            "re-run: python -m dell_agent.scripts.fetch_data",
            file=sys.stderr,
        )
        return 1

    print(f"Wrote {len(written)} file(s):")
    for path in written:
        print(f"  - {path.relative_to(DATA_ROOT.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
