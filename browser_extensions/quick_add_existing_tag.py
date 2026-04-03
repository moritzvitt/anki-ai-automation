from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aqt import gui_hooks, mw
from aqt.browser import Browser
from aqt.operations import QueryOp
from aqt.qt import QAction, QInputDialog, QMenu

from ..ui.tooltips import show_tooltip


@dataclass(frozen=True)
class QuickTagResult:
    tag: str
    tagged_note_ids: list[int]
    skipped_note_ids: list[int]


def register_browser_quick_add_existing_tag() -> None:
    if mw is None:
        return
    gui_hooks.browser_will_show_context_menu.append(_on_browser_context_menu)


def _on_browser_context_menu(browser: Browser, menu: QMenu) -> None:
    note_ids = _selected_note_ids(browser)
    if not note_ids:
        return

    action = QAction("Quick Add Existing Tag...", browser)
    action.triggered.connect(lambda: _prompt_and_apply_tag(browser, note_ids))
    menu.addAction(action)


def _prompt_and_apply_tag(browser: Browser, note_ids: list[int]) -> None:
    if mw is None or mw.col is None:
        show_tooltip("Anki collection is not available.", parent=browser)
        return

    existing_tags = _existing_tags()
    if not existing_tags:
        show_tooltip("No existing tags were found in this collection.", parent=browser)
        return

    selected_tag, accepted = QInputDialog.getItem(
        browser,
        "Quick Add Existing Tag",
        "Choose an existing tag",
        existing_tags,
        0,
        True,
    )
    if not accepted:
        return

    normalized_tag = selected_tag.strip()
    if not normalized_tag:
        show_tooltip("Choose an existing tag.", parent=browser)
        return
    if normalized_tag not in set(existing_tags):
        show_tooltip("Only existing tags can be added from this menu.", parent=browser)
        return

    op = QueryOp(
        parent=browser,
        op=lambda _col: _apply_existing_tag(note_ids, normalized_tag),
        success=lambda result: _on_tagging_finished(browser, result),
    )
    op.with_progress(label=f"Adding tag '{normalized_tag}'...")
    op.run_in_background()


def _apply_existing_tag(note_ids: list[int], tag: str) -> QuickTagResult:
    if mw is None or mw.col is None:
        return QuickTagResult(tag=tag, tagged_note_ids=[], skipped_note_ids=list(note_ids))

    tagged_note_ids: list[int] = []
    skipped_note_ids: list[int] = []
    for note_id in note_ids:
        note = mw.col.get_note(int(note_id))
        if note is None:
            skipped_note_ids.append(int(note_id))
            continue
        if note.has_tag(tag):
            skipped_note_ids.append(int(note_id))
            continue
        note.add_tag(tag)
        mw.col.update_note(note)
        tagged_note_ids.append(int(note_id))
    return QuickTagResult(tag=tag, tagged_note_ids=tagged_note_ids, skipped_note_ids=skipped_note_ids)


def _on_tagging_finished(browser: Browser, result: QuickTagResult) -> None:
    _refresh_open_browser_note(browser, changed_note_ids=result.tagged_note_ids)
    if mw is not None:
        mw.reset()
    show_tooltip(
        f"Tag '{result.tag}': added to {len(result.tagged_note_ids)} note(s), skipped {len(result.skipped_note_ids)}.",
        parent=browser,
    )


def _existing_tags() -> list[str]:
    if mw is None or mw.col is None:
        return []

    tag_manager = getattr(mw.col, "tags", None)
    raw_tags: list[str] = []
    if tag_manager is not None and hasattr(tag_manager, "all"):
        try:
            raw_tags = list(tag_manager.all())
        except Exception:
            raw_tags = []
    elif tag_manager is not None and hasattr(tag_manager, "all_names"):
        try:
            raw_tags = list(tag_manager.all_names())
        except Exception:
            raw_tags = []
    normalized = sorted({str(tag).strip() for tag in raw_tags if str(tag).strip()}, key=str.lower)
    return normalized


def _selected_note_ids(browser: Browser) -> list[int]:
    note_candidates: list[Any] = []

    if hasattr(browser, "selected_notes"):
        note_candidates = list(browser.selected_notes())
    elif hasattr(browser, "selectedNotes"):
        note_candidates = list(browser.selectedNotes())

    ordered_note_ids: list[int] = []
    seen_note_ids: set[int] = set()
    for note_id in note_candidates:
        try:
            parsed_note_id = int(note_id)
        except (TypeError, ValueError):
            continue
        if parsed_note_id not in seen_note_ids:
            ordered_note_ids.append(parsed_note_id)
            seen_note_ids.add(parsed_note_id)

    card_candidates: list[Any] = []
    if hasattr(browser, "selected_cards"):
        card_candidates = list(browser.selected_cards())
    elif hasattr(browser, "selectedCards"):
        card_candidates = list(browser.selectedCards())

    if mw is not None and mw.col is not None:
        for card_id in card_candidates:
            try:
                card = mw.col.get_card(int(card_id))
            except (TypeError, ValueError):
                continue
            if card is not None:
                note_id = int(card.nid)
                if note_id not in seen_note_ids:
                    ordered_note_ids.append(note_id)
                    seen_note_ids.add(note_id)

    return ordered_note_ids


def _refresh_open_browser_note(browser: Browser, *, changed_note_ids: list[int]) -> None:
    if not changed_note_ids:
        return
    editor = getattr(browser, "editor", None)
    note = getattr(editor, "note", None)
    if editor is None or note is None:
        return
    try:
        current_note_id = int(getattr(note, "id", 0) or 0)
    except Exception:
        return
    if current_note_id not in set(changed_note_ids):
        return
    try:
        note.load()
        if hasattr(editor, "loadNoteKeepingFocus"):
            editor.loadNoteKeepingFocus()
        else:
            editor.set_note(note, hide=False)
    except Exception:
        return
