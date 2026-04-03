from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from aqt import mw

from .audit_flow import (
    AuditRunResult,
    apply_audit_run_result,
    audit_success_artifact,
    execute_mlr_audit,
)
from .config import AddonConfig, Pipeline, PipelineStep, SavedPrompt, Workflow
from .processing import (
    ManualProcessingSpec,
    NoteFailure,
    PreparedManualProcessing,
    ProcessingResult,
    execute_prepared_manual_processing,
    prepare_manual_ai_processing,
)


@dataclass
class PipelineNoteContext:
    note_id: int
    note_type_name: str
    current_tags: set[str]
    fields: dict[str, str]
    artifacts: dict[str, Any] = field(default_factory=dict)
    step_results: dict[str, str] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    stopped: bool = False


@dataclass(frozen=True)
class PipelineStepReport:
    step_id: str
    step_type: str
    matched_note_ids: list[int]
    succeeded_note_ids: list[int]
    failed_note_ids: list[int]
    skipped_note_ids: list[int]
    details: list[str]


@dataclass(frozen=True)
class PipelineRunResult:
    pipeline_id: str
    pipeline_name: str
    selected_note_ids: list[int]
    step_reports: list[PipelineStepReport]
    contexts: list[PipelineNoteContext]


def execute_pipeline(config: AddonConfig, pipeline: Pipeline) -> PipelineRunResult:
    """Run a config-defined pipeline over a selected note set.

    Pipelines are the orchestration layer: they select notes once, then execute
    atomic workflow/audit/tag steps per note with declarative branching.
    """
    if mw is None or mw.col is None:
        raise RuntimeError("Anki collection is not available.")

    selected_note_ids = _find_note_ids_for_query(
        pipeline.note_selector.query,
        limit=pipeline.note_selector.limit,
    )
    contexts = _build_note_contexts(selected_note_ids)
    workflow_lookup = {workflow.workflow_id: workflow for workflow in config.workflows}
    prompt_lookup = {prompt.prompt_id: prompt for prompt in config.saved_prompts}

    step_reports: list[PipelineStepReport] = []
    for step in pipeline.steps:
        matched_contexts = [
            context
            for context in contexts
            if not context.stopped and _condition_matches(context, step.when)
        ]
        if not matched_contexts:
            step_reports.append(
                PipelineStepReport(
                    step_id=step.step_id,
                    step_type=step.step_type,
                    matched_note_ids=[],
                    succeeded_note_ids=[],
                    failed_note_ids=[],
                    skipped_note_ids=[context.note_id for context in contexts if not context.stopped],
                    details=["No notes matched this step's condition."],
                )
            )
            continue

        if step.step_type == "run_mlr_audit":
            report = _execute_audit_step(config, step, matched_contexts)
        elif step.step_type == "run_workflow":
            workflow = workflow_lookup[step.workflow_id or ""]
            prompt = prompt_lookup.get(workflow.prompt_id)
            if prompt is None:
                raise RuntimeError(
                    f"Pipeline step '{step.step_id}' references workflow '{workflow.name}' "
                    "but its saved prompt could not be found."
                )
            report = _execute_workflow_step(config, step, workflow, prompt, matched_contexts)
        elif step.step_type == "run_group":
            report = _execute_group_step(config, step, matched_contexts, workflow_lookup, prompt_lookup)
        elif step.step_type == "tag":
            report = _execute_tag_step(step, matched_contexts)
        elif step.step_type == "stop":
            report = _execute_stop_step(step, matched_contexts)
        else:  # pragma: no cover - config validation should prevent this.
            raise RuntimeError(f"Unsupported pipeline step type '{step.step_type}'.")
        step_reports.append(report)

    return PipelineRunResult(
        pipeline_id=pipeline.pipeline_id,
        pipeline_name=pipeline.name,
        selected_note_ids=selected_note_ids,
        step_reports=step_reports,
        contexts=contexts,
    )


def execute_pipeline_by_id(config: AddonConfig, pipeline_id: str) -> PipelineRunResult:
    pipeline = next((item for item in config.pipelines if item.pipeline_id == pipeline_id), None)
    if pipeline is None:
        raise RuntimeError(f"Unknown pipeline id '{pipeline_id}'.")
    return execute_pipeline(config, pipeline)


