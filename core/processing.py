from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
import math
import re
from threading import Event
from typing import Any, Callable

from aqt import mw
from aqt.browser import Browser
from aqt.qt import QDialog, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget
from aqt.operations import QueryOp
from aqt.utils import askUser, showCritical, showInfo

from .config import AddonConfig, FieldMapping
from ..services.openai_client import (
    OpenAIClientError,
    TokenUsage,
    count_request_input_tokens,
    count_request_input_tokens_for_text,
    request_field_updates,
    request_text_response,
)
from ..services.pricing import estimate_cost_usd, resolve_model_pricing
from .prompting import build_prompt_values, extract_placeholders, render_prompt
from .usage_stats import record_usage_run
from ..ui.tooltips import show_tooltip


WRITE_MODE_APPEND = "append"
WRITE_MODE_OVERWRITE = "overwrite"
WRITE_MODE_SKIP_NONEMPTY = "skip_nonempty"


@dataclass(frozen=True)
class NoteSnapshot:
    note_id: int
    note_type_name: str
    fields: dict[str, str]
    output_fields: list[str]
    prompt_template: str
    system_prompt: str
    write_mode: str = WRITE_MODE_OVERWRITE
    multiple_target_fields: bool = False
    convert_markdown_to_html: bool = False
    response_delimiter: str = ""


@dataclass(frozen=True)
class NoteUpdate:
    note_id: int
    output_fields: dict[str, str]
    usage: TokenUsage
    estimated_cost_usd: float | None
    write_mode: str = WRITE_MODE_OVERWRITE
    convert_markdown_to_html: bool = False


@dataclass(frozen=True)
class NoteFailure:
    note_id: int
    note_type_name: str
    reason: str


@dataclass(frozen=True)
class ProcessingResult:
    updates: list[NoteUpdate]
    failures: list[NoteFailure]
    was_cancelled: bool = False


@dataclass(frozen=True)
class ProcessingEstimate:
    input_tokens: int
    estimated_output_tokens: int
    estimated_total_tokens: int
    estimated_cost_usd: float | None
    heuristic_notes: int
    pricing_available: bool


@dataclass(frozen=True)
class ManualProcessingSpec:
    prompt_name: str
    prompt_template: str
    target_field: str
    system_prompt_name: str = ""
    system_prompt: str = ""
    write_mode: str = WRITE_MODE_OVERWRITE
    model: str = ""
    temperature: float | None = None
    multiple_target_fields: bool = False
    convert_markdown_to_html: bool = False
    response_delimiter: str = ""


@dataclass(frozen=True)
class PreparedManualProcessing:
    snapshots: list[NoteSnapshot]
    failures: list[NoteFailure]
    overwrite_count: int
    overwrite_fields: set[str]
    estimate: ProcessingEstimate | None


@dataclass(frozen=True)
class PromptRenderPlan:
    prompt_template: str
    prompt_fields: tuple[str, ...]


class ProcessingInterruptDialog(QDialog):
    def __init__(self, parent: QWidget, *, note_count: int) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI Processing")
        self.setModal(False)
        self.resize(380, 180)
        self._note_count = note_count

        layout = QVBoxLayout(self)
        self.status_label = QLabel(
            f"Processing {note_count} note(s) with AI.\n\n"
            "Click Interrupt to stop after the current in-flight request(s)."
        )
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(note_count)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.interrupt_button = QPushButton("Interrupt")
        layout.addWidget(self.interrupt_button)

    def set_progress(self, completed_count: int) -> None:
        self.progress_bar.setValue(completed_count)
        self.status_label.setText(
            f"Processing {self._note_count} note(s) with AI.\n\n"
            f"Completed {completed_count}/{self._note_count} note(s). "
            "Click Interrupt to stop after the current in-flight request(s)."
        )


def run_ai_processing(browser: Browser, config: AddonConfig, note_ids: list[int]) -> None:
    if mw is None or mw.col is None:
        showCritical("Anki collection is not available.", parent=browser)
        return

    snapshots, failures = _build_snapshots(note_ids, config)
    if failures and not snapshots:
        showCritical(_format_failure_report(failures), parent=browser)
        return

    overwrite_count, overwrite_fields = _count_overwrites(snapshots)
    _confirm_and_start_processing(
        browser,
        config,
        snapshots,
        failures,
        overwrite_count,
        overwrite_fields,
        None,
    )


def run_manual_ai_processing(
    browser: Browser,
    config: AddonConfig,
    note_ids: list[int],
    spec: ManualProcessingSpec,
) -> None:
    if mw is None or mw.col is None:
        showCritical("Anki collection is not available.", parent=browser)
        return

    run_config = replace(
        config,
        model=spec.model or config.model,
        system_prompt=spec.system_prompt or config.system_prompt,
        temperature=spec.temperature if spec.temperature is not None else config.temperature,
    )

    snapshots, failures = _build_manual_snapshots(note_ids, run_config, spec)
    if failures and not snapshots:
        showCritical(_format_failure_report(failures), parent=browser)
        return

    overwrite_count, overwrite_fields = _count_overwrites(snapshots)
    estimate = _estimate_processing(run_config, snapshots) if run_config.show_estimate_before_sending else None
    _confirm_and_start_processing(
        browser,
        run_config,
        snapshots,
        failures,
        overwrite_count,
        overwrite_fields,
        estimate,
    )


