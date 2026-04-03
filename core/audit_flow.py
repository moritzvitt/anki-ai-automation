from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from aqt import mw
from aqt.browser import Browser
from aqt.operations import QueryOp
from aqt.utils import showCritical, showInfo

from ..services.openai_client import (
    OpenAIClientError,
    TokenUsage,
    request_responses_json_text,
)
from ..services.pricing import estimate_cost_usd, resolve_model_pricing
from ..ui.tooltips import show_tooltip
from .audit_prompts import (
    MLR_AUDIT_ISSUE_FIELDS,
    MLR_AUDIT_RELEVANT_FIELDS,
    MLR_AUDIT_UPDATABLE_FIELDS,
    MLR_NOTE_TYPE_NAME,
    MLR_AUDIT_SYSTEM_PROMPT,
    build_mlr_audit_user_prompt,
    mlr_audit_response_schema,
)
from .audit_storage import (
    get_note_audit_entry,
    load_audit_log,
    save_audit_log,
    set_note_audit_entry,
)
from .config import AddonConfig, ConfigError, load_config
from .usage_stats import record_usage_run


MAX_AUDIT_NOTES_PER_RUN = 15


class AuditStatus(StrEnum):
    GOOD = "GOOD"
    FIXABLE_MINOR = "FIXABLE_MINOR"
    FIXABLE_MAJOR = "FIXABLE_MAJOR"
    REJECT = "REJECT"
    SKIP = "SKIP"


class AuditSeverity(StrEnum):
    MINOR = "minor"
    MAJOR = "major"


class AuditField(StrEnum):
    CLOZE = "Cloze"
    LEMMA = "Lemma"
    SUBTITLE = "Subtitle"
    WORD_DEFINITION = "Word Definition"
    JAPANESE_NOTES = "Japanese Notes"
    NOTES = "Notes"
    GRAMMAR = "Grammar"
    OTHER = "Other"


STATUS_TAGS = {
    AuditStatus.GOOD: "ai_good",
    AuditStatus.FIXABLE_MINOR: "ai_fix_minor",
    AuditStatus.FIXABLE_MAJOR: "ai_fix_major",
    AuditStatus.REJECT: "ai_reject",
    AuditStatus.SKIP: "ai_skip",
}
ALL_STATUS_TAGS = tuple(STATUS_TAGS.values())
TAG_AI_CHECKED = "ai_checked"
TAG_AI_MANUAL_REVIEW = "ai_manual_review"
TAG_AI_DONE_TODAY = "ai_done_today"
TAG_AI_AUDIT_FAILED = "ai_audit_failed"

METADATA_FIELD_STATUS = "AI Audit Status"
METADATA_FIELD_SUMMARY = "AI Audit Summary"
METADATA_FIELD_CONFIDENCE = "AI Audit Confidence"
METADATA_FIELD_FIELDS_TO_UPDATE = "AI Fields To Update"
METADATA_FIELD_LAST_CHECKED = "AI Last Checked"
METADATA_FIELD_RAW = "AI Audit Raw"


@dataclass(frozen=True)
class AuditIssue:
    severity: AuditSeverity
    field: AuditField
    issue: str


@dataclass(frozen=True)
class AuditResult:
    status: AuditStatus
    confidence: float
    is_learnworthy: bool
    auto_fix_allowed: bool
    summary: str
    issues: list[AuditIssue]
    fields_to_update: list[str]
    recommended_tags: list[str]


@dataclass(frozen=True)
class AuditCandidate:
    note_id: int
    note_type_name: str
    fields: dict[str, str]


@dataclass(frozen=True)
class AuditSuccess:
    note_id: int
    note_type_name: str
    result: AuditResult
    usage: TokenUsage
    estimated_cost_usd: float | None
    checked_at: str
    raw_output: str


@dataclass(frozen=True)
class AuditFailure:
    note_id: int
    note_type_name: str
    reason: str
    checked_at: str | None = None
    raw_output: str | None = None
    usage: TokenUsage | None = None
    estimated_cost_usd: float | None = None