def _find_note_ids_for_query(query: str, *, limit: int | None = None) -> list[int]:
    assert mw is not None and mw.col is not None
    try:
        note_ids = [int(note_id) for note_id in mw.col.find_notes(query)]
    except Exception as error:  # pragma: no cover - Anki runtime wrapper
        raise RuntimeError(str(error)) from error
    if limit is not None:
        return note_ids[:limit]
    return note_ids


def _build_note_contexts(note_ids: list[int]) -> list[PipelineNoteContext]:
    assert mw is not None and mw.col is not None
    contexts: list[PipelineNoteContext] = []
    for note_id in note_ids:
        note = mw.col.get_note(note_id)
        if note is None:
            continue
        note_type = note.note_type()
        note_type_name = str(note_type["name"]) if note_type else "Unknown"
        contexts.append(
            PipelineNoteContext(
                note_id=note_id,
                note_type_name=note_type_name,
                current_tags={str(tag) for tag in note.tags},
                fields={field_name: note[field_name] for field_name in note.keys()},
            )
        )
    return contexts


def _condition_matches(context: PipelineNoteContext, condition: dict[str, Any] | None) -> bool:
    if not condition:
        return True
    if "all" in condition:
        values = condition["all"]
        return isinstance(values, list) and all(_condition_matches(context, item) for item in values if isinstance(item, dict))
    if "any" in condition:
        values = condition["any"]
        return isinstance(values, list) and any(_condition_matches(context, item) for item in values if isinstance(item, dict))
    if "not" in condition:
        nested = condition["not"]
        return isinstance(nested, dict) and not _condition_matches(context, nested)
    if "artifact_equals" in condition:
        path, expected = _read_binary_condition(condition["artifact_equals"], "artifact_equals")
        return _resolve_artifact_path(context.artifacts, path) == expected
    if "artifact_in" in condition:
        path, expected = _read_binary_condition(condition["artifact_in"], "artifact_in")
        return isinstance(expected, list) and _resolve_artifact_path(context.artifacts, path) in expected
    if "tag_present" in condition:
        return isinstance(condition["tag_present"], str) and condition["tag_present"] in context.current_tags
    if "tag_absent" in condition:
        return isinstance(condition["tag_absent"], str) and condition["tag_absent"] not in context.current_tags
    if "field_empty" in condition:
        field_name = condition["field_empty"]
        return isinstance(field_name, str) and not context.fields.get(field_name, "").strip()
    if "field_not_empty" in condition:
        field_name = condition["field_not_empty"]
        return isinstance(field_name, str) and bool(context.fields.get(field_name, "").strip())
    if "note_type_is" in condition:
        return isinstance(condition["note_type_is"], str) and context.note_type_name == condition["note_type_is"]
    if "previous_step_succeeded" in condition:
        step_id = condition["previous_step_succeeded"]
        return isinstance(step_id, str) and context.step_results.get(step_id) == "success"
    if "previous_step_failed" in condition:
        step_id = condition["previous_step_failed"]
        return isinstance(step_id, str) and context.step_results.get(step_id) == "failed"
    return False


def _read_binary_condition(value: Any, name: str) -> tuple[str, Any]:
    if not isinstance(value, list) or len(value) != 2 or not isinstance(value[0], str):
        raise RuntimeError(f"Pipeline condition '{name}' must be a two-item list starting with a path string.")
    return value[0], value[1]


def _resolve_artifact_path(artifacts: dict[str, Any], path: str) -> Any:
    current: Any = artifacts
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current