def prepare_manual_ai_processing(
    config: AddonConfig,
    note_ids: list[int],
    spec: ManualProcessingSpec,
    *,
    include_estimate: bool | None = None,
) -> PreparedManualProcessing:
    if mw is None or mw.col is None:
        raise OpenAIClientError("Anki collection is not available.")

    run_config = replace(
        config,
        model=spec.model or config.model,
        system_prompt=spec.system_prompt or config.system_prompt,
        temperature=spec.temperature if spec.temperature is not None else config.temperature,
    )
    snapshots, failures = _build_manual_snapshots(note_ids, run_config, spec)
    overwrite_count, overwrite_fields = _count_overwrites(snapshots)
    use_estimate = run_config.show_estimate_before_sending if include_estimate is None else include_estimate
    estimate = _estimate_processing(run_config, snapshots) if use_estimate else None
    return PreparedManualProcessing(
        snapshots=snapshots,
        failures=failures,
        overwrite_count=overwrite_count,
        overwrite_fields=overwrite_fields,
        estimate=estimate,
    )


def start_prepared_manual_processing(
    browser: Browser,
    config: AddonConfig,
    prepared: PreparedManualProcessing,
    *,
    progress_label: str | None = None,
    show_feedback: bool = True,
    on_done: Callable[[ProcessingResult], None] | None = None,
) -> None:
    cancel_event = Event()
    interrupt_dialog = ProcessingInterruptDialog(browser, note_count=len(prepared.snapshots))
    interrupt_dialog.interrupt_button.clicked.connect(lambda: _request_processing_interrupt(interrupt_dialog, cancel_event))
    interrupt_dialog.show()
    total_snapshots = len(prepared.snapshots)
    already_applied_note_ids: set[int] = set()
    already_applied_count = 0

    def report_progress(completed_count: int) -> None:
        if mw is None or not hasattr(mw, "taskman"):
            return
        mw.taskman.run_on_main(lambda: interrupt_dialog.set_progress(min(completed_count, total_snapshots)))

    def apply_batch_updates(batch_updates: list[NoteUpdate]) -> None:
        nonlocal already_applied_count
        if mw is None or mw.col is None or not batch_updates:
            return
        already_applied_count += _apply_note_updates(batch_updates)
        already_applied_note_ids.update(update.note_id for update in batch_updates)

    op = QueryOp(
        parent=browser,
        op=lambda _col: asyncio.run(
            _process_snapshots_async(
                config,
                prepared.snapshots,
                prepared.failures,
                cancel_event=cancel_event,
                progress_callback=report_progress,
                batch_apply_callback=apply_batch_updates,
            )
        ),
        success=lambda result: _finish_prepared_processing(
            browser,
            config,
            result,
            interrupt_dialog=interrupt_dialog,
            show_feedback=show_feedback,
            on_done=on_done,
            already_applied_note_ids=already_applied_note_ids,
            already_applied_count=already_applied_count,
        ),
    )
    op.with_progress(label=progress_label or f"Processing {len(prepared.snapshots)} note(s) with AI...")
    op.run_in_background()


def execute_prepared_manual_processing(
    config: AddonConfig,
    prepared: PreparedManualProcessing,
) -> ProcessingResult:
    """Synchronous workflow execution hook used by higher-level pipeline orchestration.

    This runs the prepared snapshots and records usage, but does not apply note
    updates or refresh UI state. Callers that run this in a background worker
    must apply the returned updates on the main thread.
    """
    if mw is None or mw.col is None:
        raise OpenAIClientError("Anki collection is not available.")

    result = _process_snapshots(config, prepared.snapshots, prepared.failures)

    usage_totals = _aggregate_usage(result.updates)
    if usage_totals["request_count"]:
        record_usage_run(
            model=config.model,
            note_count=usage_totals["request_count"],
            request_count=usage_totals["request_count"],
            input_tokens=usage_totals["input_tokens"],
            cached_input_tokens=usage_totals["cached_input_tokens"],
            output_tokens=usage_totals["output_tokens"],
            reasoning_tokens=usage_totals["reasoning_tokens"],
            total_tokens=usage_totals["total_tokens"],
            estimated_cost_usd=usage_totals["estimated_cost_usd"],
            history_limit=config.usage_history_limit,
        )

    return result


def apply_processing_result_updates(result: ProcessingResult) -> int:
    """Apply field-update workflow note changes on the main thread."""
    applied = _apply_note_updates(result.updates)
    if mw is not None:
        mw.reset()
    return applied


