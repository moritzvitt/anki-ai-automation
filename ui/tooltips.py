from __future__ import annotations

from aqt import mw
from aqt.qt import QWidget
from aqt.utils import tooltip as anki_tooltip

from ..core.config import ADDON_NAME


def hover_help_enabled() -> bool:
    if mw is None:
        return True
    addon_manager = getattr(mw, "addonManager", None)
    if addon_manager is None:
        return True
    config = addon_manager.getConfig(ADDON_NAME)
    if not isinstance(config, dict):
        return True
    return bool(config.get("show_tooltips", True))


def set_hover_help(widget: QWidget, text: str, *, enabled: bool | None = None) -> QWidget:
    if enabled is None:
        enabled = hover_help_enabled()
    widget.setToolTip(text if enabled else "")
    return widget


def show_tooltip(text: str, *, parent: QWidget | None = None, period: int = 3000) -> None:
    if not hover_help_enabled():
        return
    anki_tooltip(text, parent=parent, period=period)