def _execute_audit_step(
    config: AddonConfig,
    step: PipelineStep,
    contexts: list[PipelineNoteContext],
) -> PipelineStepReport:
    note_ids = [context.note_id for context in contexts]
    result = execute_mlr_audit(config, note_ids, max_notes=None)
    apply_audit_run_result(result, show_feedback=False)

    success_by_note_id = {item.note_id: item for item in result.successes}
    failure_by_note_id = {item.note_id: item for item in result.failures}
    succeeded_note_ids: list[int] = []
    failed_note_ids: list[int] = []

    for context in contexts:
        success = success_by_note_id.get(context.note_id)
        failure = failure_by_note_id.get(context.note_id)
        if success is not None:
            context.artifacts["audit"] = audit_success_artifact(success)
            context.step_results[step.step_id] = "success"
            succeeded_note_ids.append(context.note_id)
            _refresh_context(context)
        elif failure is not None:
            context.step_results[step.step_id] = "failed"
            context.failures.append(failure.reason)
            failed_note_ids.append(context.note_id)
            _refresh_context(context)
        else:
            context.step_results[step.step_id] = "skipped"

    details = []
    if result.skipped_before_run:
        details.extend(result.skipped_before_run)
    return PipelineStepReport(
        step_id=step.step_id,
        step_type=step.step_type,
        matched_note_ids=note_ids,
        succeeded_note_ids=succeeded_note_ids,
        failed_note_ids=failed_note_ids,
        skipped_note_ids=[
            context.note_id
            for context in contexts
            if context.note_id not in succeeded_note_ids and context.note_id not in failed_note_ids
        ],
        details=details,
    )


def _execute_workflow_step(
    config: AddonConfig,
    step: PipelineStep,
    workflow: Workflow,
    prompt: SavedPrompt,
    contexts: list[PipelineNoteContext],
) -> PipelineStepReport:
    note_ids = [context.note_id for context in contexts]
    run_config, prepared = _prepare_workflow_run(config, workflow, prompt, note_ids)
    result = execute_prepared_manual_processing(run_config, prepared)

    failed_note_ids = {failure.note_id for failure in prepared.failures}
    failed_note_ids.update(failure.note_id for failure in result.failures)
    succeeded_note_ids: list[int] = []

    for context in contexts:
        if context.note_id in failed_note_ids:
            context.step_results[step.step_id] = "failed"
            reasons = [
                failure.reason
                for failure in [*prepared.failures, *result.failures]
                if failure.note_id == context.note_id
            ]
            context.failures.extend(reasons)
            _refresh_context(context)
            continue
        context.step_results[step.step_id] = "success"
        context.artifacts.setdefault("workflow", {})[workflow.workflow_id] = {
            "name": workflow.name,
            "target_field": workflow.target_field,
            "mode": workflow.mode,
        }
        succeeded_note_ids.append(context.note_id)
        _refresh_context(context)

    details = [failure.reason for failure in [*prepared.failures, *result.failures][:20]]
    return PipelineStepReport(
        step_id=step.step_id,
        step_type=step.step_type,
        matched_note_ids=note_ids,
        succeeded_note_ids=succeeded_note_ids,
        failed_note_ids=sorted(failed_note_ids),
        skipped_note_ids=[],
        details=details,
    )


def _execute_group_step(
    config: AddonConfig,
    step: PipelineStep,
    contexts: list[PipelineNoteContext],
    workflow_lookup: dict[str, Workflow],
    prompt_lookup: dict[str, SavedPrompt],
) -> PipelineStepReport:
    workflows = sorted(
        [workflow for workflow in workflow_lookup.values() if step.group_id in (workflow.group_ids or [])],
        key=lambda workflow: workflow.position,
    )
    if not workflows:
        return PipelineStepReport(
            step_id=step.step_id,
            step_type=step.step_type,
            matched_note_ids=[context.note_id for context in contexts],
            succeeded_note_ids=[],
            failed_note_ids=[],
            skipped_note_ids=[context.note_id for context in contexts],
            details=[f"Group '{step.group_id}' does not contain any workflows."],
        )

    all_succeeded: set[int] = set()
    all_failed: set[int] = set()
    details: list[str] = []
    for workflow in workflows:
        prompt = prompt_lookup.get(workflow.prompt_id)
        if prompt is None:
            details.append(f"Workflow '{workflow.name}' is missing its saved prompt.")
            for context in contexts:
                context.step_results[step.step_id] = "failed"
                context.failures.append(f"Workflow '{workflow.name}' is missing its saved prompt.")
                all_failed.add(context.note_id)
            continue
        active_contexts = [context for context in contexts if not context.stopped]
        if not active_contexts:
            break
        nested_report = _execute_workflow_step(config, step, workflow, prompt, active_contexts)
        all_succeeded.update(nested_report.succeeded_note_ids)
        all_failed.update(nested_report.failed_note_ids)
        details.extend(f"{workflow.name}: {detail}" for detail in nested_report.details)

    for context in contexts:
        if context.note_id in all_failed:
            context.step_results[step.step_id] = "failed"
        elif context.note_id in all_succeeded:
            context.step_results[step.step_id] = "success"
        else:
            context.step_results[step.step_id] = "skipped"

    return PipelineStepReport(
        step_id=step.step_id,
        step_type=step.step_type,
        matched_note_ids=[context.note_id for context in contexts],
        succeeded_note_ids=sorted(all_succeeded - all_failed),
        failed_note_ids=sorted(all_failed),
        skipped_note_ids=[
            context.note_id
            for context in contexts
            if context.note_id not in all_succeeded and context.note_id not in all_failed
        ],
        details=details,
    )