@dataclass(frozen=True)
class AuditRunResult:
    successes: list[AuditSuccess]
    failures: list[AuditFailure]
    skipped_before_run: list[str]


def run_browser_ai_audit(browser: Browser, note_ids: list[int]) -> None:
    # Browser entry point for the stage-1 audit pipeline. This is intentionally
    # diagnostic-only and does not rewrite learning content fields.
    try:
        config = load_config()
    except ConfigError as error:
        showCritical(str(error), parent=browser)
        return

    if not config.enabled:
        show_tooltip("AI Automation is disabled in the add-on config.", parent=browser)
        return

    if mw is None or mw.col is None:
        showCritical("Anki collection is not available.", parent=browser)
        return

    audit_log = load_audit_log()
    candidates, skipped_before_run = _prepare_audit_candidates(note_ids, audit_log)
    if not candidates:
        message = "No eligible Moritz Language Reactor notes found for AI audit."
        if skipped_before_run:
            message += "\n\n" + "\n".join(f"- {line}" for line in skipped_before_run[:10])
        showInfo(message, parent=browser)
        return

    op = QueryOp(
        parent=browser,
        op=lambda _col: _run_audit(config, candidates, skipped_before_run),
        success=lambda result: _apply_audit_result(browser, result),
    )
    op.with_progress(label=f"Auditing {len(candidates)} note(s) with AI...")
    op.run_in_background()


def _prepare_audit_candidates(
    note_ids: list[int],
    audit_log: dict[str, Any],
) -> tuple[list[AuditCandidate], list[str]]:
    assert mw is not None and mw.col is not None

    today = _today_key()
    candidates: list[AuditCandidate] = []
    skipped: list[str] = []

    for note_id in note_ids:
        if len(candidates) >= MAX_AUDIT_NOTES_PER_RUN:
            skipped.append(f"Stopped after the first {MAX_AUDIT_NOTES_PER_RUN} eligible notes.")
            break

        note = mw.col.get_note(note_id)
        if note is None:
            skipped.append(f"Note {note_id}: note not found.")
            continue

        note_type = note.note_type()
        note_type_name = str(note_type["name"]) if note_type else "Unknown"
        if note_type_name != MLR_NOTE_TYPE_NAME:
            skipped.append(f"Note {note_id}: note type is '{note_type_name}', not '{MLR_NOTE_TYPE_NAME}'.")
            continue

        entry = get_note_audit_entry(audit_log, note_id)
        if note.has_tag(TAG_AI_DONE_TODAY) and entry and str(entry.get("processed_on", "")) == today:
            skipped.append(f"Note {note_id}: already audited today.")
            continue

        missing_fields = [field for field in MLR_AUDIT_RELEVANT_FIELDS if field not in note]
        if missing_fields:
            skipped.append(f"Note {note_id}: missing fields: {', '.join(missing_fields)}.")
            continue

        candidates.append(
            AuditCandidate(
                note_id=note_id,
                note_type_name=note_type_name,
                fields={field_name: note[field_name] for field_name in MLR_AUDIT_RELEVANT_FIELDS},
            )
        )

    return candidates, skipped


