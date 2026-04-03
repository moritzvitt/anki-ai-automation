from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from aqt import mw

from .config import AddonConfig, Pipeline, PipelineStep, Workflow
from .workflow_engine import DeferredAuditApplication, WorkflowExecutionResult, execute_workflow


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
    deferred_audit_applications: list[DeferredAuditApplication]


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
                    deferred_audit_applications=[],
                )
            )
            continue

        if step.step_type == "run_workflow":
            workflow = workflow_lookup[step.workflow_id or ""]
            report = _execute_workflow_step(config, step, workflow, matched_contexts)
        elif step.step_type == "run_group":
            report = _execute_group_step(config, step, matched_contexts, workflow_lookup)
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


def _execute_workflow_step(
    config: AddonConfig,
    step: PipelineStep,
    workflow: Workflow,
    contexts: list[PipelineNoteContext],
) -> PipelineStepReport:
    note_ids = [context.note_id for context in contexts]
    execution = execute_workflow(config, workflow, note_ids=note_ids, show_feedback=False)

    for context in contexts:
        if context.note_id in execution.failed_note_ids:
            context.step_results[step.step_id] = "failed"
            context.failures.extend(
                [line.removeprefix("- ").strip() for line in execution.failures if f"note {context.note_id} " in line]
            )
            _refresh_context(context)
            continue
        if context.note_id in execution.succeeded_note_ids:
            context.step_results[step.step_id] = "success"
            for key, value in execution.artifacts_by_note_id.get(context.note_id, {}).items():
                context.artifacts[key] = value
        else:
            context.step_results[step.step_id] = "skipped"
        _refresh_context(context)

    return PipelineStepReport(
        step_id=step.step_id,
        step_type=step.step_type,
        matched_note_ids=note_ids,
        succeeded_note_ids=execution.succeeded_note_ids,
        failed_note_ids=execution.failed_note_ids,
        skipped_note_ids=execution.skipped_note_ids,
        details=execution.failures[:20],
        deferred_audit_applications=list(execution.deferred_audit_applications),
    )


def _execute_group_step(
    config: AddonConfig,
    step: PipelineStep,
    contexts: list[PipelineNoteContext],
    workflow_lookup: dict[str, Workflow],
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
            deferred_audit_applications=[],
        )

    all_succeeded: set[int] = set()
    all_failed: set[int] = set()
    details: list[str] = []
    deferred_audit_applications: list[DeferredAuditApplication] = []
    for workflow in workflows:
        active_contexts = [context for context in contexts if not context.stopped]
        if not active_contexts:
            break
        nested_report = _execute_workflow_step(config, step, workflow, active_contexts)
        all_succeeded.update(nested_report.succeeded_note_ids)
        all_failed.update(nested_report.failed_note_ids)
        details.extend(f"{workflow.name}: {detail}" for detail in nested_report.details)
        deferred_audit_applications.extend(nested_report.deferred_audit_applications)

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
        deferred_audit_applications=deferred_audit_applications,
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
        deferred_audit_applications=[],
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
        deferred_audit_applications=[],
    )
def _refresh_context(context: PipelineNoteContext) -> None:
    assert mw is not None and mw.col is not None
    note = mw.col.get_note(context.note_id)
    if note is None:
        return
    context.current_tags = {str(tag) for tag in note.tags}
    context.fields = {field_name: note[field_name] for field_name in note.keys()}
