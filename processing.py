from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aqt import mw
from aqt.browser import Browser
from aqt.operations import QueryOp
from aqt.utils import askUser, showCritical, showInfo, tooltip

from .config import AddonConfig, FieldMapping
from .openai_client import OpenAIClientError, request_field_updates
from .prompting import render_prompt


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


@dataclass(frozen=True)
class NoteFailure:
    note_id: int
    note_type_name: str
    reason: str


@dataclass(frozen=True)
class ProcessingResult:
    updates: list[NoteUpdate]
    failures: list[NoteFailure]


def run_ai_processing(browser: Browser, config: AddonConfig, note_ids: list[int]) -> None:
    if mw is None or mw.col is None:
        showCritical("Anki collection is not available.", parent=browser)
        return

    snapshots, failures = _build_snapshots(note_ids, config)
    if failures and not snapshots:
        showCritical(_format_failure_report(failures), parent=browser)
        return

    overwrite_count, overwrite_fields = _count_overwrites(snapshots)
    if overwrite_count:
        field_names = ", ".join(sorted(overwrite_fields))
        confirmed = askUser(
            (
                f"{overwrite_count} selected note(s) already contain data in output field(s): {field_names}.\n\n"
                "Processing may overwrite existing content. Continue?"
            ),
            parent=browser,
        )
        if not confirmed:
            return

    op = QueryOp(
        parent=browser,
        op=lambda _col: _process_snapshots(config, snapshots, failures),
        success=lambda result: _apply_result(browser, result),
    )
    op.with_progress(label=f"Processing {len(snapshots)} note(s) with AI...")
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

    for batch in _chunked(snapshots, config.batch_size):
        for snapshot in batch:
            try:
                prompt_template = snapshot.mapping.prompt_template or config.default_prompt_template
                system_prompt = snapshot.mapping.system_prompt or config.system_prompt
                prompt_values = {
                    field_name: snapshot.fields[field_name]
                    for field_name in snapshot.mapping.input_fields
                }
                prompt_values["NoteType"] = snapshot.note_type_name
                prompt = render_prompt(prompt_template, prompt_values)

                output_fields = request_field_updates(
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
                updates.append(NoteUpdate(note_id=snapshot.note_id, output_fields=output_fields))
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


def _apply_result(browser: Browser, result: ProcessingResult) -> None:
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

    browser.search()
    mw.reset()

    if applied:
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