def _run_audit(
    config: AddonConfig,
    candidates: list[AuditCandidate],
    skipped_before_run: list[str],
) -> AuditRunResult:
    successes: list[AuditSuccess] = []
    failures: list[AuditFailure] = []
    pricing = resolve_model_pricing(config.model, config.model_pricing)

    for candidate in candidates:
        checked_at = _timestamp_now()
        raw_output: str | None = None
        usage: TokenUsage | None = None
        estimated_cost: float | None = None
        try:
            response = request_responses_json_text(
                api_key=config.api_key,
                model=config.model,
                system_prompt=MLR_AUDIT_SYSTEM_PROMPT,
                user_prompt=build_mlr_audit_user_prompt(candidate.fields),
                schema_name="anki_mlr_audit",
                schema=mlr_audit_response_schema(),
                timeout_seconds=config.request_timeout_seconds,
                max_retries=config.max_retries,
                retry_backoff_seconds=config.retry_backoff_seconds,
                temperature=config.temperature,
                reasoning_effort=config.reasoning_effort,
            )
            raw_output = response.output_text
            usage = response.usage
            estimated_cost = estimate_cost_usd(
                input_tokens=usage.input_tokens,
                cached_input_tokens=usage.cached_input_tokens,
                output_tokens=usage.output_tokens,
                pricing=pricing,
            )
            parsed = json.loads(response.output_text)
            result = _validate_audit_response(parsed)
            successes.append(
                AuditSuccess(
                    note_id=candidate.note_id,
                    note_type_name=candidate.note_type_name,
                    result=result,
                    usage=usage,
                    estimated_cost_usd=estimated_cost,
                    checked_at=checked_at,
                    raw_output=response.output_text,
                )
            )
        except (OpenAIClientError, json.JSONDecodeError, ValueError) as error:
            failures.append(
                AuditFailure(
                    note_id=candidate.note_id,
                    note_type_name=candidate.note_type_name,
                    reason=str(error),
                    checked_at=checked_at,
                    raw_output=raw_output,
                    usage=usage,
                    estimated_cost_usd=estimated_cost,
                )
            )

    return AuditRunResult(
        successes=successes,
        failures=failures,
        skipped_before_run=skipped_before_run,
    )


def _validate_audit_response(value: Any) -> AuditResult:
    if not isinstance(value, dict):
        raise ValueError("Audit response must be a JSON object.")

    try:
        status = AuditStatus(str(value["status"]))
    except Exception as error:
        raise ValueError("Audit response has an invalid 'status'.") from error

    confidence = value.get("confidence")
    if not isinstance(confidence, (int, float)):
        raise ValueError("Audit response field 'confidence' must be a number.")

    is_learnworthy = value.get("is_learnworthy")
    if not isinstance(is_learnworthy, bool):
        raise ValueError("Audit response field 'is_learnworthy' must be boolean.")

    auto_fix_allowed = value.get("auto_fix_allowed")
    if not isinstance(auto_fix_allowed, bool):
        raise ValueError("Audit response field 'auto_fix_allowed' must be boolean.")

    summary = value.get("summary")
    if not isinstance(summary, str):
        raise ValueError("Audit response field 'summary' must be a string.")

    issues_raw = value.get("issues")
    if not isinstance(issues_raw, list):
        raise ValueError("Audit response field 'issues' must be an array.")
    issues: list[AuditIssue] = []
    for issue_index, issue_value in enumerate(issues_raw):
        if not isinstance(issue_value, dict):
            raise ValueError(f"Audit issue #{issue_index + 1} must be an object.")
        try:
            severity = AuditSeverity(str(issue_value["severity"]))
        except Exception as error:
            raise ValueError(f"Audit issue #{issue_index + 1} has an invalid severity.") from error
        field_name = issue_value.get("field")
        if not isinstance(field_name, str) or field_name not in MLR_AUDIT_ISSUE_FIELDS:
            raise ValueError(f"Audit issue #{issue_index + 1} has an invalid field.")
        issue_text = issue_value.get("issue")
        if not isinstance(issue_text, str):
            raise ValueError(f"Audit issue #{issue_index + 1} must contain a string issue.")
        issues.append(
            AuditIssue(
                severity=severity,
                field=AuditField(field_name),
                issue=issue_text.strip(),
            )
        )

    fields_raw = value.get("fields_to_update")
    if not isinstance(fields_raw, list):
        raise ValueError("Audit response field 'fields_to_update' must be an array.")
    fields_to_update: list[str] = []
    seen_fields: set[str] = set()
    for field_value in fields_raw:
        if not isinstance(field_value, str) or field_value not in MLR_AUDIT_UPDATABLE_FIELDS:
            raise ValueError("Audit response contains an invalid field in 'fields_to_update'.")
        if field_value not in seen_fields:
            fields_to_update.append(field_value)
            seen_fields.add(field_value)

    recommended_tags_raw = value.get("recommended_tags", [])
    if not isinstance(recommended_tags_raw, list):
        raise ValueError("Audit response field 'recommended_tags' must be an array when present.")
    recommended_tags = [tag.strip() for tag in recommended_tags_raw if isinstance(tag, str) and tag.strip()]

    return AuditResult(
        status=status,
        confidence=float(confidence),
        is_learnworthy=is_learnworthy,
        auto_fix_allowed=auto_fix_allowed,
        summary=summary.strip(),
        issues=issues,
        fields_to_update=fields_to_update,
        recommended_tags=recommended_tags,
    )


