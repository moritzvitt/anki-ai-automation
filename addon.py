from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from .core.workflow_triggers import register_workflow_triggers
from .ui.browser_menu import register_browser_menu
from .ui.config_dialog import register_config_action
from .ui.tag_migration import register_tag_migration_menu
from .ui.usage_menu import register_usage_menu
from .ui.workflow import register_workflow_menu


def _register_external_browser_extensions() -> None:
    root = Path(__file__).resolve().parent.parent
    module_path = root / "browser_extensions" / "quick_add_existing_tag.py"
    if not module_path.exists():
        return

    spec = importlib.util.spec_from_file_location(
        "external_browser_extensions.quick_add_existing_tag",
        module_path,
    )
    if spec is None or spec.loader is None:
        return

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    register = getattr(module, "register_browser_quick_add_existing_tag", None)
    if callable(register):
        register()


def register() -> None:
    register_config_action()
    register_browser_menu()
    _register_external_browser_extensions()
    register_tag_migration_menu()
    register_usage_menu()
    register_workflow_menu()
    register_workflow_triggers()
