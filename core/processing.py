from __future__ import annotations

import asyncio
from dataclasses import replace
import math
from pathlib import Path
from threading import Event
import tempfile
from typing import Callable
import uuid

from aqt import mw
from aqt.browser import Browser
from aqt.operations import QueryOp
from aqt.utils import askUser, showCritical

from .config import AddonConfig, FieldMapping
from .processing_models import (
    ManualProcessingSpec,
    NoteFailure,
    NoteSnapshot,
    NoteUpdate,
    PreparedManualProcessing,
    ProcessingEstimate,
    ProcessingInterruptDialog,
    ProcessingResult,
    PromptRenderPlan,
    WRITE_MODE_APPEND,
    WRITE_MODE_OVERWRITE,
    WRITE_MODE_SKIP_NONEMPTY,
)
from .processing_support import (
    aggregate_usage,
    apply_note_updates,
    finish_prepared_processing,
    format_failure_report,
    missing_prompt_fields,
    request_processing_interrupt,
)
from .processing_text import parse_delimited_field_updates
from .prompting import build_prompt_values, extract_placeholders, render_prompt
from .prompting import strip_html_for_prompt
from .usage_stats import record_usage_run
from ..services.openai_client import (
    OpenAIClientError,
    count_request_input_tokens,
    count_request_input_tokens_for_text,
    request_field_updates,
    request_tts_audio,
    request_text_response,
)
from ..services.pricing import estimate_cost_usd, resolve_model_pricing


