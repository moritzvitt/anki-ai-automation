from __future__ import annotations

from typing import Callable

from aqt import gui_hooks, mw
from aqt.browser import Browser
from aqt.qt import QAction, QMenu, QWidget

from .. import shared_menu
from .automation import open_browser_settings_dialog
from .browser_menu import (
    _populate_workflows_menu,
    _selected_note_ids,
    _trigger_processing,
)
from .config_dialog import _open_config_dialog
from .tooltips import set_action_hover_help
from .usage_menu import _show_usage_report
from .workflow import _open_workflow_manager


MAIN_MENU_TITLE = "AI-Automation"


def register_top_level_menus() -> None:
    if mw is not None:
        _ensure_main_window_menu()
    gui_hooks.browser_menus_did_init.append(_ensure_browser_menu)


def _ensure_main_window_menu() -> None:
    if mw is None:
        return
    menu = shared_menu.get_addon_submenu(MAIN_MENU_TITLE)
    menu.clear()

    _add_action(
        menu,
        "Workflow Configuration",
        "Open the workflow manager for reusable field-update and script workflows.",
        _open_workflow_manager,
        mw,
    )
    _add_action(
        menu,
        "Browser Settings",
        "Open the Browser AI settings dialog for prompts, presets, and Browser defaults.",
        lambda: open_browser_settings_dialog(mw),
        mw,
    )
    _add_action(
        menu,
        "Usage",
        "Show local usage totals and, when available, official OpenAI organization cost data.",
        _show_usage_report,
        mw,
    )
    menu.addSeparator()
    _add_action(
        menu,
        "Settings",
        "Open the main AI Automation settings dialog.",
        _open_config_dialog,
        mw,
    )


def _ensure_browser_menu(browser: Browser) -> None:
    menu_bar = browser.menuBar() if hasattr(browser, "menuBar") else None
    if menu_bar is None:
        return
    existing = _find_menu(menu_bar, MAIN_MENU_TITLE)
    if existing is not None:
        existing.clear()
        menu = existing
    else:
        menu = QMenu(MAIN_MENU_TITLE, browser)
        _insert_before_help(menu_bar, menu)

    _add_action(
        menu,
        "Transform with AI",
        "Open the Browser AI dialog for the current selection and run a one-off prompt or preset.",
        lambda: _trigger_processing(browser),
        browser,
    )
    workflows_menu = menu.addMenu("Run Workflow with AI")
    note_ids = _selected_note_ids(browser)
    if note_ids:
        _populate_workflows_menu(browser, workflows_menu, note_ids)
    else:
        empty_action = QAction("No Browser selection", browser)
        empty_action.setEnabled(False)
        set_action_hover_help(empty_action, "Select at least one Browser card or note to run workflows from this menu.")
        workflows_menu.addAction(empty_action)

    menu.addSeparator()
    _add_action(
        menu,
        "Browser Settings",
        "Open the Browser AI settings dialog for prompts, presets, and Browser defaults.",
        lambda: open_browser_settings_dialog(browser),
        browser,
    )
    _add_action(
        menu,
        "Workflow Configuration",
        "Open the workflow manager for reusable field-update and script workflows.",
        _open_workflow_manager,
        browser,
    )


def _add_action(menu: QMenu, label: str, tooltip: str, callback: Callable[[], None], parent: QWidget) -> QAction:
    action = QAction(label, parent)
    set_action_hover_help(action, tooltip)
    action.triggered.connect(callback)
    menu.addAction(action)
    return action


def _find_menu(menu_bar, title: str) -> QMenu | None:
    for action in menu_bar.actions():
        menu = action.menu()
        if menu is not None and menu.title() == title:
            return menu
    return None


def _insert_before_help(menu_bar, menu: QMenu) -> None:
    help_action = None
    for action in menu_bar.actions():
        current_menu = action.menu()
        title = current_menu.title() if current_menu is not None else action.text()
        if title.replace("&", "") == "Help":
            help_action = action
            break
    if help_action is not None:
        menu_bar.insertMenu(help_action, menu)
        return
    menu_bar.addMenu(menu)