def _build_snapshots(note_ids: list[int], config: AddonConfig) -> tuple[list[NoteSnapshot], list[NoteFailure]]:
    assert mw is not None and mw.col is not None

    snapshots: list[NoteSnapshot] = []
    failures: list[NoteFailure] = []
    placeholder_cache: dict[tuple[str, str], tuple[tuple[str, ...], tuple[str, ...]]] = {}

    for note_id in note_ids:
        note = mw.col.get_note(note_id)
        if note is None:
            failures.append(NoteFailure(note_id=note_id, note_type_name="Unknown", reason="Note not found."))
            continue

        note_type = note.note_type()
        note_type_name = str(note_type["name"])
        available_fields = {field_name: note[field_name] for field_name in note.keys()}
        mapping = _match_mapping(note_type_name, config.field_mappings)
        if mapping is None:
            failures.append(
                NoteFailure(
                    note_id=note_id,
                    note_type_name=note_type_name,
                    reason="No field mapping matched this note type.",
                )
            )
            continue

        missing_outputs = [field for field in mapping.output_fields if field not in available_fields]
        system_prompt = mapping.system_prompt or config.system_prompt
        prompt_template = mapping.prompt_template or config.default_prompt_template
        placeholder_key = (prompt_template, system_prompt)
        if placeholder_key not in placeholder_cache:
            prompt_fields = tuple(extract_placeholders(prompt_template))
            system_prompt_fields = tuple(extract_placeholders(system_prompt))
            placeholder_cache[placeholder_key] = (prompt_fields, system_prompt_fields)
        else:
            prompt_fields, system_prompt_fields = placeholder_cache[placeholder_key]
        missing_prompt_fields = _missing_prompt_fields(
            prompt_fields=prompt_fields,
            system_prompt_fields=system_prompt_fields,
            available_fields=available_fields,
        )
        if missing_prompt_fields or missing_outputs:
            missing = ", ".join(missing_prompt_fields + missing_outputs)
            failures.append(
                NoteFailure(
                    note_id=note_id,
                    note_type_name=note_type_name,
                    reason=f"Referenced fields do not exist on the note: {missing}",
                )
            )
            continue

        snapshots.append(
            NoteSnapshot(
                note_id=note_id,
                note_type_name=note_type_name,
                fields=available_fields,
                output_fields=list(mapping.output_fields),
                prompt_template=prompt_template,
                system_prompt=system_prompt,
                write_mode=WRITE_MODE_OVERWRITE,
            )
        )

    return snapshots, failures


def _build_manual_snapshots(
    note_ids: list[int],
    config: AddonConfig,
    spec: ManualProcessingSpec,
) -> tuple[list[NoteSnapshot], list[NoteFailure]]:
    assert mw is not None and mw.col is not None

    snapshots: list[NoteSnapshot] = []
    failures: list[NoteFailure] = []
    prompt_fields = tuple(extract_placeholders(spec.prompt_template))
    system_prompt_fields = tuple(extract_placeholders(config.system_prompt))

    for note_id in note_ids:
        note = mw.col.get_note(note_id)
        if note is None:
            failures.append(NoteFailure(note_id=note_id, note_type_name="Unknown", reason="Note not found."))
            continue

        note_type = note.note_type()
        note_type_name = str(note_type["name"])
        available_fields = {field_name: note[field_name] for field_name in note.keys()}

        if spec.multiple_target_fields and spec.write_mode == WRITE_MODE_SKIP_NONEMPTY:
            failures.append(
                NoteFailure(
                    note_id=note_id,
                    note_type_name=note_type_name,
                    reason="Skip-if-not-empty mode is not supported with multiple target fields.",
                )
            )
            continue

        if spec.target_field not in available_fields:
            if not spec.multiple_target_fields:
                failures.append(
                    NoteFailure(
                        note_id=note_id,
                        note_type_name=note_type_name,
                        reason=f"Target field '{spec.target_field}' does not exist on this note.",
                    )
                )
                continue

        if (
            not spec.multiple_target_fields
            and spec.write_mode == WRITE_MODE_SKIP_NONEMPTY
            and available_fields.get(spec.target_field, "").strip()
        ):
            failures.append(
                NoteFailure(
                    note_id=note_id,
                    note_type_name=note_type_name,
                    reason=(
                        f"Skipped because target field '{spec.target_field}' already contains data."
                    ),
                )
            )
            continue

        missing_prompt_fields = _missing_prompt_fields(
            prompt_fields=prompt_fields,
            system_prompt_fields=system_prompt_fields,
            available_fields=available_fields,
        )
        if missing_prompt_fields:
            failures.append(
                NoteFailure(
                    note_id=note_id,
                    note_type_name=note_type_name,
                    reason=(
                        "Referenced fields do not exist on the note: "
                        + ", ".join(missing_prompt_fields)
                    ),
                )
            )
            continue

        snapshots.append(
            NoteSnapshot(
                note_id=note_id,
                note_type_name=note_type_name,
                fields=available_fields,
                output_fields=[] if spec.multiple_target_fields else [spec.target_field],
                prompt_template=spec.prompt_template,
                system_prompt=config.system_prompt,
                write_mode=spec.write_mode,
                multiple_target_fields=spec.multiple_target_fields,
                convert_markdown_to_html=spec.convert_markdown_to_html,
                response_delimiter=spec.response_delimiter,
            )
        )

    return snapshots, failures