def run_ai_processing(browser: Browser, config: AddonConfig, note_ids: list[int]) -> None:
    if mw is None or mw.col is None:
        showCritical("Anki collection is not available.", parent=browser)
        return

    snapshots, failures = _build_snapshots(note_ids, config)
    if failures and not snapshots:
        showCritical(format_failure_report(failures), parent=browser)
        return

    overwrite_count, overwrite_fields = _count_overwrites(snapshots)
    _confirm_and_start_processing(browser, config, snapshots, failures, overwrite_count, overwrite_fields, None)


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
        showCritical(format_failure_report(failures), parent=browser)
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
    interrupt_dialog.interrupt_button.clicked.connect(
        lambda: request_processing_interrupt(interrupt_dialog, cancel_event)
    )
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
        already_applied_count += apply_note_updates(batch_updates)
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
        success=lambda result: finish_prepared_processing(
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
    *,
    cancel_event: Event | None = None,
    progress_callback: Callable[[int], None] | None = None,
) -> ProcessingResult:
    if mw is None or mw.col is None:
        raise OpenAIClientError("Anki collection is not available.")

    result = _process_snapshots(
        config,
        prepared.snapshots,
        prepared.failures,
        cancel_event=cancel_event,
        progress_callback=progress_callback,
    )

    usage_totals = aggregate_usage(result.updates)
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
    applied = apply_note_updates(result.updates)
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

        note_type_name = str(note.note_type()["name"])
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
            placeholder_cache[placeholder_key] = (
                tuple(extract_placeholders(prompt_template)),
                tuple(extract_placeholders(system_prompt)),
            )
        prompt_fields, system_prompt_fields = placeholder_cache[placeholder_key]
        missing_fields = missing_prompt_fields(
            prompt_fields=prompt_fields,
            system_prompt_fields=system_prompt_fields,
            available_fields=available_fields,
        )
        if missing_fields or missing_outputs:
            failures.append(
                NoteFailure(
                    note_id=note_id,
                    note_type_name=note_type_name,
                    reason=f"Referenced fields do not exist on the note: {', '.join(missing_fields + missing_outputs)}",
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

        note_type_name = str(note.note_type()["name"])
        available_fields = {field_name: note[field_name] for field_name in note.keys()}

        if spec.tts_enabled and spec.multiple_target_fields:
            failures.append(
                NoteFailure(
                    note_id=note_id,
                    note_type_name=note_type_name,
                    reason="TTS mode does not support multiple target fields.",
                )
            )
            continue

        if spec.multiple_target_fields and spec.write_mode == WRITE_MODE_SKIP_NONEMPTY:
            failures.append(
                NoteFailure(
                    note_id=note_id,
                    note_type_name=note_type_name,
                    reason="Skip-if-not-empty mode is not supported with multiple target fields.",
                )
            )
            continue

        if spec.target_field not in available_fields and not spec.multiple_target_fields:
            failures.append(
                NoteFailure(
                    note_id=note_id,
                    note_type_name=note_type_name,
                    reason=f"Target field '{spec.target_field}' does not exist on this note.",
                )
            )
            continue

        if spec.tts_enabled and spec.tts_source_field not in available_fields:
            failures.append(
                NoteFailure(
                    note_id=note_id,
                    note_type_name=note_type_name,
                    reason=f"TTS source field '{spec.tts_source_field}' does not exist on this note.",
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
                    reason=f"Skipped because target field '{spec.target_field}' already contains data.",
                )
            )
            continue

        if spec.tts_enabled:
            source_text = strip_html_for_prompt(available_fields.get(spec.tts_source_field, ""))
            if not source_text:
                failures.append(
                    NoteFailure(
                        note_id=note_id,
                        note_type_name=note_type_name,
                        reason=f"TTS source field '{spec.tts_source_field}' is empty.",
                    )
                )
                continue
        else:
            missing_fields = missing_prompt_fields(
                prompt_fields=prompt_fields,
                system_prompt_fields=system_prompt_fields,
                available_fields=available_fields,
            )
            if missing_fields:
                failures.append(
                    NoteFailure(
                        note_id=note_id,
                        note_type_name=note_type_name,
                        reason="Referenced fields do not exist on the note: " + ", ".join(missing_fields),
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
                convert_field_html_to_markdown=spec.convert_field_html_to_markdown,
                response_delimiter=spec.response_delimiter,
                tts_enabled=spec.tts_enabled,
                tts_source_field=spec.tts_source_field,
                tts_voice=spec.tts_voice,
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
    progress_callback: Callable[[int], None] | None = None,
) -> ProcessingResult:
    return asyncio.run(
        _process_snapshots_async(
            config,
            snapshots,
            initial_failures,
            cancel_event=cancel_event,
            progress_callback=progress_callback,
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

    updates = [updates_by_note_id[snapshot.note_id] for snapshot in snapshots if snapshot.note_id in updates_by_note_id]
    return ProcessingResult(updates=updates, failures=failures, was_cancelled=was_cancelled)


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
        convert_field_html_to_markdown=snapshot.convert_field_html_to_markdown,
    )
    prompt = render_prompt(plan.prompt_template, prompt_values)
    return snapshot.system_prompt, prompt


def _estimate_processing(config: AddonConfig, snapshots: list[NoteSnapshot]) -> ProcessingEstimate:
    input_tokens = 0
    heuristic_notes = 0
    render_plans: dict[tuple[str, str], PromptRenderPlan] = {}
    if any(snapshot.tts_enabled for snapshot in snapshots):
        input_tokens = sum(
            _heuristic_token_count(strip_html_for_prompt(snapshot.fields.get(snapshot.tts_source_field, "")))
            for snapshot in snapshots
        )
        return ProcessingEstimate(
            input_tokens=input_tokens,
            estimated_output_tokens=0,
            estimated_total_tokens=input_tokens,
            estimated_cost_usd=None,
            heuristic_notes=len(snapshots),
            pricing_available=False,
        )
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
        warning_lines: list[str] = []
        if snapshot.tts_enabled:
            source_text = strip_html_for_prompt(snapshot.fields.get(snapshot.tts_source_field, ""))
            tts_result = request_tts_audio(
                api_key=config.api_key,
                model=config.model,
                voice=snapshot.tts_voice,
                input_text=source_text,
                timeout_seconds=config.request_timeout_seconds,
                max_retries=config.max_retries,
                retry_backoff_seconds=config.retry_backoff_seconds,
            )
            media_filename = _store_tts_audio(
                note_id=snapshot.note_id,
                voice=snapshot.tts_voice,
                media_type=tts_result.media_type,
                audio_bytes=tts_result.audio_bytes,
            )
            field_updates = {snapshot.output_fields[0]: f"[sound:{media_filename}]"}
            usage = tts_result.usage
        else:
            system_prompt, prompt = _render_snapshot_prompts(snapshot, config, render_plan=render_plan)
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
                field_updates, parser_warnings = parse_delimited_field_updates(
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
            return None, NoteFailure(
                note_id=snapshot.note_id,
                note_type_name=snapshot.note_type_name,
                reason=" ".join(warning_lines),
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
        return None, NoteFailure(
            note_id=snapshot.note_id,
            note_type_name=snapshot.note_type_name,
            reason=str(error),
        )
    except Exception as error:  # pragma: no cover
        return None, NoteFailure(
            note_id=snapshot.note_id,
            note_type_name=snapshot.note_type_name,
            reason=f"Unexpected error: {error}",
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
            confirmation_lines.append(f"- {estimate.heuristic_notes} note(s) used a heuristic input-token estimate")

    if failures:
        confirmation_lines.extend(["", f"{len(failures)} note(s) will be skipped due to config or note issues."])

    if overwrite_count:
        confirmation_lines.extend(
            [
                "",
                f"{overwrite_count} note(s) already contain data in output field(s): {', '.join(sorted(overwrite_fields))}.",
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
    if not askUser("\n".join(confirmation_lines), parent=browser):
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


def _store_tts_audio(*, note_id: int, voice: str, media_type: str, audio_bytes: bytes) -> str:
    assert mw is not None and mw.col is not None
    media = getattr(mw.col, "media", None)
    if media is None:
        raise OpenAIClientError("Anki media collection is not available.")

    extension = _audio_extension_for_media_type(media_type)
    filename = f"ai-tts-note-{note_id}-{voice}-{uuid.uuid4().hex[:8]}.{extension}"
    write_data = getattr(media, "write_data", None)
    if callable(write_data):
        write_data(filename, audio_bytes)
        return filename

    add_file = getattr(media, "add_file", None)
    if callable(add_file):
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{extension}") as handle:
            handle.write(audio_bytes)
            temp_path = handle.name
        try:
            added = add_file(temp_path)
        finally:
            Path(temp_path).unlink(missing_ok=True)
        return str(added or filename)

    raise OpenAIClientError("This Anki version does not expose a supported media-write API.")


def _audio_extension_for_media_type(media_type: str) -> str:
    lowered = media_type.lower()
    if "wav" in lowered:
        return "wav"
    if "flac" in lowered:
        return "flac"
    if "ogg" in lowered or "opus" in lowered:
        return "ogg"
    return "mp3"
