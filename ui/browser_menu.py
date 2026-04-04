from __future__ import annotations

from threading import Event
from typing import Any

from aqt import gui_hooks, mw
from aqt.browser import Browser
from aqt.operations import QueryOp
from aqt.qt import QAction, QMenu
from aqt.utils import showCritical

from ..core.audit_flow import apply_audit_run_result
from ..core.config import ConfigError, load_config
from ..core.processing import ProcessingInterruptDialog
from ..core.workflow_engine import execute_workflow_by_id
from .automation import open_transform_dialog
from .tooltips import show_tooltip
from .workflow import run_workflows_background


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
    workflows_menu = menu.addMenu("Run Workflow with AI")
    _populate_workflows_menu(browser, workflows_menu, note_ids)
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

    cancel_event = Event()
    progress_dialog = ProcessingInterruptDialog(
        browser,
        note_count=len(note_ids),
        window_title="AI Audit Progress",
        action_label=f"Auditing",
    )
    progress_dialog.interrupt_button.clicked.connect(
        lambda: _request_progress_interrupt(progress_dialog, cancel_event)
    )
    progress_dialog.show()

    def report_progress(completed_count: int) -> None:
        if mw is None or not hasattr(mw, "taskman"):
            return
        mw.taskman.run_on_main(
            lambda: progress_dialog.set_progress(min(completed_count, len(note_ids)))
        )

    def run_audit_operation():
        try:
            return execute_workflow_by_id(
                config,
                "mlr-audit",
                note_ids=note_ids,
                show_feedback=False,
                skip_already_processed_today=False,
                cancel_event=cancel_event,
                progress_callback=report_progress,
            )
        finally:
            if mw is not None and hasattr(mw, "taskman"):
                mw.taskman.run_on_main(progress_dialog.close)

    op = QueryOp(
        parent=browser,
        op=lambda _col: run_audit_operation(),
        success=lambda result: _on_audit_workflow_finished(browser, workflow, config, result),
    )
    op.with_progress(label=f"Running workflow: {workflow.name}")
    op.run_in_background()


def _populate_workflows_menu(browser: Browser, menu: QMenu, note_ids: list[int]) -> None:
    try:
        config = load_config()
    except ConfigError as error:
        error_action = QAction("Workflow configuration error", browser)
        error_action.setEnabled(False)
        error_action.setToolTip(str(error))
        menu.addAction(error_action)
        return

    enabled_workflows = [
        workflow
        for workflow in sorted(config.workflows, key=lambda item: item.position)
        if workflow.enabled
    ]
    enabled_groups = [
        group
        for group in sorted(config.workflow_groups, key=lambda item: item.name.lower())
        if any(group.group_id == workflow.group_id for workflow in enabled_workflows)
    ]
    if not enabled_workflows:
        empty_action = QAction("No enabled workflows", browser)
        empty_action.setEnabled(False)
        menu.addAction(empty_action)
        return

    if enabled_groups:
        groups_menu = menu.addMenu("Run Group")
        for group in enabled_groups:
            action = QAction(group.name, browser)
            action.triggered.connect(
                lambda _checked=False, selected_group_id=group.group_id: _trigger_browser_group(
                    browser,
                    selected_group_id,
                    note_ids,
                )
            )
            groups_menu.addAction(action)
        menu.addSeparator()

    for workflow in enabled_workflows:
        action = QAction(workflow.name, browser)
        action.triggered.connect(
            lambda _checked=False, selected_workflow=workflow: _trigger_browser_workflow(
                browser,
                selected_workflow.workflow_id,
                note_ids,
            )
        )
        menu.addAction(action)


def _trigger_browser_workflow(browser: Browser, workflow_id: str, note_ids: list[int]) -> None:
    if not note_ids:
        show_tooltip("Select at least one card or note in the Browser.", parent=browser)
        return
    try:
        config = load_config()
    except ConfigError as error:
        showCritical(str(error), parent=browser)
        return

    workflow = next((item for item in config.workflows if item.workflow_id == workflow_id), None)
    if workflow is None:
        showCritical(f"The workflow '{workflow_id}' is not configured.", parent=browser)
        return
    if not workflow.enabled:
        show_tooltip("Enable the workflow before running it.", parent=browser)
        return

    run_workflows_background(
        browser,
        [workflow],
        run_label=f"{workflow.name} (selected Browser notes)",
        note_ids_override=list(note_ids),
        show_summary_dialog=False,
        on_done=lambda _summary: _refresh_open_browser_note(browser, changed_note_ids=note_ids),
    )


def _trigger_browser_group(browser: Browser, group_id: str, note_ids: list[int]) -> None:
    if not note_ids:
        show_tooltip("Select at least one card or note in the Browser.", parent=browser)
        return
    try:
        config = load_config()
    except ConfigError as error:
        showCritical(str(error), parent=browser)
        return

    workflows = [
        workflow
        for workflow in sorted(config.workflows, key=lambda item: item.position)
        if workflow.enabled and group_id == workflow.group_id
    ]
    if not workflows:
        show_tooltip("This workflow group does not contain any enabled workflows.", parent=browser)
        return

    group_name = next(
        (group.name for group in config.workflow_groups if group.group_id == group_id),
        "Selected workflow group",
    )
    run_workflows_background(
        browser,
        workflows,
        run_label=f"{group_name} (selected Browser notes)",
        note_ids_override=list(note_ids),
        show_summary_dialog=False,
        on_done=lambda _summary: _refresh_open_browser_note(browser, changed_note_ids=note_ids),
    )


def _on_audit_workflow_finished(browser: Browser, workflow, config, result) -> None:
    apply_results = []
    try:
        for deferred in result.deferred_audit_applications:
            apply_results.append(
                apply_audit_run_result(
                    deferred.result,
                    workflow=workflow,
                    config=config,
                    browser=browser,
                    show_feedback=False,
                )
            )
    except Exception as error:
        showCritical(f"Applying audit results failed: {error}", parent=browser)
        return

    persisted_note_ids: list[int] = []
    for item in apply_results:
        persisted_note_ids.extend(item.persisted_success_note_ids)
        persisted_note_ids.extend(item.persisted_failure_note_ids)
    _refresh_open_browser_note(browser, changed_note_ids=persisted_note_ids)
    skipped_count = len(getattr(result.deferred_audit_applications[0].result, "skipped_before_run", [])) if result.deferred_audit_applications else 0
    show_tooltip(
        f"{result.workflow_name}: {result.updated_requests} audited, {len(result.failures)} failed, {skipped_count} skipped.",
        parent=browser,
    )


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


def _request_progress_interrupt(dialog: ProcessingInterruptDialog, cancel_event: Event) -> None:
    cancel_event.set()
    dialog.set_interrupt_requested()