def _apply_audit_result(browser: Browser, result: AuditRunResult) -> None:
    assert mw is not None and mw.col is not None

    audit_log = load_audit_log()
    changed_notes = []
    current_model = ""
    try:
        current_model = load_config().model
    except ConfigError:
        current_model = ""

    for success in result.successes:
        note = mw.col.get_note(success.note_id)
        if note is None:
            continue

        _remove_status_tags(note)
        note.remove_tag(TAG_AI_AUDIT_FAILED)
        note.remove_tag(TAG_AI_MANUAL_REVIEW)
        note.add_tag(TAG_AI_CHECKED)
        note.add_tag(STATUS_TAGS[success.result.status])
        note.add_tag(TAG_AI_DONE_TODAY)
        if success.result.status in {AuditStatus.FIXABLE_MAJOR, AuditStatus.REJECT}:
            note.add_tag(TAG_AI_MANUAL_REVIEW)

        # Persist normalized audit values separately from the note tags so later
        # pipeline stages can route on validated data instead of raw model text.
        _write_audit_metadata_fields(note, success)
        changed_notes.append(note)
        set_note_audit_entry(
            audit_log,
            success.note_id,
            {
                "note_type_name": success.note_type_name,
                "processed_on": _today_key_from_timestamp(success.checked_at),
                "last_checked": success.checked_at,
                "status": success.result.status.value,
                "summary": success.result.summary,
                "confidence": success.result.confidence,
                "is_learnworthy": success.result.is_learnworthy,
                "auto_fix_allowed": success.result.auto_fix_allowed,
                "fields_to_update": list(success.result.fields_to_update),
                "issues": [
                    {
                        "severity": issue.severity.value,
                        "field": issue.field.value,
                        "issue": issue.issue,
                    }
                    for issue in success.result.issues
                ],
                "recommended_tags": list(success.result.recommended_tags),
                "usage": _usage_dict(success.usage),
                "model": current_model,
                "estimated_cost_usd": success.estimated_cost_usd,
                "raw_output": success.raw_output,
                "audit_failed": False,
            },
        )

    for failure in result.failures:
        note = mw.col.get_note(failure.note_id)
        if note is None:
            continue

        _remove_status_tags(note)
        note.remove_tag(TAG_AI_MANUAL_REVIEW)
        note.add_tag(TAG_AI_AUDIT_FAILED)
        note.add_tag(TAG_AI_DONE_TODAY)
        changed_notes.append(note)
        _write_failure_metadata_fields(note, failure)
        set_note_audit_entry(
            audit_log,
            failure.note_id,
            {
                "note_type_name": failure.note_type_name,
                "processed_on": _today_key_from_timestamp(failure.checked_at) if failure.checked_at else _today_key(),
                "last_checked": failure.checked_at,
                "audit_failed": True,
                "error": failure.reason,
                "usage": _usage_dict(failure.usage) if failure.usage else None,
                "estimated_cost_usd": failure.estimated_cost_usd,
                "raw_output": failure.raw_output,
            },
        )

    if changed_notes:
        if hasattr(mw.col, "update_notes"):
            mw.col.update_notes(changed_notes)
        else:
            for note in changed_notes:
                mw.col.update_note(note)

    save_audit_log(audit_log)
    _record_audit_usage(result)

    if hasattr(browser, "search"):
        browser.search()
    mw.reset()

    summary = (
        f"AI audit checked {len(result.successes)} note(s), "
        f"failed on {len(result.failures)}."
    )
    show_tooltip(summary, parent=browser)

    report_lines: list[str] = []
    if result.skipped_before_run:
        report_lines.append("Skipped before audit:")
        report_lines.extend(f"- {line}" for line in result.skipped_before_run[:10])
    if result.failures:
        if report_lines:
            report_lines.append("")
        report_lines.append("Audit failures:")
        report_lines.extend(
            f"- Note {failure.note_id} ({failure.note_type_name}): {failure.reason}"
            for failure in result.failures[:20]
        )
    if report_lines:
        showInfo("\n".join(report_lines), parent=browser)


