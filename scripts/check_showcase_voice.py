#!/usr/bin/env python3
"""Showcase voice guard.

Scans visitor-facing publication surfaces for apologetic or hedging
language that implies the public corpus is a watered-down stand-in for a
hidden real one. The showcase is the product. The corpus on disk is the
corpus visitors are supposed to see.

Banned phrasings (case-insensitive, word-boundaried where applicable) and
why each is banned:

- "sanitized"          → implies the visible content was scrubbed
- "fictional"          → apologizes for the corpus being fake
- "fictitious"         → same
- "obviously fake"     → same, louder
- "no real ..."        → defensive disclaimer
- "real matter data"   → implies hidden privileged data exists
- "private matter"     → same
- "private version"    → implies a withheld version
- "internal lore"      → same
- "preserving confidentiality" → defensive
- "public-safe"        → defensive, implies unsafe content elsewhere
- "showcase only"      → implies the artifact is not the real thing
- "for showcase purposes" → same
- "for showcase use"   → same

Exceptions:
- Function names and identifiers like ``sanitize`` / ``_sanitize_field`` /
  ``sanitize()`` (whitespace normalizers in the ingest scripts) are real
  engineering and are scoped out by the SCAN_GLOBS list.

Exit code 0 = clean. Exit code 1 = at least one banned phrase found.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Publication surfaces — the visitor-facing copy that must hold the line.
SCAN_GLOBS = (
    "README.md",
    "docs/**/*.html",
    "docs/**/*.md",
    "docs/**/*.json",
    "hoss-stonewall/README.md",
    "hoss-stonewall/sample_corpus/**/*.md",
    "archive/**/*.md",
)

# Files that legitimately discuss the rule itself or contain technical
# tokens like the ``sanitize`` function name. These are excluded from the
# scan so the guard does not chase its own tail.
SCAN_EXCLUDES = {
    REPO_ROOT / "AGENTS.md",
    REPO_ROOT / ".github" / "copilot-instructions.md",
    REPO_ROOT / "scripts" / "check_showcase_voice.py",
    REPO_ROOT / "docs" / "showcase-repo-handoff.md",
    REPO_ROOT / "archive" / "stonewall-showcase" / "quarterback" / "publication-runbook.md",
}

BANNED_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9_])sanitized(?![A-Za-z0-9_])", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_])sanitization(?![A-Za-z0-9_])", re.IGNORECASE),
    re.compile(r"\bfictional\b", re.IGNORECASE),
    re.compile(r"\bfictitious\b", re.IGNORECASE),
    re.compile(r"\bobviously fake\b", re.IGNORECASE),
    re.compile(r"\bno real (?:matter|matters|parties|persons?|client|clients|case|cases|claim|claims|data|names?)\b",
               re.IGNORECASE),
    re.compile(r"\breal matter data\b", re.IGNORECASE),
    re.compile(r"\bprivate matter\b", re.IGNORECASE),
    re.compile(r"\bprivate version\b", re.IGNORECASE),
    re.compile(r"\binternal lore\b", re.IGNORECASE),
    re.compile(r"\bpreserving confidentiality\b", re.IGNORECASE),
    re.compile(r"\bpublic-safe\b", re.IGNORECASE),
    re.compile(r"\bshowcase only\b", re.IGNORECASE),
    re.compile(r"\bfor showcase (?:purposes|use)\b", re.IGNORECASE),
)


def collect_files() -> list[Path]:
    seen: set[Path] = set()
    for pattern in SCAN_GLOBS:
        for path in sorted(REPO_ROOT.glob(pattern)):
            if not path.is_file():
                continue
            if path in SCAN_EXCLUDES:
                continue
            seen.add(path)
    return sorted(seen)


def scan(path: Path) -> list[tuple[int, str, str]]:
    hits: list[tuple[int, str, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        hits.append((0, "<decode-error>", f"File is not valid UTF-8: {path}"))
        return hits
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pattern in BANNED_PATTERNS:
            match = pattern.search(line)
            if match:
                hits.append((lineno, match.group(0), line.strip()))
                break
    return hits


def main() -> int:
    total = 0
    files_with_hits = 0
    for path in collect_files():
        hits = scan(path)
        if not hits:
            continue
        files_with_hits += 1
        rel = path.relative_to(REPO_ROOT)
        print(f"{rel}:")
        for lineno, term, line in hits:
            print(f"  line {lineno}: {term!r}  ->  {line}")
            total += 1

    if total:
        print()
        print(f"Showcase voice check FAILED: {total} hit(s) across "
              f"{files_with_hits} file(s).")
        print("See AGENTS.md \"Showcase Voice & PR Standards\" for the rule.")
        return 1

    print("Showcase voice check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
