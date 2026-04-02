from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
import math
from typing import Any, Callable

from aqt import mw
from aqt.browser import Browser
from aqt.operations import QueryOp
from aqt.utils import askUser, showCritical, showInfo, tooltip

from .config import AddonConfig, FieldMapping
from .openai_client import (
    OpenAIClientError,
    TokenUsage,
    count_request_input_tokens,
    request_field_updates,
)
from .pricing import estimate_cost_usd, resolve_model_pricing
from .prompting import extract_placeholders, render_prompt
from .usage_stats import record_usage_run


WRITE_MODE_APPEND = "append"
WRITE_MODE_OVERWRITE = "overwrite"


@dataclass(frozen=True)
class NoteSnapshot:
    note_id: int
    note_type_name: str
    fields: dict[str, str]
    output_fields: list[str]
    prompt_template: str
    system_prompt: str
    write_mode: str = WRITE_MODE_OVERWRITE


@dataclass(frozen=True)
class NoteUpdate:
    note_id: int
    output_fields: dict[str, str]
    usage: TokenUsage
    estimated_cost_usd: float | None
    write_mode: str = WRITE_MODE_OVERWRITE


@dataclass(frozen=True)
class NoteFailure:
    note_id: int
    note_type_name: str
    reason: str


@dataclass(frozen=True)
class ProcessingResult:
    updates: list[NoteUpdate]
    failures: list[NoteFailure]


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


@dataclass(frozen=True)
class PreparedManualProcessing:
    snapshots: list[NoteSnapshot]
    failures: list[NoteFailure]
    overwrite_count: int
    overwrite_fields: set[str]
    estimate: ProcessingEstimate | None


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
    op = QueryOp(
        parent=browser,
        op=lambda _col: _process_snapshots(config, prepared.snapshots, prepared.failures),
        success=lambda result: _finish_prepared_processing(
            browser,
            config,
            result,
            show_feedback=show_feedback,
            on_done=on_done,
        ),
    )
    op.with_progress(label=progress_label or f"Processing {len(prepared.snapshots)} note(s) with AI...")
    op.run_in_background()


def _build_snapshots(note_ids: list[int], config: AddonConfig) -> tuple[list[NoteSnapshot], list[NoteFailure]]:
    assert mw is not None and mw.col is not None

    snapshots: list[NoteSnapshot] = []
    failures: list[NoteFailure] = []

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
        missing_prompt_fields = _missing_prompt_fields(
            prompt_template=prompt_template,
            system_prompt=system_prompt,
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

    for note_id in note_ids:
        note = mw.col.get_note(note_id)
        if note is None:
            failures.append(NoteFailure(note_id=note_id, note_type_name="Unknown", reason="Note not found."))
            continue

        note_type = note.note_type()
        note_type_name = str(note_type["name"])
        available_fields = {field_name: note[field_name] for field_name in note.keys()}

        if spec.target_field not in available_fields:
            failures.append(
                NoteFailure(
                    note_id=note_id,
                    note_type_name=note_type_name,
                    reason=f"Target field '{spec.target_field}' does not exist on this note.",
                )
            )
            continue

        missing_prompt_fields = _missing_prompt_fields(
            prompt_template=spec.prompt_template,
            system_prompt=config.system_prompt,
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
                output_fields=[spec.target_field],
                prompt_template=spec.prompt_template,
                system_prompt=config.system_prompt,
                write_mode=spec.write_mode,
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
) -> ProcessingResult:
    updates_by_note_id: dict[int, NoteUpdate] = {}
    failures = list(initial_failures)
    max_workers = max(1, min(config.max_parallel_requests, config.batch_size))

    for batch in _chunked(snapshots, config.batch_size):
        if max_workers <= 1 or len(batch) <= 1:
            for snapshot in batch:
                update, failure = _process_single_snapshot(config, snapshot)
                if update is not None:
                    updates_by_note_id[update.note_id] = update
                if failure is not None:
                    failures.append(failure)
            continue

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_process_single_snapshot, config, snapshot): snapshot.note_id
                for snapshot in batch
            }
            for future in as_completed(futures):
                update, failure = future.result()
                if update is not None:
                    updates_by_note_id[update.note_id] = update
                if failure is not None:
                    failures.append(failure)

    updates = [
        updates_by_note_id[snapshot.note_id]
        for snapshot in snapshots
        if snapshot.note_id in updates_by_note_id
    ]
    return ProcessingResult(updates=updates, failures=failures)


