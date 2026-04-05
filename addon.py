from __future__ import annotations

from .browser_extensions.quick_add_existing_tag import register_browser_quick_add_existing_tag
from .core.workflow_triggers import register_workflow_triggers
from .ui.browser_menu import register_browser_menu
from .ui.config_dialog import register_config_action
from .ui.tag_migration import register_tag_migration_menu
from .ui.usage_menu import register_usage_menu
from .ui.workflow import register_workflow_menu


def register() -> None:
    register_config_action()
    register_browser_menu()
    register_browser_quick_add_existing_tag()
    register_tag_migration_menu()
    register_usage_menu()
    register_workflow_menu()
    register_workflow_triggers()
