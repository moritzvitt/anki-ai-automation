#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import os
import re
import sys
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


ANKICONNECT_URL = "http://127.0.0.1:8765"
STATUS_FIELD_NAME = "AI Status"
TAG_PREFIX = "AI_STATUS::"
KNOWN_STATUSES = (
    "GOOD",
    "FIXABLE_MINOR",
    "FIXABLE_MAJOR",
    "REJECT",
    "SKIP",
    "FAILED",
)


def main() -> int:
    note_ids = _note_ids_from_env()
    if not note_ids:
        return 0

    notes = _invoke("notesInfo", notes=note_ids)
    if not isinstance(notes, list):
        raise RuntimeError("AnkiConnect returned an unexpected notesInfo payload.")

    grouped_note_ids: dict[str, list[int]] = {}
    removable_tags: set[str] = set()

    for note in notes:
        if not isinstance(note, dict):
            continue
        note_id = int(note.get("noteId", 0))
        tags = note.get("tags", [])
        if isinstance(tags, list):
            for tag in tags:
                if isinstance(tag, str) and tag.startswith(TAG_PREFIX):
                    removable_tags.add(tag)
        fields = note.get("fields", {})
        if not isinstance(fields, dict):
            continue
        raw_status = _field_value(fields, STATUS_FIELD_NAME)
        status_tag = _status_tag(raw_status)
        if status_tag is None:
            continue
        grouped_note_ids.setdefault(status_tag, []).append(note_id)
        removable_tags.add(status_tag)

    if not grouped_note_ids:
        return 0

    existing_status_tags = sorted(removable_tags)
    if existing_status_tags:
        _invoke("removeTags", notes=note_ids, tags=" ".join(existing_status_tags))

    for tag, tag_note_ids in grouped_note_ids.items():
        _invoke("addTags", notes=tag_note_ids, tags=tag)

    return 0


def _note_ids_from_env() -> list[int]:
    raw = os.environ.get("AI_AUTOMATION_NOTE_IDS", "").strip()
    if not raw:
        return []
    note_ids: list[int] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        note_ids.append(int(item))
    return note_ids


def _field_value(fields: dict[str, Any], name: str) -> str:
    field = fields.get(name)
    if isinstance(field, dict):
        value = field.get("value", "")
        return str(value)
    return str(field or "")


def _status_tag(raw_status: str) -> str | None:
    plain_text = _strip_html(raw_status)
    if not plain_text:
        return None

    canonical_status = _known_status(plain_text)
    if canonical_status is None:
        canonical_status = _generalize_status(plain_text)
    if not canonical_status:
        return None
    return f"{TAG_PREFIX}{canonical_status}"


def _strip_html(value: str) -> str:
    text = re.sub(r"(?i)<br\\s*/?>", "\n", value)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n+", "\n", text)
    return text.strip()


def _known_status(text: str) -> str | None:
    normalized = _generalize_status(text)
    if normalized in KNOWN_STATUSES:
        return normalized
    for status in KNOWN_STATUSES:
        if status in normalized:
            return status
    return None


def _generalize_status(text: str) -> str:
    generalized = text.upper()
    generalized = generalized.replace("-", "_")
    generalized = generalized.replace("/", "_")
    generalized = re.sub(r"[^A-Z0-9]+", "_", generalized)
    generalized = re.sub(r"_+", "_", generalized)
    return generalized.strip("_")


def _invoke(action: str, **params: Any) -> Any:
    payload = json.dumps({"action": action, "version": 6, "params": params}).encode("utf-8")
    request = Request(
        ANKICONNECT_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request) as response:
            data = json.loads(response.read().decode("utf-8"))
    except URLError as error:  # pragma: no cover
        raise RuntimeError("Could not reach AnkiConnect on 127.0.0.1:8765.") from error

    if not isinstance(data, dict):
        raise RuntimeError("AnkiConnect returned an invalid response.")
    if data.get("error"):
        raise RuntimeError(str(data["error"]))
    return data.get("result")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # pragma: no cover
        print(f"AI status tagging failed: {error}", file=sys.stderr)
        raise SystemExit(1)