def _match_mapping(note_type_name: str, mappings: list[FieldMapping]) -> FieldMapping | None:
    for mapping in mappings:
        if mapping.note_type == "*" or mapping.note_type == note_type_name:
            return mapping
    return None


def _count_overwrites(snapshots: list[NoteSnapshot]) -> tuple[int, set[str]]:
    overwrite_count = 0
    overwrite_fields: set[str] = set()

    for snapshot in snapshots:
        if snapshot.multiple_target_fields:
            continue
        note_has_existing_output = False
        for field_name in snapshot.output_fields:
            if snapshot.fields.get(field_name, "").strip():
                note_has_existing_output = True
                overwrite_fields.add(field_name)
        if note_has_existing_output:
            overwrite_count += 1

    return overwrite_count, overwrite_fields


def _process_snapshots(
    config: AddonConfig,
    snapshots: list[NoteSnapshot],
    initial_failures: list[NoteFailure],
    *,
    cancel_event: Event | None = None,
) -> ProcessingResult:
    return asyncio.run(
        _process_snapshots_async(
            config,
            snapshots,
            initial_failures,
            cancel_event=cancel_event,
        )
    )


async def _process_snapshots_async(
    config: AddonConfig,
    snapshots: list[NoteSnapshot],
    initial_failures: list[NoteFailure],
    *,
    cancel_event: Event | None = None,
    progress_callback: Callable[[int], None] | None = None,
    batch_apply_callback: Callable[[list[NoteUpdate]], None] | None = None,
) -> ProcessingResult:
    updates_by_note_id: dict[int, NoteUpdate] = {}
    failures = list(initial_failures)
    batch_size = max(1, config.batch_size)
    max_workers = max(1, min(config.max_parallel_requests, batch_size))
    was_cancelled = False
    completed_count = 0

    async def process_batch(batch_snapshots: list[NoteSnapshot]) -> tuple[list[NoteUpdate], list[NoteFailure]]:
        semaphore = asyncio.Semaphore(max_workers)
        render_plans: dict[tuple[str, str], PromptRenderPlan] = {}

        async def run_snapshot(snapshot: NoteSnapshot) -> tuple[NoteUpdate | None, NoteFailure | None]:
            if cancel_event is not None and cancel_event.is_set():
                return None, None
            async with semaphore:
                if cancel_event is not None and cancel_event.is_set():
                    return None, None
                plan_key = (snapshot.prompt_template, snapshot.system_prompt)
                render_plan = render_plans.get(plan_key)
                if render_plan is None:
                    render_plan = PromptRenderPlan(
                        prompt_template=snapshot.prompt_template,
                        prompt_fields=tuple(extract_placeholders(snapshot.prompt_template)),
                    )
                    render_plans[plan_key] = render_plan
                return await asyncio.to_thread(_process_single_snapshot, config, snapshot, render_plan)

        batch_updates_by_note_id: dict[int, NoteUpdate] = {}
        batch_failures: list[NoteFailure] = []
        tasks = [asyncio.create_task(run_snapshot(snapshot)) for snapshot in batch_snapshots]
        for completed in asyncio.as_completed(tasks):
            update, failure = await completed
            if update is not None:
                batch_updates_by_note_id[update.note_id] = update
            if failure is not None:
                batch_failures.append(failure)
        ordered_updates = [
            batch_updates_by_note_id[snapshot.note_id]
            for snapshot in batch_snapshots
            if snapshot.note_id in batch_updates_by_note_id
        ]
        return ordered_updates, batch_failures

    for batch_start in range(0, len(snapshots), batch_size):
        if cancel_event is not None and cancel_event.is_set():
            was_cancelled = True
            break

        batch_snapshots = snapshots[batch_start: batch_start + batch_size]
        batch_updates, batch_failures = await process_batch(batch_snapshots)
        completed_count += len(batch_snapshots)
        if progress_callback is not None:
            progress_callback(completed_count)
        for update in batch_updates:
            updates_by_note_id[update.note_id] = update
        failures.extend(batch_failures)

        if batch_apply_callback is not None and batch_updates and mw is not None and hasattr(mw, "taskman"):
            mw.taskman.run_on_main(lambda updates=list(batch_updates): batch_apply_callback(updates))

        if cancel_event is not None and cancel_event.is_set():
            was_cancelled = True
            break

    updates = [
        updates_by_note_id[snapshot.note_id]
        for snapshot in snapshots
        if snapshot.note_id in updates_by_note_id
    ]
    return ProcessingResult(updates=updates, failures=failures, was_cancelled=was_cancelled)


