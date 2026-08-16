#!/usr/bin/env python3
"""Validate the minimum structure and obvious secret hygiene of generated knowledge."""

from __future__ import annotations

import re
import sys
from pathlib import Path


REQUIRED_HEADINGS = ("## 問い合わせ", "## 回答", "## 適用条件・注意点", "## 根拠")
FORBIDDEN_PATTERNS = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:bearer|password|api[_ -]?key)\s*[:=]\s*[^\s,;]+"),
)


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "knowledge")
    errors: list[str] = []
    index = root / "index.md"
    if not index.is_file():
        errors.append("knowledge/index.md is missing")

    articles = sorted((root / "articles").glob("*.md"))
    if not articles:
        errors.append("No knowledge/articles/*.md files were generated")

    for article in articles:
        text = article.read_text(encoding="utf-8")
        expected_key = article.stem
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*-[1-9][0-9]*", expected_key):
            errors.append(f"{article}: filename must be a JSM issue key")
        if f"issue_key: {expected_key}" not in text:
            errors.append(f"{article}: issue_key front matter does not match filename")
        for heading in REQUIRED_HEADINGS:
            if heading not in text:
                errors.append(f"{article}: missing heading {heading}")
        for pattern in FORBIDDEN_PATTERNS:
            if pattern.search(text):
                errors.append(f"{article}: possible secret detected")

    if errors:
        print("Knowledge validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Validated {len(articles)} knowledge article(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

