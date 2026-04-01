from __future__ import annotations

from aqt import mw
from aqt.qt import QAction
from aqt.utils import showInfo


def _show_starter_message() -> None:
    showInfo("Your Anki add-on starter is loaded. Replace this action with real behavior.")


def register() -> None:
    """Register a small sample action so the template is visibly active."""
    if mw is None:
        return

    action = QAction("Starter Repo Action", mw)
    action.triggered.connect(_show_starter_message)
    mw.form.menuTools.addAction(action)
