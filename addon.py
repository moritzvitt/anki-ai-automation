from __future__ import annotations

from .browser_menu import register_browser_menu
from .config_ui import register_config_action
from .usage_menu import register_usage_menu


def register() -> None:
    register_config_action()
    register_browser_menu()
    register_usage_menu()
