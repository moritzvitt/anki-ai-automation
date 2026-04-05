from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from threading import Event
from typing import Callable

from aqt import mw

from .config import AddonConfig, SavedPrompt, Workflow
from .processing import (
    ManualProcessingSpec,
    ProcessingResult,
    apply_processing_result_updates,
    execute_prepared_manual_processing,
    prepare_manual_ai_processing,
)


@dataclass(frozen=True)
class DeferredFieldTagApplication:
    workflow_id: str
    success_note_ids: list[int]
    failure_note_ids: list[int]
    success_tags: list[str]
    failure_tags: list[str]


@dataclass(frozen=True)
class DeferredFieldUpdateApplication:
    workflow_id: str
    result: ProcessingResult


@dataclass(frozen=True)
class WorkflowExecutionResult:
    workflow_id: str
    workflow_name: str
    workflow_type: str
    matched_note_ids: list[int]
    succeeded_note_ids: list[int]
    failed_note_ids: list[int]
    skipped_note_ids: list[int]
    failures: list[str]
    updated_requests: int
    artifacts_by_note_id: dict[int, dict[str, object]]
    deferred_field_tag_applications: list[DeferredFieldTagApplication]
    deferred_field_update_applications: list[DeferredFieldUpdateApplication]


def execute_workflow(
    config: AddonConfig,
    workflow: Workflow,
    *,
    note_ids: list[int] | None = None,
    show_feedback: bool = False,
    skip_already_processed_today: bool = True,
    cancel_event: Event | None = None,
    progress_callback: Callable[[int], None] | None = None,
) -> WorkflowExecutionResult:
    matched_note_ids = (
        list(note_ids)
        if note_ids is not None
        else ([] if workflow.workflow_type == "script" and not workflow.query.strip() else _find_note_ids_for_query(workflow.query))
    )
    if workflow.workflow_type == "script":
        return _execute_script_workflow(workflow, matched_note_ids)
    if workflow.workflow_type != "field_update":
        raise RuntimeError(f"Unsupported workflow type '{workflow.workflow_type}'.")
    return _execute_field_update_workflow(
        config,
        workflow,
        matched_note_ids,
        cancel_event=cancel_event,
        progress_callback=progress_callback,
    )


def execute_workflow_by_id(
    config: AddonConfig,
    workflow_id: str,
    *,
    note_ids: list[int] | None = None,
    show_feedback: bool = False,
    skip_already_processed_today: bool = True,
    cancel_event: Event | None = None,
    progress_callback: Callable[[int], None] | None = None,
) -> WorkflowExecutionResult:
    workflow = next((item for item in config.workflows if item.workflow_id == workflow_id), None)
    if workflow is None:
        raise RuntimeError(f"Unknown workflow id '{workflow_id}'.")
    return execute_workflow(
        config,
        workflow,
        note_ids=note_ids,
        show_feedback=show_feedback,
        skip_already_processed_today=skip_already_processed_today,
        cancel_event=cancel_event,
        progress_callback=progress_callback,
    )


def _execute_field_update_workflow(
    config: AddonConfig,
    workflow: Workflow,
    note_ids: list[int],
    *,
    cancel_event: Event | None = None,
    progress_callback: Callable[[int], None] | None = None,
) -> WorkflowExecutionResult:
    ordered_note_ids = [int(note_id) for note_id in note_ids]
    prompt = next((item for item in config.saved_prompts if item.prompt_id == workflow.prompt_id), None)
    if prompt is None:
        raise RuntimeError(
            f"Workflow '{workflow.name}' references missing saved prompt '{workflow.prompt_id}'."
        )

    spec = ManualProcessingSpec(
        prompt_name=prompt.name,
        prompt_template=prompt.prompt_text,
        target_field=workflow.target_field,
        system_prompt_name=workflow.system_prompt_id or "",
        system_prompt=_system_prompt_text(config, workflow.system_prompt_id),
        write_mode=workflow.mode,
        model=workflow.model or config.model,
        temperature=workflow.temperature,
        multiple_target_fields=workflow.multiple_target_fields,
        convert_markdown_to_html=workflow.convert_markdown_to_html,
        convert_field_html_to_markdown=workflow.convert_field_html_to_markdown,
        response_delimiter=workflow.response_delimiter or "",
    )
    prepared = prepare_manual_ai_processing(config, note_ids, spec, include_estimate=False)
    result = execute_prepared_manual_processing(
        _workflow_run_config(config, workflow),
        prepared,
        cancel_event=cancel_event,
        progress_callback=progress_callback,
    )

    failed_note_ids = {failure.note_id for failure in prepared.failures}
    failed_note_ids.update(failure.note_id for failure in result.failures)
    succeeded_note_ids = [update.note_id for update in result.updates if update.note_id not in failed_note_ids]
    skipped_note_ids = [
        note_id
        for note_id in ordered_note_ids
        if note_id not in succeeded_note_ids and note_id not in failed_note_ids
    ]

    return WorkflowExecutionResult(
        workflow_id=workflow.workflow_id,
        workflow_name=workflow.name,
        workflow_type=workflow.workflow_type,
        matched_note_ids=ordered_note_ids,
        succeeded_note_ids=succeeded_note_ids,
        failed_note_ids=sorted(failed_note_ids),
        skipped_note_ids=skipped_note_ids,
        failures=[
            f"- note {failure.note_id} ({failure.note_type_name}): {failure.reason}"
            for failure in [*prepared.failures, *result.failures]
        ],
        updated_requests=len(result.updates),
        artifacts_by_note_id={},
        deferred_field_tag_applications=[
            DeferredFieldTagApplication(
                workflow_id=workflow.workflow_id,
                success_note_ids=succeeded_note_ids,
                failure_note_ids=sorted(failed_note_ids),
                success_tags=list(workflow.success_tags or []),
                failure_tags=list(workflow.failure_tags or []),
            )
        ]
        if workflow.success_tags or workflow.failure_tags
        else [],
        deferred_field_update_applications=[
            DeferredFieldUpdateApplication(
                workflow_id=workflow.workflow_id,
                result=result,
            )
        ]
        if result.updates
        else [],
    )


