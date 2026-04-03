from __future__ import annotations

from typing import Any

from aqt import gui_hooks, mw
from aqt.browser import Browser
from aqt.qt import QAction, QMenu

from ..core.audit_flow import run_browser_ai_audit
from .automation import open_transform_dialog
from .tooltips import show_tooltip


def register_browser_menu() -> None:
    if mw is None:
        return

    gui_hooks.browser_will_show_context_menu.append(_on_browser_context_menu)


def _on_browser_context_menu(browser: Browser, menu: QMenu) -> None:
    note_ids = _selected_note_ids(browser)
    if not note_ids:
        return

    action = QAction("Transform with AI", browser)
    action.triggered.connect(lambda: _trigger_processing(browser))
    audit_action = QAction("Audit with AI", browser)
    audit_action.triggered.connect(lambda: _trigger_audit(browser))
    menu.addSeparator()
    menu.addAction(action)
    menu.addAction(audit_action)


def _trigger_processing(browser: Browser) -> None:
    note_ids = _selected_note_ids(browser)
    if not note_ids:
        show_tooltip("Select at least one card or note in the Browser.", parent=browser)
        return

    open_transform_dialog(browser, note_ids)


def _trigger_audit(browser: Browser) -> None:
    note_ids = _selected_note_ids(browser)
    if not note_ids:
        show_tooltip("Select at least one card or note in the Browser.", parent=browser)
        return

    run_browser_ai_audit(browser, note_ids)


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