def _remove_status_tags(note: Any) -> None:
    for tag in ALL_STATUS_TAGS:
        note.remove_tag(tag)


def _write_audit_metadata_fields(note: Any, success: AuditSuccess) -> None:
    _set_optional_field(note, METADATA_FIELD_STATUS, success.result.status.value)
    _set_optional_field(note, METADATA_FIELD_SUMMARY, success.result.summary)
    _set_optional_field(note, METADATA_FIELD_CONFIDENCE, f"{success.result.confidence:.3f}")
    _set_optional_field(note, METADATA_FIELD_FIELDS_TO_UPDATE, ", ".join(success.result.fields_to_update))
    _set_optional_field(note, METADATA_FIELD_LAST_CHECKED, success.checked_at)
    _set_optional_field(note, METADATA_FIELD_RAW, success.raw_output)


def _write_failure_metadata_fields(note: Any, failure: AuditFailure) -> None:
    _set_optional_field(note, METADATA_FIELD_STATUS, "")
    _set_optional_field(note, METADATA_FIELD_SUMMARY, f"Audit failed: {failure.reason}")
    _set_optional_field(note, METADATA_FIELD_CONFIDENCE, "")
    _set_optional_field(note, METADATA_FIELD_FIELDS_TO_UPDATE, "")
    _set_optional_field(note, METADATA_FIELD_LAST_CHECKED, failure.checked_at or _timestamp_now())
    _set_optional_field(note, METADATA_FIELD_RAW, failure.raw_output or "")


def _set_optional_field(note: Any, field_name: str, value: str) -> None:
    if field_name in note:
        note[field_name] = value


def _record_audit_usage(result: AuditRunResult) -> None:
    if not result.successes and not any(failure.usage for failure in result.failures):
        return

    try:
        config = load_config()
    except ConfigError:
        return

    request_count = 0
    input_tokens = 0
    cached_input_tokens = 0
    output_tokens = 0
    reasoning_tokens = 0
    total_tokens = 0
    estimated_cost_usd = 0.0
    has_cost = False

    for success in result.successes:
        request_count += 1
        input_tokens += success.usage.input_tokens
        cached_input_tokens += success.usage.cached_input_tokens
        output_tokens += success.usage.output_tokens
        reasoning_tokens += success.usage.reasoning_tokens
        total_tokens += success.usage.total_tokens
        if success.estimated_cost_usd is not None:
            estimated_cost_usd += success.estimated_cost_usd
            has_cost = True

    for failure in result.failures:
        if failure.usage is None:
            continue
        request_count += 1
        input_tokens += failure.usage.input_tokens
        cached_input_tokens += failure.usage.cached_input_tokens
        output_tokens += failure.usage.output_tokens
        reasoning_tokens += failure.usage.reasoning_tokens
        total_tokens += failure.usage.total_tokens
        if failure.estimated_cost_usd is not None:
            estimated_cost_usd += failure.estimated_cost_usd
            has_cost = True

    if request_count:
        record_usage_run(
            model=config.model,
            note_count=request_count,
            request_count=request_count,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost_usd if has_cost else None,
            history_limit=config.usage_history_limit,
        )


def _usage_dict(usage: TokenUsage) -> dict[str, int]:
    return {
        "input_tokens": usage.input_tokens,
        "cached_input_tokens": usage.cached_input_tokens,
        "output_tokens": usage.output_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
        "total_tokens": usage.total_tokens,
    }


def _timestamp_now() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _today_key() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def _today_key_from_timestamp(timestamp: str | None) -> str:
    if not timestamp:
        return _today_key()
    return timestamp.split(" ", 1)[0]
