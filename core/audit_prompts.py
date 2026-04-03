from __future__ import annotations

from typing import Any


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

# This is the main customization point for the audit stage.
MLR_AUDIT_SYSTEM_PROMPT = (
    "You are auditing Japanese Anki cards for study quality. "
    "This stage is diagnostic only. "
    "Do not rewrite any card fields. "
    "Return only valid JSON that matches the requested schema."
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


def build_mlr_audit_user_prompt(fields: dict[str, str]) -> str:
    return (
        "Review this Japanese Anki card for study quality.\n\n"
        "Your task is diagnostic and routing-only.\n"
        "Do not rewrite any field content.\n"
        "Evaluate whether the card is good as-is, fixable with limited support-field changes, "
        "too risky for limited automatic fixing, unsuitable for study, or should be skipped.\n\n"
        "Use these criteria:\n"
        "1. Clear learning focus\n"
        "2. Natural and comprehensible Japanese\n"
        "3. Good cloze design\n"
        "4. Correct and useful meaning/explanations\n"
        "5. Appropriate amount of information\n"
        "6. No misleading or major errors\n\n"
        "Important rules:\n"
        "- Use GOOD only if the card is already study-ready.\n"
        "- Use FIXABLE_MINOR if only supporting fields need modest changes.\n"
        "- Use FIXABLE_MAJOR if the card may be repairable, but not safely through limited automatic changes.\n"
        "- Use REJECT if the card should not be learned in its current form.\n"
        "- Use SKIP if the card cannot be classified cleanly in this workflow.\n"
        "- fields_to_update may only include Japanese Notes, Notes, Word Definition, or Grammar.\n"
        "- Prefer minimal intervention.\n"
        "- Return JSON only.\n\n"
        "Card fields:\n"
        f"Cloze: {fields['Cloze']}\n"
        f"Lemma: {fields['Lemma']}\n"
        f"Subtitle: {fields['Subtitle']}\n"
        f"Word Definition: {fields['Word Definition']}\n"
        f"Japanese Notes: {fields['Japanese Notes']}\n"
        f"Notes: {fields['Notes']}\n"
        f"Grammar: {fields['Grammar']}\n"
    )