def _apply_note_updates(updates: list[NoteUpdate], *, skip_note_ids: set[int] | None = None) -> int:
    assert mw is not None and mw.col is not None

    applied = 0
    changed_notes = []
    for update in updates:
        if skip_note_ids is not None and update.note_id in skip_note_ids:
            continue
        note = mw.col.get_note(update.note_id)
        if note is None:
            continue
        changed = False
        for field_name, field_value in update.output_fields.items():
            next_value = _merge_field_value(
                current_value=note[field_name],
                generated_value=field_value,
                write_mode=update.write_mode,
                convert_markdown_to_html=update.convert_markdown_to_html,
            )
            if note[field_name] != next_value:
                note[field_name] = next_value
                changed = True
        if changed:
            changed_notes.append(note)
            applied += 1

    if changed_notes:
        if hasattr(mw.col, "update_notes"):
            mw.col.update_notes(changed_notes)
        else:
            for note in changed_notes:
                mw.col.update_note(note)
    return applied


def _apply_result(
    browser: Browser,
    config: AddonConfig,
    result: ProcessingResult,
    *,
    show_feedback: bool = True,
    already_applied_note_ids: set[int] | None = None,
    already_applied_count: int = 0,
) -> None:
    assert mw is not None and mw.col is not None

    applied = already_applied_count + _apply_note_updates(
        result.updates,
        skip_note_ids=already_applied_note_ids,
    )

    usage_totals = _aggregate_usage(result.updates)
    if usage_totals["request_count"]:
        record_usage_run(
            model=config.model,
            note_count=usage_totals["request_count"],
            request_count=usage_totals["request_count"],
            input_tokens=usage_totals["input_tokens"],
            cached_input_tokens=usage_totals["cached_input_tokens"],
            output_tokens=usage_totals["output_tokens"],
            reasoning_tokens=usage_totals["reasoning_tokens"],
            total_tokens=usage_totals["total_tokens"],
            estimated_cost_usd=usage_totals["estimated_cost_usd"],
            history_limit=config.usage_history_limit,
        )

    if hasattr(browser, "search"):
        browser.search()
    mw.reset()

    if show_feedback:
        if result.was_cancelled:
            summary = (
                f"AI Automation interrupted after {usage_totals['request_count']} processed request(s), "
                f"updated {applied}"
            )
            if usage_totals["total_tokens"]:
                summary += f", used {usage_totals['total_tokens']:,} tokens"
            if usage_totals["estimated_cost_usd"] is not None:
                summary += f", est. ${usage_totals['estimated_cost_usd']:.4f}"
            show_tooltip(summary + ".", parent=browser)
        elif usage_totals["request_count"]:
            summary = (
                f"AI Automation processed {usage_totals['request_count']} note(s), "
                f"updated {applied}, used {usage_totals['total_tokens']:,} tokens"
            )
            if usage_totals["estimated_cost_usd"] is not None:
                summary += f", est. ${usage_totals['estimated_cost_usd']:.4f}"
            show_tooltip(summary + ".", parent=browser)
        elif applied:
            show_tooltip(f"AI Automation updated {applied} note(s).", parent=browser)

        if result.failures:
            showInfo(_format_failure_report(result.failures), parent=browser)


def _format_failure_report(failures: list[NoteFailure]) -> str:
    lines = ["Some notes could not be processed:"]
    for failure in failures[:20]:
        lines.append(
            f"- Note {failure.note_id} ({failure.note_type_name}): {failure.reason}"
        )
    if len(failures) > 20:
        lines.append(f"- ...and {len(failures) - 20} more")
    return "\n".join(lines)


def _render_snapshot_prompts(
    snapshot: NoteSnapshot,
    _config: AddonConfig,
    *,
    render_plan: PromptRenderPlan | None = None,
    render_plans: dict[tuple[str, str], PromptRenderPlan] | None = None,
) -> tuple[str, str]:
    plan = render_plan
    if plan is None:
        plan_key = (snapshot.prompt_template, snapshot.system_prompt)
        if render_plans is not None:
            plan = render_plans.get(plan_key)
            if plan is None:
                plan = PromptRenderPlan(
                    prompt_template=snapshot.prompt_template,
                    prompt_fields=tuple(extract_placeholders(snapshot.prompt_template)),
                )
                render_plans[plan_key] = plan
        else:
            plan = PromptRenderPlan(
                prompt_template=snapshot.prompt_template,
                prompt_fields=tuple(extract_placeholders(snapshot.prompt_template)),
            )

    prompt_values = build_prompt_values(
        snapshot.fields,
        note_type_name=snapshot.note_type_name if "NoteType" in plan.prompt_fields else None,
    )
    prompt = render_prompt(plan.prompt_template, prompt_values)
    return snapshot.system_prompt, prompt


