from __future__ import annotations

from typing import Any

from aqt import gui_hooks, mw
from aqt.browser import Browser
from aqt.operations import QueryOp
from aqt.qt import QAction, QMenu
from aqt.utils import showCritical, showInfo

from ..core.audit_flow import apply_audit_run_result
from ..core.config import ConfigError, load_config
from ..core.workflow_engine import execute_workflow_by_id
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
    try:
        config = load_config()
    except ConfigError as error:
        showCritical(str(error), parent=browser)
        return

    workflow = next((item for item in config.workflows if item.workflow_id == "mlr-audit"), None)
    if workflow is None:
        showCritical("The workflow 'mlr-audit' is not configured.", parent=browser)
        return

    op = QueryOp(
        parent=browser,
        op=lambda _col: execute_workflow_by_id(config, "mlr-audit", note_ids=note_ids, show_feedback=False),
        success=lambda result: _on_audit_workflow_finished(browser, workflow, config, result),
    )
    op.with_progress(label=f"Running workflow: {workflow.name}")
    op.run_in_background()


def _on_audit_workflow_finished(browser: Browser, workflow, config, result) -> None:
    for deferred in result.deferred_audit_applications:
        apply_audit_run_result(
            deferred.result,
            workflow=workflow,
            config=config,
            browser=browser,
            show_feedback=False,
        )
    skipped_count = len(getattr(result.deferred_audit_applications[0].result, "skipped_before_run", [])) if result.deferred_audit_applications else 0
    show_tooltip(
        f"{result.workflow_name}: {result.updated_requests} audited, {len(result.failures)} failed, {skipped_count} skipped.",
        parent=browser,
    )

    report_lines: list[str] = []
    if result.updated_requests == 0 and skipped_count:
        report_lines.append("No selected notes were audited.")
    if result.deferred_audit_applications:
        skipped_before_run = result.deferred_audit_applications[0].result.skipped_before_run
        if skipped_before_run:
            if report_lines:
                report_lines.append("")
            report_lines.append("Skipped before audit:")
            report_lines.extend(f"- {line}" for line in skipped_before_run[:20])
    if result.failures:
        if report_lines:
            report_lines.append("")
        report_lines.append("Audit workflow failures:")
        report_lines.extend(result.failures[:20])
    if report_lines:
        showInfo("\n".join(report_lines), parent=browser)


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
