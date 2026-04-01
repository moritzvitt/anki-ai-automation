from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

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
from .prompting import render_prompt
from .usage_stats import record_usage_run


@dataclass(frozen=True)
class NoteSnapshot:
    note_id: int
    note_type_name: str
    fields: dict[str, str]
    mapping: FieldMapping


@dataclass(frozen=True)
class NoteUpdate:
    note_id: int
    output_fields: dict[str, str]
    usage: TokenUsage
    estimated_cost_usd: float | None


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


def run_ai_processing(browser: Browser, config: AddonConfig, note_ids: list[int]) -> None:
    if mw is None or mw.col is None:
        showCritical("Anki collection is not available.", parent=browser)
        return

    snapshots, failures = _build_snapshots(note_ids, config)
    if failures and not snapshots:
        showCritical(_format_failure_report(failures), parent=browser)
        return

    overwrite_count, overwrite_fields = _count_overwrites(snapshots)
    if config.show_estimate_before_sending:
        op = QueryOp(
            parent=browser,
            op=lambda _col: _estimate_processing(config, snapshots),
            success=lambda estimate: _confirm_and_start_processing(
                browser,
                config,
                snapshots,
                failures,
                overwrite_count,
                overwrite_fields,
                estimate,
            ),
        )
        op.with_progress(label=f"Estimating token usage for {len(snapshots)} note(s)...")
        op.run_in_background()
        return

    _confirm_and_start_processing(
        browser,
        config,
        snapshots,
        failures,
        overwrite_count,
        overwrite_fields,
        None,
    )


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

        missing_inputs = [field for field in mapping.input_fields if field not in available_fields]
        missing_outputs = [field for field in mapping.output_fields if field not in available_fields]
        if missing_inputs or missing_outputs:
            missing = ", ".join(missing_inputs + missing_outputs)
            failures.append(
                NoteFailure(
                    note_id=note_id,
                    note_type_name=note_type_name,
                    reason=f"Configured fields do not exist on the note: {missing}",
                )
            )
            continue

        snapshots.append(
            NoteSnapshot(
                note_id=note_id,
                note_type_name=note_type_name,
                fields=available_fields,
                mapping=mapping,
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
        for field_name in snapshot.mapping.output_fields:
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
    updates: list[NoteUpdate] = []
    failures = list(initial_failures)
    pricing = resolve_model_pricing(config.model, config.model_pricing)

    for batch in _chunked(snapshots, config.batch_size):
        for snapshot in batch:
            try:
                system_prompt, prompt = _render_snapshot_prompts(snapshot, config)
                result = request_field_updates(
                    api_key=config.api_key,
                    model=config.model,
                    system_prompt=system_prompt,
                    user_prompt=prompt,
                    output_fields=snapshot.mapping.output_fields,
                    timeout_seconds=config.request_timeout_seconds,
                    max_retries=config.max_retries,
                    retry_backoff_seconds=config.retry_backoff_seconds,
                    temperature=config.temperature,
                    reasoning_effort=config.reasoning_effort,
                )
                updates.append(
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
                    )
                )
            except OpenAIClientError as error:
                failures.append(
                    NoteFailure(
                        note_id=snapshot.note_id,
                        note_type_name=snapshot.note_type_name,
                        reason=str(error),
                    )
                )
            except Exception as error:  # pragma: no cover - defensive for Anki runtime
                failures.append(
                    NoteFailure(
                        note_id=snapshot.note_id,
                        note_type_name=snapshot.note_type_name,
                        reason=f"Unexpected error: {error}",
                    )
                )

    return ProcessingResult(updates=updates, failures=failures)


def _apply_result(browser: Browser, config: AddonConfig, result: ProcessingResult) -> None:
    assert mw is not None and mw.col is not None

    applied = 0
    for update in result.updates:
        note = mw.col.get_note(update.note_id)
        if note is None:
            continue
        changed = False
        for field_name, field_value in update.output_fields.items():
            if note[field_name] != field_value:
                note[field_name] = field_value
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

    browser.search()
    mw.reset()

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
    prompt_template = snapshot.mapping.prompt_template or config.default_prompt_template
    system_prompt = snapshot.mapping.system_prompt or config.system_prompt
    prompt_values = {
        field_name: snapshot.fields[field_name]
        for field_name in snapshot.mapping.input_fields
    }
    prompt_values["NoteType"] = snapshot.note_type_name
    prompt = render_prompt(prompt_template, prompt_values)
    return system_prompt, prompt


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
                output_fields=snapshot.mapping.output_fields,
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

    op = QueryOp(
        parent=browser,
        op=lambda _col: _process_snapshots(config, snapshots, failures),
        success=lambda result: _apply_result(browser, config, result),
    )
    op.with_progress(label=f"Processing {len(snapshots)} note(s) with AI...")
    op.run_in_background()


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
