from __future__ import annotations

from aqt import gui_hooks, mw
from aqt.qt import QTimer

from .config import ConfigError, Workflow, load_config
from ..ui.workflow import run_workflows_background


_TRIGGER_TIMER: QTimer | None = None
_TRIGGER_CONDITION_STATE: dict[str, bool] = {}
_TRIGGER_RUN_IN_PROGRESS = False
_PERIODIC_CHECK_INTERVAL_MS = 60_000


def register_workflow_triggers() -> None:
    if mw is None:
        return
    if hasattr(gui_hooks, "profile_did_open"):
        gui_hooks.profile_did_open.append(_on_profile_did_open)


def _on_profile_did_open() -> None:
    _ensure_trigger_timer()
    _check_triggered_workflows(reason="startup")


def _ensure_trigger_timer() -> None:
    global _TRIGGER_TIMER
    if mw is None:
        return
    if _TRIGGER_TIMER is None:
        _TRIGGER_TIMER = QTimer(mw)
        _TRIGGER_TIMER.setInterval(_PERIODIC_CHECK_INTERVAL_MS)
        _TRIGGER_TIMER.timeout.connect(lambda: _check_triggered_workflows(reason="periodic"))
    if not _TRIGGER_TIMER.isActive():
        _TRIGGER_TIMER.start()


def _check_triggered_workflows(*, reason: str) -> None:
    global _TRIGGER_RUN_IN_PROGRESS
    if _TRIGGER_RUN_IN_PROGRESS or mw is None or mw.col is None:
        return

    try:
        config = load_config()
    except ConfigError:
        return

    triggered_workflows: list[Workflow] = []
    next_condition_state = dict(_TRIGGER_CONDITION_STATE)

    for workflow in sorted(config.workflows, key=lambda item: item.position):
        monitor_enabled = workflow.trigger_on_startup or workflow.trigger_on_periodic
        if not monitor_enabled:
            continue

        try:
            match_count = len(mw.col.find_notes(workflow.query))
        except Exception:
            continue

        condition_met = match_count >= max(1, workflow.trigger_min_matches)
        previous_condition_met = _TRIGGER_CONDITION_STATE.get(workflow.workflow_id, False)
        next_condition_state[workflow.workflow_id] = condition_met

        if reason == "startup" and workflow.trigger_on_startup and condition_met:
            triggered_workflows.append(workflow)
            continue

        if reason == "periodic" and workflow.trigger_on_periodic and condition_met and not previous_condition_met:
            triggered_workflows.append(workflow)

    _TRIGGER_CONDITION_STATE.clear()
    _TRIGGER_CONDITION_STATE.update(next_condition_state)

    if not triggered_workflows:
        return

    _TRIGGER_RUN_IN_PROGRESS = True
    run_label = "Automatic workflow trigger" if len(triggered_workflows) == 1 else "Automatic workflow triggers"
    run_workflows_background(
        mw,
        triggered_workflows,
        run_label=run_label,
        show_summary_dialog=False,
        on_done=lambda _summary: _mark_trigger_run_finished(),
    )


def _mark_trigger_run_finished() -> None:
    global _TRIGGER_RUN_IN_PROGRESS
    _TRIGGER_RUN_IN_PROGRESS = False