def _execute_tag_step(step: PipelineStep, contexts: list[PipelineNoteContext]) -> PipelineStepReport:
    assert mw is not None and mw.col is not None
    changed_notes = []
    for context in contexts:
        note = mw.col.get_note(context.note_id)
        if note is None:
            context.step_results[step.step_id] = "failed"
            context.failures.append("Note not found while applying tags.")
            continue
        for tag in step.remove_tags or []:
            note.remove_tag(tag)
        for tag in step.add_tags or []:
            note.add_tag(tag)
        changed_notes.append(note)
        context.step_results[step.step_id] = "success"
    if changed_notes:
        if hasattr(mw.col, "update_notes"):
            mw.col.update_notes(changed_notes)
        else:
            for note in changed_notes:
                mw.col.update_note(note)
    for context in contexts:
        _refresh_context(context)
    return PipelineStepReport(
        step_id=step.step_id,
        step_type=step.step_type,
        matched_note_ids=[context.note_id for context in contexts],
        succeeded_note_ids=[context.note_id for context in contexts if context.step_results.get(step.step_id) == "success"],
        failed_note_ids=[context.note_id for context in contexts if context.step_results.get(step.step_id) == "failed"],
        skipped_note_ids=[],
        details=[],
    )


def _execute_stop_step(step: PipelineStep, contexts: list[PipelineNoteContext]) -> PipelineStepReport:
    for context in contexts:
        context.stopped = True
        context.step_results[step.step_id] = "success"
    return PipelineStepReport(
        step_id=step.step_id,
        step_type=step.step_type,
        matched_note_ids=[context.note_id for context in contexts],
        succeeded_note_ids=[context.note_id for context in contexts],
        failed_note_ids=[],
        skipped_note_ids=[],
        details=["Stopped matched notes from continuing through the pipeline."],
    )


def _prepare_workflow_run(
    config: AddonConfig,
    workflow: Workflow,
    prompt: SavedPrompt,
    note_ids: list[int],
) -> tuple[AddonConfig, PreparedManualProcessing]:
    system_prompt_text = config.system_prompt
    if workflow.system_prompt_id is not None:
        system_prompt = next(
            (item for item in config.saved_system_prompts if item.prompt_id == workflow.system_prompt_id),
            None,
        )
        if system_prompt is not None:
            system_prompt_text = system_prompt.prompt_text

    run_config = replace(
        config,
        model=workflow.model or config.model,
        system_prompt=system_prompt_text,
        temperature=workflow.temperature if workflow.temperature is not None else config.temperature,
    )

    spec = ManualProcessingSpec(
        prompt_name=prompt.name,
        prompt_template=prompt.prompt_text,
        target_field=workflow.target_field,
        system_prompt_name=workflow.system_prompt_id or "",
        system_prompt=system_prompt_text,
        write_mode=workflow.mode,
        model=run_config.model,
        temperature=workflow.temperature,
        multiple_target_fields=workflow.multiple_target_fields,
        convert_markdown_to_html=workflow.convert_markdown_to_html,
        response_delimiter=workflow.response_delimiter or "",
    )
    return run_config, prepare_manual_ai_processing(run_config, note_ids, spec, include_estimate=False)


def _refresh_context(context: PipelineNoteContext) -> None:
    assert mw is not None and mw.col is not None
    note = mw.col.get_note(context.note_id)
    if note is None:
        return
    context.current_tags = {str(tag) for tag in note.tags}
    context.fields = {field_name: note[field_name] for field_name in note.keys()}
