from __future__ import annotations

import json
import re
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
    AUDIT_SCHEMA_PRESET_MLR,
    MLR_AUDIT_ALLOWED_SEVERITIES,
    MLR_AUDIT_ALLOWED_STATUSES,
    available_audit_schema_presets,
    get_audit_schema_preset,
)
from .audit_storage import (
    get_note_audit_entry,
    load_audit_log,
    save_audit_log,
    set_note_audit_entry,
)
from .config import AddonConfig, ConfigError, load_config
from .config import Workflow
from .prompting import render_prompt, strip_html_for_prompt
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
    AuditStatus.GOOD: "ai::audit::good",
    AuditStatus.FIXABLE_MINOR: "ai::audit::fix_minor",
    AuditStatus.FIXABLE_MAJOR: "ai::audit::fix_major",
    AuditStatus.REJECT: "ai::audit::reject",
    AuditStatus.SKIP: "ai::audit::skip",
}
ALL_STATUS_TAGS = tuple(STATUS_TAGS.values())
TAG_AI_CHECKED = "ai::audit::checked"
TAG_AI_MANUAL_REVIEW = "ai::review::manual"
TAG_AI_PROCESSED = "ai::audit::processed"
TAG_AI_AUDIT_FAILED = "ai::audit::failed"

METADATA_FIELD_STATUS = "AI Audit Status"
METADATA_FIELD_SUMMARY = "AI Audit Summary"
METADATA_FIELD_CONFIDENCE = "AI Audit Confidence"
METADATA_FIELD_FIELDS_TO_UPDATE = "AI Fields To Update"
METADATA_FIELD_LAST_CHECKED = "AI Last Checked"
METADATA_FIELD_RAW = "AI Audit Raw"


def _default_status_tag_map() -> dict[str, str]:
    return {
        AuditStatus.GOOD.value: "ai::audit::good",
        AuditStatus.FIXABLE_MINOR.value: "ai::audit::fix_minor",
        AuditStatus.FIXABLE_MAJOR.value: "ai::audit::fix_major",
        AuditStatus.REJECT.value: "ai::audit::reject",
        AuditStatus.SKIP.value: "ai::audit::skip",
    }


def _default_extra_status_tags() -> dict[str, list[str]]:
    return {
        AuditStatus.FIXABLE_MAJOR.value: [TAG_AI_MANUAL_REVIEW],
        AuditStatus.REJECT.value: [TAG_AI_MANUAL_REVIEW],
    }


def _default_metadata_field_map() -> dict[str, str]:
    return {
        "status": METADATA_FIELD_STATUS,
        "summary": METADATA_FIELD_SUMMARY,
        "confidence": METADATA_FIELD_CONFIDENCE,
        "fields_to_update": METADATA_FIELD_FIELDS_TO_UPDATE,
        "last_checked": METADATA_FIELD_LAST_CHECKED,
        "raw": METADATA_FIELD_RAW,
    }


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


@dataclass(frozen=True)
class AuditFieldSyncResult:
    updated_notes: int
    skipped_notes: int
    missing_notes: int


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
        success=lambda result: apply_audit_run_result(result, browser=browser),
    )
    op.with_progress(label=f"Auditing {len(candidates)} note(s) with AI...")
    op.run_in_background()


def _prepare_audit_candidates(
    note_ids: list[int],
    audit_log: dict[str, Any],
    *,
    relevant_fields: tuple[str, ...],
    note_type_filter: str | None,
    max_candidates: int | None = MAX_AUDIT_NOTES_PER_RUN,
) -> tuple[list[AuditCandidate], list[str]]:
    assert mw is not None and mw.col is not None

    today = _today_key()
    candidates: list[AuditCandidate] = []
    skipped: list[str] = []

    for note_id in note_ids:
        if max_candidates is not None and len(candidates) >= max_candidates:
            skipped.append(f"Stopped after the first {max_candidates} eligible notes.")
            break

        note = mw.col.get_note(note_id)
        if note is None:
            skipped.append(f"Note {note_id}: note not found.")
            continue

        note_type = note.note_type()
        note_type_name = str(note_type["name"]) if note_type else "Unknown"
        if note_type_filter and note_type_name != note_type_filter:
            skipped.append(f"Note {note_id}: note type is '{note_type_name}', not '{note_type_filter}'.")
            continue

        entry = get_note_audit_entry(audit_log, note_id)
        if entry and str(entry.get("processed_on", "")) == today:
            skipped.append(f"Note {note_id}: already audited today.")
            continue

        missing_fields = [field for field in relevant_fields if field not in note]
        if missing_fields:
            skipped.append(f"Note {note_id}: missing fields: {', '.join(missing_fields)}.")
            continue

        candidates.append(
            AuditCandidate(
                note_id=note_id,
                note_type_name=note_type_name,
                fields={
                    field_name: _normalize_audit_field_value(field_name, str(note[field_name]))
                    for field_name in relevant_fields
                },
            )
        )

    return candidates, skipped


