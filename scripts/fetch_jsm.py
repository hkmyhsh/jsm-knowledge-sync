#!/usr/bin/env python3
"""Fetch JSM Cloud requests and public comments into a sanitized JSON file."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


SECRET_PATTERNS = (
    (re.compile(r"(?i)\b(?:bearer|token|password|secret|api[_ -]?key)\s*[:=]\s*[^\s,;]+"), "[REDACTED_SECRET]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_ACCESS_KEY]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"), "[REDACTED_PRIVATE_KEY]"),
    (re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])"), "[REDACTED_EMAIL]"),
)


def redact(value: str) -> str:
    result = value
    for pattern, replacement in SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def adf_to_text(value: Any) -> str:
    """Convert Atlassian Document Format or arbitrary field data to plain text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "\n".join(part for item in value if (part := adf_to_text(item)))
    if isinstance(value, dict):
        node_type = value.get("type")
        if node_type == "text":
            return redact(str(value.get("text", "")))
        content = value.get("content")
        if isinstance(content, list):
            separator = "\n" if node_type in {"doc", "bulletList", "orderedList", "listItem", "codeBlock"} else ""
            return separator.join(part for item in content if (part := adf_to_text(item)))
        safe = {k: v for k, v in value.items() if k not in {"self", "avatarUrls", "accountId", "emailAddress"}}
        return redact(json.dumps(safe, ensure_ascii=False, sort_keys=True))
    return redact(str(value))


class JsmClient:
    def __init__(self, base_url: str, email: str, token: str, auth_mode: str) -> None:
        self.base_url = base_url.rstrip("/")
        if not self.base_url.startswith("https://"):
            raise ValueError("JSM_BASE_URL must use HTTPS")
        if auth_mode == "basic":
            raw = base64.b64encode(f"{email}:{token}".encode()).decode()
            self.authorization = f"Basic {raw}"
        elif auth_mode == "bearer":
            self.authorization = f"Bearer {token}"
        else:
            raise ValueError("JSM_AUTH_MODE must be 'basic' or 'bearer'")
        self.ssl_context = ssl.create_default_context()

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"Accept": "application/json", "Authorization": self.authorization}
        if body is not None:
            headers["Content-Type"] = "application/json"

        for attempt in range(5):
            request = urllib.request.Request(url, data=body, headers=headers, method=method)
            try:
                with urllib.request.urlopen(request, context=self.ssl_context, timeout=30) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if retryable and attempt < 4:
                    retry_after = exc.headers.get("Retry-After", "")
                    delay = min(int(retry_after), 60) if retry_after.isdigit() else 2**attempt
                    time.sleep(delay)
                    continue
                detail = exc.read(2048).decode("utf-8", errors="replace")
                raise RuntimeError(f"JSM API failed: {method} {path} -> HTTP {exc.code}: {detail}") from exc
            except urllib.error.URLError as exc:
                if attempt < 4:
                    time.sleep(2**attempt)
                    continue
                raise RuntimeError(f"JSM API connection failed: {exc.reason}") from exc
        raise AssertionError("unreachable")

    def search(self, jql: str, max_issues: int, extra_fields: list[str]) -> list[dict[str, Any]]:
        fields = ["summary", "description", "issuetype", "status", "resolution", "reporter", "created", "updated", "labels"]
        fields.extend(field for field in extra_fields if field and field not in fields)
        issues: list[dict[str, Any]] = []
        next_page_token: str | None = None

        while len(issues) < max_issues:
            payload: dict[str, Any] = {
                "jql": jql,
                "fields": fields,
                "maxResults": min(100, max_issues - len(issues)),
            }
            if next_page_token:
                payload["nextPageToken"] = next_page_token
            page = self.request("POST", "/rest/api/3/search/jql", payload)
            issues.extend(page.get("issues", []))
            next_page_token = page.get("nextPageToken")
            if page.get("isLast", not next_page_token) or not next_page_token:
                break
        return issues[:max_issues]

    def comments(self, issue_key: str) -> list[dict[str, Any]]:
        comments: list[dict[str, Any]] = []
        start = 0
        while True:
            query = urllib.parse.urlencode({"start": start, "limit": 100})
            key = urllib.parse.quote(issue_key, safe="")
            page = self.request("GET", f"/rest/servicedeskapi/request/{key}/comment?{query}")
            values = page.get("values", [])
            comments.extend(comment for comment in values if comment.get("public") is True)
            if page.get("isLastPage", True) or not values:
                break
            start += len(values)
        return comments


def required_env(name: str, allow_empty: bool = False) -> str:
    value = os.getenv(name, "").strip()
    if not value and not allow_empty:
        raise ValueError(f"Required environment variable is missing: {name}")
    return value


def normalized_issue(issue: dict[str, Any], comments: list[dict[str, Any]], base_url: str, extra_fields: list[str]) -> dict[str, Any]:
    fields = issue.get("fields", {})
    reporter_id = (fields.get("reporter") or {}).get("accountId")
    conversation = []
    for comment in comments:
        author_id = (comment.get("author") or {}).get("accountId")
        role = "requester" if reporter_id and author_id == reporter_id else "support_candidate"
        conversation.append(
            {
                "role": role,
                "created": (comment.get("created") or {}).get("iso8601", ""),
                "body": redact(str(comment.get("body", ""))),
            }
        )

    return {
        "issue_key": issue.get("key", ""),
        "source_url": f"{base_url.rstrip('/')}/browse/{issue.get('key', '')}",
        "issue_type": (fields.get("issuetype") or {}).get("name", ""),
        "status": (fields.get("status") or {}).get("name", ""),
        "resolution": (fields.get("resolution") or {}).get("name", ""),
        "created": fields.get("created", ""),
        "updated": fields.get("updated", ""),
        "labels": [redact(str(label)) for label in fields.get("labels", [])],
        "summary": redact(str(fields.get("summary", ""))),
        "description": adf_to_text(fields.get("description")),
        "extra_fields": {field: adf_to_text(fields.get(field)) for field in extra_fields},
        "public_conversation": conversation,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    try:
        base_url = required_env("JSM_BASE_URL")
        token = required_env("JSM_API_TOKEN")
        auth_mode = os.getenv("JSM_AUTH_MODE", "basic").strip().lower()
        email = required_env("JSM_EMAIL", allow_empty=auth_mode == "bearer")
        issue_key = os.getenv("JSM_ISSUE_KEY", "").strip().upper()
        configured_jql = os.getenv("JSM_JQL", "").strip()
        max_issues = int(os.getenv("JSM_MAX_ISSUES", "100"))
        extra_fields = [part.strip() for part in os.getenv("JSM_EXTRA_FIELDS", "").split(",") if part.strip()]

        if not 1 <= max_issues <= 500:
            raise ValueError("JSM_MAX_ISSUES must be between 1 and 500")
        if issue_key:
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*-[1-9][0-9]*", issue_key):
                raise ValueError("JSM_ISSUE_KEY has an invalid format")
            jql = f'key = "{issue_key}"'
        elif configured_jql:
            jql = configured_jql
        else:
            raise ValueError("Set JSM_JQL or provide JSM_ISSUE_KEY")

        client = JsmClient(base_url, email, token, auth_mode)
        issues = client.search(jql, max_issues, extra_fields)
        result = [normalized_issue(issue, client.comments(issue["key"]), base_url, extra_fields) for issue in issues]

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"schema_version": 1, "issues": result}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Fetched and sanitized {len(result)} JSM issue(s).")
        return 0
    except (ValueError, RuntimeError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