def _apply_result(browser: Browser, config: AddonConfig, result: ProcessingResult, *, show_feedback: bool = True) -> None:
    assert mw is not None and mw.col is not None

    applied = 0
    for update in result.updates:
        note = mw.col.get_note(update.note_id)
        if note is None:
            continue
        changed = False
        for field_name, field_value in update.output_fields.items():
            next_value = _merge_field_value(
                current_value=note[field_name],
                generated_value=field_value,
                write_mode=update.write_mode,
            )
            if note[field_name] != next_value:
                note[field_name] = next_value
                changed = True
        if changed:
            mw.col.update_note(note)
            applied += 1

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
        if usage_totals["request_count"]:
            summary = (
                f"AI Automation processed {usage_totals['request_count']} note(s), "
                f"updated {applied}, used {usage_totals['total_tokens']:,} tokens"
            )
            if usage_totals["estimated_cost_usd"] is not None:
                summary += f", est. ${usage_totals['estimated_cost_usd']:.4f}"
            tooltip(summary + ".", parent=browser)
        elif applied:
            tooltip(f"AI Automation updated {applied} note(s).", parent=browser)

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


def _chunked(items: list[Any], size: int) -> list[list[Any]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _render_snapshot_prompts(snapshot: NoteSnapshot, config: AddonConfig) -> tuple[str, str]:
    prompt_values = dict(snapshot.fields)
    prompt_values["NoteType"] = snapshot.note_type_name
    prompt = render_prompt(snapshot.prompt_template, prompt_values)
    return snapshot.system_prompt, prompt


def _estimate_processing(config: AddonConfig, snapshots: list[NoteSnapshot]) -> ProcessingEstimate:
    input_tokens = 0
    heuristic_notes = 0
    for snapshot in snapshots:
        system_prompt, prompt = _render_snapshot_prompts(snapshot, config)
        try:
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
) -> tuple[NoteUpdate | None, NoteFailure | None]:
    pricing = resolve_model_pricing(config.model, config.model_pricing)
    try:
        system_prompt, prompt = _render_snapshot_prompts(snapshot, config)
        result = request_field_updates(
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
        )
        return (
            NoteUpdate(
                note_id=snapshot.note_id,
                output_fields=result.field_updates,
                usage=result.usage,
                estimated_cost_usd=estimate_cost_usd(
                    input_tokens=result.usage.input_tokens,
                    cached_input_tokens=result.usage.cached_input_tokens,
                    output_tokens=result.usage.output_tokens,
                    pricing=pricing,
                ),
                write_mode=snapshot.write_mode,
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
    prompt_template: str,
    system_prompt: str,
    available_fields: dict[str, str],
) -> list[str]:
    missing: list[str] = []
    seen: set[str] = set()
    placeholders = extract_placeholders(prompt_template) + extract_placeholders(system_prompt)
    for placeholder in placeholders:
        if placeholder == "NoteType":
            continue
        if placeholder not in available_fields and placeholder not in seen:
            missing.append(placeholder)
            seen.add(placeholder)
    return missing


def _merge_field_value(*, current_value: str, generated_value: str, write_mode: str) -> str:
    if write_mode != WRITE_MODE_APPEND:
        return generated_value
    if not current_value.strip():
        return generated_value
    if not generated_value.strip():
        return current_value
    return current_value.rstrip() + "\n\n" + generated_value.lstrip()


def _finish_prepared_processing(
    browser: Browser,
    config: AddonConfig,
    result: ProcessingResult,
    *,
    show_feedback: bool,
    on_done: Callable[[ProcessingResult], None] | None,
) -> None:
    _apply_result(browser, config, result, show_feedback=show_feedback)
    if on_done is not None:
        on_done(result)
