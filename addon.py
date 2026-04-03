from __future__ import annotations

from .core.workflow_triggers import register_workflow_triggers
from .ui.audit_sync import register_audit_sync_menu
from .ui.browser_menu import register_browser_menu
from .ui.config_dialog import register_config_action
from .ui.pipelines import register_pipeline_menu
from .ui.tag_migration import register_tag_migration_menu
from .ui.usage_menu import register_usage_menu
from .ui.workflow import register_workflow_menu


def register() -> None:
    register_config_action()
    register_browser_menu()
    register_audit_sync_menu()
    register_tag_migration_menu()
    register_usage_menu()
    register_workflow_menu()
    register_pipeline_menu()
    register_workflow_triggers()
