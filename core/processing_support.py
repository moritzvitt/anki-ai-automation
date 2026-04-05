from __future__ import annotations

from threading import Event
from typing import Callable

from aqt import mw
from aqt.browser import Browser
from aqt.utils import showInfo

from ..ui.tooltips import show_tooltip
from .config_models import AddonConfig
from .processing_models import NoteFailure, NoteUpdate, ProcessingInterruptDialog, ProcessingResult
from .processing_text import markdown_to_html
from .usage_stats import record_usage_run


def apply_note_updates(updates: list[NoteUpdate], *, skip_note_ids: set[int] | None = None) -> int:
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
            next_value = merge_field_value(
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


def format_failure_report(failures: list[NoteFailure]) -> str:
    lines = ["Some notes could not be processed:"]
    for failure in failures[:20]:
        lines.append(f"- Note {failure.note_id} ({failure.note_type_name}): {failure.reason}")
    if len(failures) > 20:
        lines.append(f"- ...and {len(failures) - 20} more")
    return "\n".join(lines)


def aggregate_usage(updates: list[NoteUpdate]) -> dict[str, int | float | None]:
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


def missing_prompt_fields(
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


def merge_field_value(
    *,
    current_value: str,
    generated_value: str,
    write_mode: str,
    convert_markdown_to_html: bool,
) -> str:
    next_generated_value = markdown_to_html(generated_value) if convert_markdown_to_html else generated_value
    if write_mode != "append":
        return next_generated_value
    if not current_value.strip():
        return next_generated_value
    if not next_generated_value.strip():
        return current_value
    return current_value.rstrip() + "\n\n" + next_generated_value.lstrip()


def finish_prepared_processing(
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
    apply_result(
        browser,
        config,
        result,
        show_feedback=show_feedback,
        already_applied_note_ids=already_applied_note_ids,
        already_applied_count=already_applied_count,
    )
    if on_done is not None:
        on_done(result)


def request_processing_interrupt(dialog: ProcessingInterruptDialog, cancel_event: Event) -> None:
    cancel_event.set()
    dialog.set_interrupt_requested()


def apply_result(
    browser: Browser,
    config: AddonConfig,
    result: ProcessingResult,
    *,
    show_feedback: bool = True,
    already_applied_note_ids: set[int] | None = None,
    already_applied_count: int = 0,
) -> None:
    assert mw is not None and mw.col is not None

    applied = already_applied_count + apply_note_updates(
        result.updates,
        skip_note_ids=already_applied_note_ids,
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
            showInfo(format_failure_report(result.failures), parent=browser)
