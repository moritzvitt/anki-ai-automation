from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable


MLR_NOTE_TYPE_NAME = "Moritz Language Reactor"
MLR_AUDIT_RELEVANT_FIELDS = (
    "Cloze",
    "Lemma",
    "Subtitle",
    "Word Definition",
    "Japanese Notes",
    "Notes",
    "Grammar",
)
MLR_AUDIT_UPDATABLE_FIELDS = (
    "Japanese Notes",
    "Notes",
    "Word Definition",
    "Grammar",
)
MLR_AUDIT_ISSUE_FIELDS = MLR_AUDIT_RELEVANT_FIELDS + ("Other",)
MLR_AUDIT_ALLOWED_STATUSES = (
    "GOOD",
    "FIXABLE_MINOR",
    "FIXABLE_MAJOR",
    "REJECT",
    "SKIP",
)
MLR_AUDIT_ALLOWED_SEVERITIES = ("minor", "major")
AUDIT_SCHEMA_PRESET_MLR = "mlr_audit"
_PROMPT_LIBRARY_ROOT = Path(__file__).resolve().parent.parent / "prompt_library"


@dataclass(frozen=True)
class AuditSchemaPreset:
    preset_id: str
    name: str
    note_type_name: str | None
    relevant_fields: tuple[str, ...]
    updatable_fields: tuple[str, ...]
    issue_fields: tuple[str, ...]
    allowed_statuses: tuple[str, ...]
    allowed_severities: tuple[str, ...]
    default_system_prompt: str
    default_user_prompt_template: str
    schema_builder: Callable[[], dict[str, Any]]


@lru_cache(maxsize=16)
def _load_prompt_library_text(relative_path: str) -> str:
    path = _PROMPT_LIBRARY_ROOT / relative_path
    try:
        text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as error:
        raise RuntimeError(f"Missing bundled audit prompt file: {path}") from error
    if not text:
        raise RuntimeError(f"Bundled audit prompt file is empty: {path}")
    return text


MLR_AUDIT_SYSTEM_PROMPT = _load_prompt_library_text("system_prompts/mlr-audit-system.md")
MLR_AUDIT_USER_PROMPT_TEMPLATE = _load_prompt_library_text(
    "default_prompts/mlr/audit/mlr-audit.md"
)


def mlr_audit_response_schema() -> dict[str, Any]:
    issue_field_enum = list(MLR_AUDIT_ISSUE_FIELDS)
    updatable_field_enum = list(MLR_AUDIT_UPDATABLE_FIELDS)
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "status": {"type": "string", "enum": list(MLR_AUDIT_ALLOWED_STATUSES)},
            "confidence": {"type": "number"},
            "is_learnworthy": {"type": "boolean"},
            "auto_fix_allowed": {"type": "boolean"},
            "summary": {"type": "string"},
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "severity": {"type": "string", "enum": list(MLR_AUDIT_ALLOWED_SEVERITIES)},
                        "field": {"type": "string", "enum": issue_field_enum},
                        "issue": {"type": "string"},
                    },
                    "required": ["severity", "field", "issue"],
                },
            },
            "fields_to_update": {
                "type": "array",
                "items": {"type": "string", "enum": updatable_field_enum},
            },
            "recommended_tags": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "status",
            "confidence",
            "is_learnworthy",
            "auto_fix_allowed",
            "summary",
            "issues",
            "fields_to_update",
            "recommended_tags",
        ],
    }


MLR_AUDIT_PRESET = AuditSchemaPreset(
    preset_id=AUDIT_SCHEMA_PRESET_MLR,
    name="MLR Audit",
    note_type_name=MLR_NOTE_TYPE_NAME,
    relevant_fields=MLR_AUDIT_RELEVANT_FIELDS,
    updatable_fields=MLR_AUDIT_UPDATABLE_FIELDS,
    issue_fields=MLR_AUDIT_ISSUE_FIELDS,
    allowed_statuses=MLR_AUDIT_ALLOWED_STATUSES,
    allowed_severities=MLR_AUDIT_ALLOWED_SEVERITIES,
    default_system_prompt=MLR_AUDIT_SYSTEM_PROMPT,
    default_user_prompt_template=MLR_AUDIT_USER_PROMPT_TEMPLATE,
    schema_builder=mlr_audit_response_schema,
)


def get_audit_schema_preset(preset_id: str | None) -> AuditSchemaPreset:
    normalized = (preset_id or AUDIT_SCHEMA_PRESET_MLR).strip().lower()
    if normalized in {AUDIT_SCHEMA_PRESET_MLR, "mlr", "mlr audit"}:
        return MLR_AUDIT_PRESET
    raise ValueError(f"Unknown audit schema preset '{preset_id}'.")


def available_audit_schema_presets() -> list[AuditSchemaPreset]:
    return [MLR_AUDIT_PRESET]
