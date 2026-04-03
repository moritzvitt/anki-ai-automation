from __future__ import annotations

import json
import os
from typing import Any


_USER_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "user_data")
_AUDIT_FILE = os.path.join(_USER_DATA_DIR, "audit_log.json")


def load_audit_log() -> dict[str, Any]:
    if not os.path.exists(_AUDIT_FILE):
        return {"notes": {}}

    try:
        with open(_AUDIT_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"notes": {}}

    if not isinstance(data, dict):
        return {"notes": {}}
    notes = data.get("notes")
    if not isinstance(notes, dict):
        data["notes"] = {}
    return data


def save_audit_log(log: dict[str, Any]) -> None:
    os.makedirs(_USER_DATA_DIR, exist_ok=True)
    with open(_AUDIT_FILE, "w", encoding="utf-8") as handle:
        json.dump(log, handle, indent=2, sort_keys=True, ensure_ascii=False)


def get_note_audit_entry(log: dict[str, Any], note_id: int) -> dict[str, Any] | None:
    notes = log.get("notes")
    if not isinstance(notes, dict):
        return None
    entry = notes.get(str(note_id))
    return entry if isinstance(entry, dict) else None


def set_note_audit_entry(log: dict[str, Any], note_id: int, entry: dict[str, Any]) -> None:
    notes = log.setdefault("notes", {})
    if not isinstance(notes, dict):
        notes = {}
        log["notes"] = notes
    notes[str(note_id)] = entry
