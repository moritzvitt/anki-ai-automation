from __future__ import annotations

from aqt import mw
from aqt.qt import QAction
from aqt.utils import showInfo

from .usage_stats import build_usage_report, load_usage_stats


def register_usage_menu() -> None:
    if mw is None:
        return

    action = QAction("AI Automation Usage", mw)
    action.triggered.connect(_show_usage_report)
    mw.form.menuTools.addAction(action)


def _show_usage_report() -> None:
    if mw is None:
        return

    showInfo(build_usage_report(load_usage_stats()), parent=mw)