def _run_audit(
    config: AddonConfig,
    workflow: Workflow,
    candidates: list[AuditCandidate],
    skipped_before_run: list[str],
    *,
    schema_name: str,
    schema: dict[str, Any],
    system_prompt: str,
    user_prompt_template: str,
    issue_fields: tuple[str, ...],
    updatable_fields: tuple[str, ...],
    allowed_statuses: tuple[str, ...],
    allowed_severities: tuple[str, ...],
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
                model=workflow.model or config.model,
                system_prompt=system_prompt,
                user_prompt=render_prompt(user_prompt_template, candidate.fields),
                schema_name=schema_name,
                schema=schema,
                timeout_seconds=config.request_timeout_seconds,
                max_retries=config.max_retries,
                retry_backoff_seconds=config.retry_backoff_seconds,
                temperature=workflow.temperature if workflow.temperature is not None else config.temperature,
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
            result = _validate_audit_response(
                parsed,
                issue_fields=issue_fields,
                updatable_fields=updatable_fields,
                allowed_statuses=allowed_statuses,
                allowed_severities=allowed_severities,
            )
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


def execute_audit_workflow(
    config: AddonConfig,
    workflow: Workflow,
    note_ids: list[int],
    *,
    max_notes: int | None = MAX_AUDIT_NOTES_PER_RUN,
) -> AuditRunResult:
    if mw is None or mw.col is None:
        raise OpenAIClientError("Anki collection is not available.")
    if workflow.workflow_type != "audit":
        raise OpenAIClientError(f"Workflow '{workflow.name}' is not an audit workflow.")
    if workflow.api_mode == "chat_completions":
        raise OpenAIClientError(
            "Audit workflows currently require structured output validation and only support the Responses API."
        )

    preset = get_audit_schema_preset(workflow.schema_preset or AUDIT_SCHEMA_PRESET_MLR)
    schema = preset.schema_builder()
    if workflow.response_schema_json:
        try:
            parsed_schema = json.loads(workflow.response_schema_json)
        except json.JSONDecodeError as error:
            raise OpenAIClientError(
                f"Workflow '{workflow.name}' has invalid response_schema_json: {error}"
            ) from error
        if not isinstance(parsed_schema, dict):
            raise OpenAIClientError(
                f"Workflow '{workflow.name}' response_schema_json must decode to a JSON object."
            )
        schema = parsed_schema

    audit_log = load_audit_log()
    candidates, skipped_before_run = _prepare_audit_candidates(
        note_ids,
        audit_log,
        relevant_fields=preset.relevant_fields,
        note_type_filter=workflow.note_type_filter or preset.note_type_name,
        max_candidates=max_notes,
    )
    system_prompt = _audit_system_prompt(config, workflow, preset)
    user_prompt_template = _audit_user_prompt_template(config, workflow, preset)
    return _run_audit(
        config,
        workflow,
        candidates,
        skipped_before_run,
        schema_name=f"{workflow.workflow_id}_schema",
        schema=schema,
        system_prompt=system_prompt,
        user_prompt_template=user_prompt_template,
        issue_fields=preset.issue_fields,
        updatable_fields=preset.updatable_fields,
        allowed_statuses=preset.allowed_statuses,
        allowed_severities=preset.allowed_severities,
    )


def execute_mlr_audit(
    config: AddonConfig,
    note_ids: list[int],
    *,
    max_notes: int | None = MAX_AUDIT_NOTES_PER_RUN,
) -> AuditRunResult:
    workflow = Workflow(
        workflow_id="mlr-audit",
        name="MLR Audit",
        query='note:"Moritz Language Reactor"',
        prompt_id="",
        workflow_type="audit",
        schema_preset=AUDIT_SCHEMA_PRESET_MLR,
        note_type_filter=get_audit_schema_preset(AUDIT_SCHEMA_PRESET_MLR).note_type_name,
    )
    return execute_audit_workflow(config, workflow, note_ids, max_notes=max_notes)


def _validate_audit_response(
    value: Any,
    *,
    issue_fields: tuple[str, ...],
    updatable_fields: tuple[str, ...],
    allowed_statuses: tuple[str, ...],
    allowed_severities: tuple[str, ...],
) -> AuditResult:
    if not isinstance(value, dict):
        raise ValueError("Audit response must be a JSON object.")

    try:
        raw_status = str(value["status"])
        if raw_status not in allowed_statuses:
            raise ValueError(raw_status)
        status = AuditStatus(raw_status)
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
            raw_severity = str(issue_value["severity"])
            if raw_severity not in allowed_severities:
                raise ValueError(raw_severity)
            severity = AuditSeverity(raw_severity)
        except Exception as error:
            raise ValueError(f"Audit issue #{issue_index + 1} has an invalid severity.") from error
        field_name = issue_value.get("field")
        if not isinstance(field_name, str) or field_name not in issue_fields:
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
        if not isinstance(field_value, str) or field_value not in updatable_fields:
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


def _audit_system_prompt(config: AddonConfig, workflow: Workflow, preset: Any) -> str:
    if workflow.system_prompt_id:
        prompt = next(
            (item for item in config.saved_system_prompts if item.prompt_id == workflow.system_prompt_id),
            None,
        )
        if prompt is not None:
            return prompt.prompt_text
    return preset.default_system_prompt


def _audit_user_prompt_template(config: AddonConfig, workflow: Workflow, preset: Any) -> str:
    if workflow.prompt_id:
        prompt = next((item for item in config.saved_prompts if item.prompt_id == workflow.prompt_id), None)
        if prompt is not None:
            return prompt.prompt_text
    return preset.default_user_prompt_template


def _normalize_audit_field_value(field_name: str, value: str) -> str:
    if field_name in (AuditField.CLOZE.value, AuditField.SUBTITLE.value):
        return strip_html_for_prompt(value)
    return value


def apply_audit_run_result(
    result: AuditRunResult,
    *,
    workflow: Workflow | None = None,
    config: AddonConfig | None = None,
    browser: Browser | None = None,
    show_feedback: bool = True,
) -> None:
    assert mw is not None and mw.col is not None

    audit_log = load_audit_log()
    changed_notes = []
    active_config = config
    if active_config is None:
        try:
            active_config = load_config()
        except ConfigError:
            active_config = None
    current_model = workflow.model if workflow is not None and workflow.model else (active_config.model if active_config is not None else "")
    status_tag_map = dict(workflow.status_tag_map) if workflow is not None and workflow.status_tag_map else _default_status_tag_map()
    extra_status_tags = dict(workflow.extra_status_tags) if workflow is not None and workflow.extra_status_tags else _default_extra_status_tags()
    success_tags = list(workflow.success_tags) if workflow is not None and workflow.success_tags else [TAG_AI_CHECKED, TAG_AI_PROCESSED]
    failure_tags = list(workflow.failure_tags) if workflow is not None and workflow.failure_tags else [TAG_AI_AUDIT_FAILED, TAG_AI_PROCESSED]
    clear_status_tags = list(workflow.clear_status_tags) if workflow is not None and workflow.clear_status_tags else list(status_tag_map.values())
    metadata_field_map = dict(workflow.metadata_field_map) if workflow is not None and workflow.metadata_field_map else _default_metadata_field_map()
    removable_audit_tags = set(clear_status_tags)
    removable_audit_tags.update(failure_tags)
    for tags in extra_status_tags.values():
        removable_audit_tags.update(tags)
    removable_audit_tags.add(TAG_AI_MANUAL_REVIEW)
    removable_audit_tags.add(TAG_AI_AUDIT_FAILED)

    for success in result.successes:
        note = mw.col.get_note(success.note_id)
        if note is None:
            continue

        _remove_named_tags(note, removable_audit_tags)
        for tag in success_tags:
            note.add_tag(tag)
        mapped_status_tag = status_tag_map.get(success.result.status.value)
        if mapped_status_tag:
            note.add_tag(mapped_status_tag)
        for tag in extra_status_tags.get(success.result.status.value, []):
            note.add_tag(tag)

        # Persist normalized audit values separately from the note tags so later
        # pipeline stages can route on validated data instead of raw model text.
        _write_audit_metadata_fields(
            note,
            success,
            metadata_field_map=metadata_field_map,
            include_raw_output=workflow.store_raw_output if workflow is not None else True,
        )
        changed_notes.append(note)
        set_note_audit_entry(
            audit_log,
            success.note_id,
            {
                "workflow_id": workflow.workflow_id if workflow is not None else None,
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
                "raw_output": success.raw_output if workflow is None or workflow.store_raw_output else None,
                "audit_failed": False,
            },
        )

    for failure in result.failures:
        note = mw.col.get_note(failure.note_id)
        if note is None:
            continue

        _remove_named_tags(note, removable_audit_tags)
        for tag in failure_tags:
            note.add_tag(tag)
        changed_notes.append(note)
        _write_failure_metadata_fields(
            note,
            failure,
            metadata_field_map=metadata_field_map,
            include_raw_output=workflow.store_raw_output if workflow is not None else True,
        )
        set_note_audit_entry(
            audit_log,
            failure.note_id,
            {
                "workflow_id": workflow.workflow_id if workflow is not None else None,
                "note_type_name": failure.note_type_name,
                "processed_on": _today_key_from_timestamp(failure.checked_at) if failure.checked_at else _today_key(),
                "last_checked": failure.checked_at,
                "audit_failed": True,
                "error": failure.reason,
                "usage": _usage_dict(failure.usage) if failure.usage else None,
                "estimated_cost_usd": failure.estimated_cost_usd,
                "raw_output": failure.raw_output if workflow is None or workflow.store_raw_output else None,
            },
        )

    if changed_notes:
        if hasattr(mw.col, "update_notes"):
            mw.col.update_notes(changed_notes)
        else:
            for note in changed_notes:
                mw.col.update_note(note)

    save_audit_log(audit_log)
    _record_audit_usage(result, config=active_config, workflow=workflow)

    if browser is not None and hasattr(browser, "search"):
        browser.search()
    mw.reset()

    if show_feedback:
        summary = (
            f"AI audit checked {len(result.successes)} note(s), "
            f"failed on {len(result.failures)}."
        )
        if browser is not None:
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


def sync_audit_fields_from_log(config: AddonConfig | None = None) -> AuditFieldSyncResult:
    """Backfill optional AI Audit note fields from the persisted audit log.

    This is useful after adding audit metadata fields to a note type after notes
    have already been audited, because the historic results already exist in
    `user_data/audit_log.json`.
    """
    assert mw is not None and mw.col is not None

    active_config = config
    if active_config is None:
        active_config = load_config()
    workflow_lookup = {workflow.workflow_id: workflow for workflow in active_config.workflows}
    audit_log = load_audit_log()
    note_entries = audit_log.get("notes")
    if not isinstance(note_entries, dict):
        return AuditFieldSyncResult(updated_notes=0, skipped_notes=0, missing_notes=0)

    changed_notes: list[Any] = []
    updated_notes = 0
    skipped_notes = 0
    missing_notes = 0

    for note_id_text, entry in note_entries.items():
        if not isinstance(entry, dict):
            skipped_notes += 1
            continue
        try:
            note_id = int(note_id_text)
        except (TypeError, ValueError):
            skipped_notes += 1
            continue

        note = mw.col.get_note(note_id)
        if note is None:
            missing_notes += 1
            continue

        workflow_id = entry.get("workflow_id")
        workflow = workflow_lookup.get(workflow_id) if isinstance(workflow_id, str) else None
        metadata_field_map = (
            dict(workflow.metadata_field_map)
            if workflow is not None and workflow.metadata_field_map
            else _default_metadata_field_map()
        )
        include_raw_output = workflow.store_raw_output if workflow is not None else True
        before = {field_name: note[field_name] for field_name in note.keys()}

        if entry.get("audit_failed"):
            failure = AuditFailure(
                note_id=note_id,
                note_type_name=str(entry.get("note_type_name", "Unknown")),
                reason=str(entry.get("error", "Unknown audit failure.")),
                checked_at=str(entry.get("last_checked") or "") or None,
                raw_output=str(entry.get("raw_output") or "") or None,
                usage=None,
                estimated_cost_usd=None,
            )
            _write_failure_metadata_fields(
                note,
                failure,
                metadata_field_map=metadata_field_map,
                include_raw_output=include_raw_output,
            )
        else:
            status_text = entry.get("status")
            try:
                status = AuditStatus(str(status_text))
            except Exception:
                skipped_notes += 1
                continue
            issues: list[AuditIssue] = []
            for issue_entry in entry.get("issues", []):
                if not isinstance(issue_entry, dict):
                    continue
                try:
                    issues.append(
                        AuditIssue(
                            severity=AuditSeverity(str(issue_entry.get("severity"))),
                            field=AuditField(str(issue_entry.get("field"))),
                            issue=str(issue_entry.get("issue", "")).strip(),
                        )
                    )
                except Exception:
                    continue
            success = AuditSuccess(
                note_id=note_id,
                note_type_name=str(entry.get("note_type_name", "Unknown")),
                result=AuditResult(
                    status=status,
                    confidence=float(entry.get("confidence", 0.0) or 0.0),
                    is_learnworthy=bool(entry.get("is_learnworthy", False)),
                    auto_fix_allowed=bool(entry.get("auto_fix_allowed", False)),
                    summary=str(entry.get("summary", "")).strip(),
                    issues=issues,
                    fields_to_update=[
                        str(field_name)
                        for field_name in entry.get("fields_to_update", [])
                        if isinstance(field_name, str)
                    ],
                    recommended_tags=[
                        str(tag)
                        for tag in entry.get("recommended_tags", [])
                        if isinstance(tag, str)
                    ],
                ),
                usage=TokenUsage(0, 0, 0, 0, 0),
                estimated_cost_usd=None,
                checked_at=str(entry.get("last_checked") or _timestamp_now()),
                raw_output=str(entry.get("raw_output") or ""),
            )
            _write_audit_metadata_fields(
                note,
                success,
                metadata_field_map=metadata_field_map,
                include_raw_output=include_raw_output,
            )

        after = {field_name: note[field_name] for field_name in note.keys()}
        if before != after:
            changed_notes.append(note)
            updated_notes += 1
        else:
            skipped_notes += 1

    if changed_notes:
        if hasattr(mw.col, "update_notes"):
            mw.col.update_notes(changed_notes)
        else:
            for note in changed_notes:
                mw.col.update_note(note)
        mw.reset()

    return AuditFieldSyncResult(
        updated_notes=updated_notes,
        skipped_notes=skipped_notes,
        missing_notes=missing_notes,
    )


def _remove_status_tags(note: Any) -> None:
    for tag in ALL_STATUS_TAGS:
        note.remove_tag(tag)


def _remove_named_tags(note: Any, tags: set[str] | list[str] | tuple[str, ...]) -> None:
    for tag in tags:
        note.remove_tag(tag)


def _write_audit_metadata_fields(
    note: Any,
    success: AuditSuccess,
    *,
    metadata_field_map: dict[str, str],
    include_raw_output: bool,
) -> None:
    _set_optional_field(note, metadata_field_map.get("status"), success.result.status.value)
    _set_optional_field(note, metadata_field_map.get("summary"), success.result.summary)
    _set_optional_field(note, metadata_field_map.get("confidence"), f"{success.result.confidence:.3f}")
    _set_optional_field(
        note,
        metadata_field_map.get("fields_to_update"),
        ", ".join(success.result.fields_to_update),
    )
    _set_optional_field(note, metadata_field_map.get("last_checked"), success.checked_at)
    _set_optional_field(note, metadata_field_map.get("raw"), success.raw_output if include_raw_output else "")


def _write_failure_metadata_fields(
    note: Any,
    failure: AuditFailure,
    *,
    metadata_field_map: dict[str, str],
    include_raw_output: bool,
) -> None:
    _set_optional_field(note, metadata_field_map.get("status"), "")
    _set_optional_field(note, metadata_field_map.get("summary"), f"Audit failed: {failure.reason}")
    _set_optional_field(note, metadata_field_map.get("confidence"), "")
    _set_optional_field(note, metadata_field_map.get("fields_to_update"), "")
    _set_optional_field(note, metadata_field_map.get("last_checked"), failure.checked_at or _timestamp_now())
    _set_optional_field(note, metadata_field_map.get("raw"), (failure.raw_output or "") if include_raw_output else "")


def _set_optional_field(note: Any, field_name: str | None, value: str) -> None:
    if field_name and field_name in note:
        note[field_name] = value


def _record_audit_usage(
    result: AuditRunResult,
    *,
    config: AddonConfig | None = None,
    workflow: Workflow | None = None,
) -> None:
    if not result.successes and not any(failure.usage for failure in result.failures):
        return

    active_config = config
    if active_config is None:
        try:
            active_config = load_config()
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
            model=workflow.model if workflow is not None and workflow.model else active_config.model,
            note_count=request_count,
            request_count=request_count,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost_usd if has_cost else None,
            history_limit=active_config.usage_history_limit,
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


def audit_success_artifact(success: AuditSuccess) -> dict[str, Any]:
    return {
        "status": success.result.status.value,
        "confidence": success.result.confidence,
        "is_learnworthy": success.result.is_learnworthy,
        "auto_fix_allowed": success.result.auto_fix_allowed,
        "summary": success.result.summary,
        "issues": [
            {
                "severity": issue.severity.value,
                "field": issue.field.value,
                "issue": issue.issue,
            }
            for issue in success.result.issues
        ],
        "fields_to_update": list(success.result.fields_to_update),
        "recommended_tags": list(success.result.recommended_tags),
        "checked_at": success.checked_at,
    }