def _estimate_processing(config: AddonConfig, snapshots: list[NoteSnapshot]) -> ProcessingEstimate:
    input_tokens = 0
    heuristic_notes = 0
    render_plans: dict[tuple[str, str], PromptRenderPlan] = {}
    for snapshot in snapshots:
        system_prompt, prompt = _render_snapshot_prompts(snapshot, config, render_plans=render_plans)
        try:
            if snapshot.multiple_target_fields:
                input_tokens += count_request_input_tokens_for_text(
                    api_key=config.api_key,
                    model=config.model,
                    system_prompt=system_prompt,
                    user_prompt=prompt,
                    timeout_seconds=config.request_timeout_seconds,
                    reasoning_effort=config.reasoning_effort,
                )
            else:
                input_tokens += count_request_input_tokens(
                    api_key=config.api_key,
                    model=config.model,
                    system_prompt=system_prompt,
                    user_prompt=prompt,
                    output_fields=snapshot.output_fields,
                    timeout_seconds=config.request_timeout_seconds,
                    reasoning_effort=config.reasoning_effort,
                )
        except OpenAIClientError:
            heuristic_notes += 1
            input_tokens += _heuristic_token_count(system_prompt) + _heuristic_token_count(prompt)

    estimated_output_tokens = len(snapshots) * config.estimated_output_tokens_per_note
    pricing = resolve_model_pricing(config.model, config.model_pricing)
    estimated_cost = estimate_cost_usd(
        input_tokens=input_tokens,
        cached_input_tokens=0,
        output_tokens=estimated_output_tokens,
        pricing=pricing,
    )
    return ProcessingEstimate(
        input_tokens=input_tokens,
        estimated_output_tokens=estimated_output_tokens,
        estimated_total_tokens=input_tokens + estimated_output_tokens,
        estimated_cost_usd=estimated_cost,
        heuristic_notes=heuristic_notes,
        pricing_available=pricing is not None,
    )


def _process_single_snapshot(
    config: AddonConfig,
    snapshot: NoteSnapshot,
    render_plan: PromptRenderPlan | None = None,
) -> tuple[NoteUpdate | None, NoteFailure | None]:
    pricing = resolve_model_pricing(config.model, config.model_pricing)
    try:
        system_prompt, prompt = _render_snapshot_prompts(
            snapshot,
            config,
            render_plan=render_plan,
        )
        warning_lines: list[str] = []
        if snapshot.multiple_target_fields:
            text_result = request_text_response(
                api_key=config.api_key,
                model=config.model,
                system_prompt=system_prompt,
                user_prompt=prompt,
                timeout_seconds=config.request_timeout_seconds,
                max_retries=config.max_retries,
                retry_backoff_seconds=config.retry_backoff_seconds,
                temperature=config.temperature,
                reasoning_effort=config.reasoning_effort,
                use_chat_completions_api=config.use_chat_completions_api,
            )
            field_updates, parser_warnings = _parse_delimited_field_updates(
                response_text=text_result.output_text,
                response_delimiter=snapshot.response_delimiter,
                available_fields=list(snapshot.fields.keys()),
            )
            warning_lines.extend(parser_warnings)
            usage = text_result.usage
        else:
            structured_result = request_field_updates(
                api_key=config.api_key,
                model=config.model,
                system_prompt=system_prompt,
                user_prompt=prompt,
                output_fields=snapshot.output_fields,
                timeout_seconds=config.request_timeout_seconds,
                max_retries=config.max_retries,
                retry_backoff_seconds=config.retry_backoff_seconds,
                temperature=config.temperature,
                reasoning_effort=config.reasoning_effort,
                use_chat_completions_api=config.use_chat_completions_api,
            )
            field_updates = structured_result.field_updates
            usage = structured_result.usage
        if not field_updates:
            warning_lines.append("The response did not contain any matching field sections.")
            return (
                None,
                NoteFailure(
                    note_id=snapshot.note_id,
                    note_type_name=snapshot.note_type_name,
                    reason=" ".join(warning_lines),
                ),
            )
        return (
            NoteUpdate(
                note_id=snapshot.note_id,
                output_fields=field_updates,
                usage=usage,
                estimated_cost_usd=estimate_cost_usd(
                    input_tokens=usage.input_tokens,
                    cached_input_tokens=usage.cached_input_tokens,
                    output_tokens=usage.output_tokens,
                    pricing=pricing,
                ),
                write_mode=snapshot.write_mode,
                convert_markdown_to_html=snapshot.convert_markdown_to_html,
            ),
            None,
        )
    except OpenAIClientError as error:
        return (
            None,
            NoteFailure(
                note_id=snapshot.note_id,
                note_type_name=snapshot.note_type_name,
                reason=str(error),
            ),
        )
    except Exception as error:  # pragma: no cover - defensive for Anki runtime
        return (
            None,
            NoteFailure(
                note_id=snapshot.note_id,
                note_type_name=snapshot.note_type_name,
                reason=f"Unexpected error: {error}",
            ),
        )


