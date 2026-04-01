from __future__ import annotations

from typing import Any

from aqt import gui_hooks, mw
from aqt.browser import Browser
from aqt.qt import QAction, QMenu
from aqt.utils import showCritical, tooltip

from .config import ConfigError, load_config
from .processing import run_ai_processing


def register_browser_menu() -> None:
    if mw is None:
        return

    gui_hooks.browser_will_show_context_menu.append(_on_browser_context_menu)


def _on_browser_context_menu(browser: Browser, menu: QMenu) -> None:
    note_ids = _selected_note_ids(browser)
    if not note_ids:
        return

    action = QAction("Process with AI", browser)
    action.triggered.connect(lambda: _trigger_processing(browser))
    menu.addSeparator()
    menu.addAction(action)


def _trigger_processing(browser: Browser) -> None:
    try:
        config = load_config()
    except ConfigError as error:
        showCritical(str(error), parent=browser)
        return

    if not config.enabled:
        tooltip("AI Automation is disabled in the add-on config.", parent=browser)
        return

    note_ids = _selected_note_ids(browser)
    if not note_ids:
        tooltip("Select at least one note in the Browser.", parent=browser)
        return

    run_ai_processing(browser, config, note_ids)


def _selected_note_ids(browser: Browser) -> list[int]:
    candidates: list[Any] = []

    if hasattr(browser, "selected_notes"):
        candidates = list(browser.selected_notes())
    elif hasattr(browser, "selectedNotes"):
        candidates = list(browser.selectedNotes())

    note_ids: list[int] = []
    for note_id in candidates:
        try:
            note_ids.append(int(note_id))
        except (TypeError, ValueError):
            continue

    return note_ids