def _execute_script_workflow(
    workflow: Workflow,
    note_ids: list[int],
) -> WorkflowExecutionResult:
    command = (workflow.script_command or "").strip()
    if not command:
        raise RuntimeError(f"Workflow '{workflow.name}' has no script command configured.")
    env = os.environ.copy()
    env["AI_AUTOMATION_WORKFLOW_ID"] = workflow.workflow_id
    env["AI_AUTOMATION_WORKFLOW_NAME"] = workflow.name
    env["AI_AUTOMATION_WORKFLOW_TYPE"] = workflow.workflow_type
    env["AI_AUTOMATION_NOTE_IDS"] = ",".join(str(note_id) for note_id in note_ids)
    subprocess.run(
        command,
        shell=True,
        cwd=str(Path(__file__).resolve().parent.parent),
        env=env,
        check=True,
    )
    return WorkflowExecutionResult(
        workflow_id=workflow.workflow_id,
        workflow_name=workflow.name,
        workflow_type=workflow.workflow_type,
        matched_note_ids=list(note_ids),
        succeeded_note_ids=list(note_ids),
        failed_note_ids=[],
        skipped_note_ids=[],
        failures=[],
        updated_requests=0,
        artifacts_by_note_id={},
        deferred_field_tag_applications=[],
        deferred_field_update_applications=[],
    )


def _find_note_ids_for_query(query: str) -> list[int]:
    if mw is None or mw.col is None:
        raise RuntimeError("Anki collection is not available.")
    try:
        return [int(note_id) for note_id in mw.col.find_notes(query)]
    except Exception as error:  # pragma: no cover
        raise RuntimeError(str(error)) from error


def _system_prompt_text(config: AddonConfig, prompt_id: str | None) -> str:
    if prompt_id is None:
        return config.system_prompt
    prompt = next((item for item in config.saved_system_prompts if item.prompt_id == prompt_id), None)
    return prompt.prompt_text if prompt is not None else config.system_prompt


def _workflow_run_config(config: AddonConfig, workflow: Workflow) -> AddonConfig:
    if workflow.model is None and workflow.temperature is None:
        return config
    from dataclasses import replace

    return replace(
        config,
        model=workflow.model or config.model,
        temperature=workflow.temperature if workflow.temperature is not None else config.temperature,
    )


def apply_field_tag_result(application: DeferredFieldTagApplication) -> None:
    _apply_note_tags(application.success_note_ids, application.success_tags)
    _apply_note_tags(application.failure_note_ids, application.failure_tags)


def apply_field_update_result(application: DeferredFieldUpdateApplication) -> int:
    return apply_processing_result_updates(application.result)


def _apply_note_tags(note_ids: list[int], tags: list[str]) -> None:
    if not note_ids or not tags:
        return
    if mw is None or mw.col is None:
        raise RuntimeError("Anki collection is not available.")

    changed_notes = []
    for note_id in note_ids:
        note = mw.col.get_note(note_id)
        if note is None:
            continue
        changed = False
        for tag in tags:
            normalized = str(tag).strip()
            if not normalized:
                continue
            if not note.has_tag(normalized):
                note.add_tag(normalized)
                changed = True
        if changed:
            changed_notes.append(note)

    if changed_notes:
        if hasattr(mw.col, "update_notes"):
            mw.col.update_notes(changed_notes)
        else:
            for note in changed_notes:
                mw.col.update_note(note)