def _confirm_and_start_processing(
    browser: Browser,
    config: AddonConfig,
    snapshots: list[NoteSnapshot],
    failures: list[NoteFailure],
    overwrite_count: int,
    overwrite_fields: set[str],
    estimate: ProcessingEstimate | None,
) -> None:
    confirmation_lines = [f"Ready to process {len(snapshots)} note(s) with model {config.model}."]
    has_multi_target_mode = any(snapshot.multiple_target_fields for snapshot in snapshots)

    if estimate is not None:
        confirmation_lines.extend(
            [
                "",
                "Estimated usage before sending:",
                f"- Input tokens: {estimate.input_tokens:,}",
                f"- Output tokens: {estimate.estimated_output_tokens:,}",
                f"- Total tokens: {estimate.estimated_total_tokens:,}",
            ]
        )
        if estimate.pricing_available and estimate.estimated_cost_usd is not None:
            confirmation_lines.append(f"- Estimated cost: ${estimate.estimated_cost_usd:.4f}")
        else:
            confirmation_lines.append("- Estimated cost: unavailable for this model until pricing is configured")
        confirmation_lines.append(
            f"- Output estimate assumes {config.estimated_output_tokens_per_note} output tokens per note"
        )
        if estimate.heuristic_notes:
            confirmation_lines.append(
                f"- {estimate.heuristic_notes} note(s) used a heuristic input-token estimate"
            )

    if failures:
        confirmation_lines.extend(["", f"{len(failures)} note(s) will be skipped due to config or note issues."])

    if overwrite_count:
        field_names = ", ".join(sorted(overwrite_fields))
        confirmation_lines.extend(
            [
                "",
                f"{overwrite_count} note(s) already contain data in output field(s): {field_names}.",
                "Continuing may overwrite existing content.",
            ]
        )
    elif has_multi_target_mode and any(snapshot.write_mode != WRITE_MODE_APPEND for snapshot in snapshots):
        confirmation_lines.extend(
            [
                "",
                "Delimited multi-field mode is enabled.",
                "Any parsed field section that matches a note field may overwrite existing content.",
            ]
        )

    confirmation_lines.extend(["", "Continue?"])
    confirmed = askUser("\n".join(confirmation_lines), parent=browser)
    if not confirmed:
        return

    start_prepared_manual_processing(
        browser,
        config,
        PreparedManualProcessing(
            snapshots=snapshots,
            failures=failures,
            overwrite_count=overwrite_count,
            overwrite_fields=overwrite_fields,
            estimate=estimate,
        ),
    )


def _heuristic_token_count(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def _aggregate_usage(updates: list[NoteUpdate]) -> dict[str, int | float | None]:
    total_cost = 0.0
    cost_known = False
    totals = {
        "request_count": len(updates),
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": None,
    }
    for update in updates:
        totals["input_tokens"] += update.usage.input_tokens
        totals["cached_input_tokens"] += update.usage.cached_input_tokens
        totals["output_tokens"] += update.usage.output_tokens
        totals["reasoning_tokens"] += update.usage.reasoning_tokens
        totals["total_tokens"] += update.usage.total_tokens
        if update.estimated_cost_usd is not None:
            total_cost += update.estimated_cost_usd
            cost_known = True
    if cost_known:
        totals["estimated_cost_usd"] = total_cost
    return totals


def _missing_prompt_fields(
    *,
    prompt_fields: tuple[str, ...] | list[str],
    system_prompt_fields: tuple[str, ...] | list[str],
    available_fields: dict[str, str],
) -> list[str]:
    missing: list[str] = []
    seen: set[str] = set()
    placeholders = list(prompt_fields) + list(system_prompt_fields)
    for placeholder in placeholders:
        if placeholder == "NoteType":
            continue
        if placeholder not in available_fields and placeholder not in seen:
            missing.append(placeholder)
            seen.add(placeholder)
    return missing


def _merge_field_value(
    *,
    current_value: str,
    generated_value: str,
    write_mode: str,
    convert_markdown_to_html: bool,
) -> str:
    next_generated_value = (
        _markdown_to_html(generated_value) if convert_markdown_to_html else generated_value
    )
    if write_mode != WRITE_MODE_APPEND:
        return next_generated_value
    if not current_value.strip():
        return next_generated_value
    if not next_generated_value.strip():
        return current_value
    return current_value.rstrip() + "\n\n" + next_generated_value.lstrip()


def _finish_prepared_processing(
    browser: Browser,
    config: AddonConfig,
    result: ProcessingResult,
    *,
    interrupt_dialog: ProcessingInterruptDialog | None,
    show_feedback: bool,
    on_done: Callable[[ProcessingResult], None] | None,
    already_applied_note_ids: set[int] | None = None,
    already_applied_count: int = 0,
) -> None:
    if interrupt_dialog is not None:
        interrupt_dialog.close()
    _apply_result(
        browser,
        config,
        result,
        show_feedback=show_feedback,
        already_applied_note_ids=already_applied_note_ids,
        already_applied_count=already_applied_count,
    )
    if on_done is not None:
        on_done(result)


def _request_processing_interrupt(dialog: ProcessingInterruptDialog, cancel_event: Event) -> None:
    cancel_event.set()
    dialog.interrupt_button.setEnabled(False)
    dialog.interrupt_button.setText("Interrupt Requested")


def _markdown_to_html(value: str) -> str:
    lines = value.strip().splitlines()
    if not lines:
        return ""

    blocks: list[str] = []
    paragraph_lines: list[str] = []
    list_items: list[str] = []
    ordered_list_items: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        if paragraph_lines:
            blocks.append("<p>" + "<br>".join(_format_inline_markdown(line) for line in paragraph_lines) + "</p>")
            paragraph_lines = []

    def flush_list() -> None:
        nonlocal list_items
        if list_items:
            blocks.append("<ul>" + "".join(f"<li>{item}</li>" for item in list_items) + "</ul>")
            list_items = []

    def flush_ordered_list() -> None:
        nonlocal ordered_list_items
        if ordered_list_items:
            blocks.append("<ol>" + "".join(f"<li>{item}</li>" for item in ordered_list_items) + "</ol>")
            ordered_list_items = []

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            flush_list()
            flush_ordered_list()
            continue
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading_match:
            flush_paragraph()
            flush_list()
            flush_ordered_list()
            level = len(heading_match.group(1))
            heading_text = _format_inline_markdown(heading_match.group(2).strip())
            blocks.append(f"<h{level}>{heading_text}</h{level}>")
            continue
        if stripped.startswith(("- ", "* ")):
            flush_paragraph()
            flush_ordered_list()
            list_items.append(_format_inline_markdown(stripped[2:].strip()))
            continue
        ordered_list_match = re.match(r"^\d+\.\s+(.+)$", stripped)
        if ordered_list_match:
            flush_paragraph()
            flush_list()
            ordered_list_items.append(_format_inline_markdown(ordered_list_match.group(1).strip()))
            continue
        flush_list()
        flush_ordered_list()
        paragraph_lines.append(stripped)

    flush_paragraph()
    flush_list()
    flush_ordered_list()
    return "\n".join(blocks)


def _format_inline_markdown(value: str) -> str:
    escaped = html.escape(value)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", escaped)
    escaped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', escaped)
    return escaped


def _parse_delimited_field_updates(
    *,
    response_text: str,
    response_delimiter: str,
    available_fields: list[str],
) -> tuple[dict[str, str], list[str]]:
    prefix, suffix = _split_field_delimiter(response_delimiter)
    field_lookup = {field_name.casefold(): field_name for field_name in available_fields}
    marker_pattern = re.compile(
        rf"(?m)^{re.escape(prefix)}\s*(?P<field>.+?)\s*{re.escape(suffix)}\s*$"
    )
    matches = list(marker_pattern.finditer(response_text))
    if not matches:
        raise OpenAIClientError(
            "The response did not contain any field markers that matched the configured delimiter."
        )

    parsed_updates: dict[str, str] = {}
    warnings: list[str] = []
    unknown_fields: list[str] = []

    for index, match in enumerate(matches):
        raw_field_name = match.group("field").strip()
        normalized_field_name = _normalize_delimited_field_name(raw_field_name)
        section_start = match.end()
        section_end = matches[index + 1].start() if index + 1 < len(matches) else len(response_text)
        section_value = response_text[section_start:section_end].strip()
        canonical_name = field_lookup.get(normalized_field_name.casefold())
        if canonical_name is None:
            unknown_fields.append(raw_field_name)
            continue
        if canonical_name in parsed_updates and section_value:
            parsed_updates[canonical_name] = parsed_updates[canonical_name].rstrip() + "\n\n" + section_value
            warnings.append(f"Field '{canonical_name}' appeared multiple times and its sections were merged.")
            continue
        parsed_updates[canonical_name] = section_value

    if unknown_fields:
        warnings.append(
            "Ignored unknown field section(s): " + ", ".join(sorted(set(unknown_fields))) + "."
        )
    return parsed_updates, warnings


def _normalize_delimited_field_name(value: str) -> str:
    normalized = value.strip()
    if normalized.startswith("{") and normalized.endswith("}") and len(normalized) >= 2:
        return normalized[1:-1].strip()
    return normalized


def _split_field_delimiter(delimiter: str) -> tuple[str, str]:
    normalized = delimiter.strip()
    if not normalized:
        raise OpenAIClientError("Multiple target field mode requires a response delimiter.")
    if "{field}" in normalized:
        prefix, suffix = normalized.split("{field}", 1)
        if not prefix and not suffix:
            raise OpenAIClientError("The response delimiter must include text around '{field}'.")
        return prefix, suffix

    match = re.match(r"^(?P<prefix>[^A-Za-z0-9]*).+?(?P<suffix>[^A-Za-z0-9]*)$", normalized)
    if match is None:
        raise OpenAIClientError(
            "The response delimiter must look like '--Notes--' or include a '{field}' placeholder."
        )
    prefix = match.group("prefix")
    suffix = match.group("suffix")
    if not prefix and not suffix:
        raise OpenAIClientError(
            "The response delimiter must look like '--Notes--' or include a '{field}' placeholder."
        )
    return prefix, suffix
