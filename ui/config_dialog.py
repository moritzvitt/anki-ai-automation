from __future__ import annotations

from typing import Any

import aqt
from aqt import mw
from aqt.addons import ConfigEditor
from aqt.operations import QueryOp
from aqt.qt import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from aqt.utils import showCritical, showInfo

from ..core.config import ADDON_NAME, ConfigError, load_config
from ..services.model_catalog import ModelOption, fallback_model_options, fetch_model_options
from .automation import open_browser_settings_dialog
from .tooltips import set_hover_help
from .workflow import WorkflowManagerDialog
from .. import shared_styling


def register_config_action() -> None:
    if mw is None:
        return

    addon_manager = mw.addonManager
    if hasattr(addon_manager, "setConfigAction"):
        addon_manager.setConfigAction(ADDON_NAME, _open_config_dialog)


def _open_config_dialog() -> None:
    if mw is None:
        return

    dialog = ConfigDialog(parent=mw)
    dialog.exec()


class ConfigDialog(QDialog):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI Automation Settings")
        self.resize(920, 640)

        self._addon_manager = mw.addonManager if mw is not None else None
        self._config = self._load_config()

        self.enabled_checkbox = QCheckBox("Enable AI Automation")
        self.show_tooltips_checkbox = QCheckBox("Show tooltips and hover help")
        self.use_chat_completions_checkbox = QCheckBox("Use Chat Completions API")
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(320)
        self.model_status_label = QLabel()
        self.refresh_models_button = QPushButton("Refresh Models")
        self.open_workflows_button = QPushButton("Open Workflow Settings")
        self.open_browser_settings_button = QPushButton("Open Browser Settings")
        self.open_live_config_button = QPushButton("Open Live Config")
        self.editor_default_group_combo = QComboBox()
        self._workflow_groups = self._load_workflow_groups()

        self._build_ui()
        self._populate_fields()
        self._refresh_model_options()
        shared_styling.apply_dialog_theme(self)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        header = QLabel(
            "<div style='line-height:1.15;'>"
            "<div style='font-size:16px; font-weight:600; margin:0; padding:0;'>AI Automation Settings</div>"
            "<div style='margin-top:2px;'>Use OpenAI to update Anki notes from Browser selections or reusable workflows. "
            "Manage the core settings here, then open the Browser or workflow dialogs for the detailed AI setup.</div>"
            "</div>"
        )
        header.setWordWrap(True)
        header.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(header)
        layout.addWidget(self._build_main_settings_group())
        layout.addWidget(self._build_navigation_group())
        layout.addWidget(
            shared_styling.build_global_preferences_group(
                self,
                addon_name="AI Automation",
                intro="Global Styling controls the shared theme and gamification level used by supported Moritz add-ons. AI Automation keeps its own local settings if the global add-on is missing or turned off.",
            )
        )

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_main_settings_group(self) -> QGroupBox:
        group = QGroupBox("Core Settings")
        form = QFormLayout(group)

        self.api_key_edit.setPlaceholderText("sk-...")
        self.model_status_label.setWordWrap(True)
        self.refresh_models_button.clicked.connect(self._refresh_model_options)
        help_enabled = bool(self._config.get("show_tooltips", True))
        set_hover_help(self.enabled_checkbox, "Turn the add-on on or off for this Anki profile.", enabled=help_enabled)
        set_hover_help(
            self.show_tooltips_checkbox,
            "Enable or disable hover help and small popup tooltip messages throughout the add-on.",
            enabled=help_enabled,
        )
        set_hover_help(
            self.use_chat_completions_checkbox,
            "Use the Chat Completions API instead of the Responses API for generation. Leave this on unless you are comparing APIs or debugging a model-specific issue.",
            enabled=help_enabled,
        )
        set_hover_help(self.api_key_edit, "OpenAI API key used for live model loading and AI requests.", enabled=help_enabled)
        set_hover_help(self.model_combo, "Default model used unless a Browser run or workflow overrides it.", enabled=help_enabled)
        set_hover_help(self.refresh_models_button, "Fetch the current curated model shortlist from OpenAI for the model dropdown.", enabled=help_enabled)

        model_row = QWidget()
        model_layout = QVBoxLayout(model_row)
        model_layout.setContentsMargins(0, 0, 0, 0)
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.addWidget(self.model_combo, stretch=1)
        top_row.addWidget(self.refresh_models_button)
        model_layout.addLayout(top_row)
        model_layout.addWidget(self.model_status_label)

        form.addRow(self.enabled_checkbox)
        form.addRow(self.show_tooltips_checkbox)
        form.addRow(self.use_chat_completions_checkbox)
        form.addRow("API key", self.api_key_edit)
        form.addRow("Default model", model_row)
        return group

    def _build_navigation_group(self) -> QGroupBox:
        group = QGroupBox("General Settings")
        layout = QVBoxLayout(group)

        help_text = QLabel(
            "Choose the default workflow group for the editor toolbar, open the reusable workflow and Browser settings dialogs, or inspect the live stored config."
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

        self.editor_default_group_combo.setMinimumWidth(280)
        set_hover_help(
            self.editor_default_group_combo,
            "Choose which workflow group is preselected in the editor toolbar's Create dropdown.",
            enabled=bool(self._config.get("show_tooltips", True)),
        )
        group_row = QHBoxLayout()
        group_row.addWidget(QLabel("Default editor workflow group"))
        group_row.addWidget(self.editor_default_group_combo, stretch=1)
        layout.addLayout(group_row)

        buttons_row = QHBoxLayout()
        self.open_workflows_button.clicked.connect(self._open_workflow_settings)
        self.open_browser_settings_button.clicked.connect(self._open_browser_settings)
        self.open_live_config_button.clicked.connect(self._open_live_config)
        set_hover_help(
            self.open_workflows_button,
            "Open the workflow manager to create, edit, group, and run reusable field-update or script workflows.",
            enabled=bool(self._config.get("show_tooltips", True)),
        )
        set_hover_help(
            self.open_browser_settings_button,
            "Open the Browser AI settings dialog for saved prompts, presets, write modes, and Browser defaults.",
            enabled=bool(self._config.get("show_tooltips", True)),
        )
        set_hover_help(
            self.open_live_config_button,
            "Open Anki's built-in raw JSON config editor for this add-on.",
            enabled=bool(self._config.get("show_tooltips", True)),
        )
        buttons_row.addWidget(self.open_workflows_button)
        buttons_row.addWidget(self.open_browser_settings_button)
        buttons_row.addWidget(self.open_live_config_button)
        layout.addLayout(buttons_row)
        return group

    def _populate_fields(self) -> None:
        self.enabled_checkbox.setChecked(bool(self._config.get("enabled", True)))
        self.show_tooltips_checkbox.setChecked(bool(self._config.get("show_tooltips", True)))
        self.use_chat_completions_checkbox.setChecked(bool(self._config.get("use_chat_completions_api", True)))
        self.api_key_edit.setText(str(self._config.get("openai_api_key", "")))

        self._set_model_options(
            fallback_model_options(
                current_model=str(self._config.get("model", "")),
                pricing_overrides=self._config.get("model_pricing", {}),
            ),
            current_model=str(self._config.get("model", "")),
        )
        self.model_status_label.setText(
            "Showing a curated flashcard-writing model list. Click Refresh Models to load the current shortlist from OpenAI."
        )
        self.editor_default_group_combo.clear()
        self.editor_default_group_combo.addItem("No default group", "")
        for group in self._workflow_groups:
            self.editor_default_group_combo.addItem(group["name"], group["group_id"])
        current_group_id = str(self._config.get("editor_default_workflow_group_id") or "")
        current_index = self.editor_default_group_combo.findData(current_group_id)
        self.editor_default_group_combo.setCurrentIndex(current_index if current_index >= 0 else 0)

    def _save(self) -> None:
        self._config.update(
            {
                "enabled": self.enabled_checkbox.isChecked(),
                "show_tooltips": self.show_tooltips_checkbox.isChecked(),
                "use_chat_completions_api": self.use_chat_completions_checkbox.isChecked(),
                "openai_api_key": self.api_key_edit.text().strip(),
                "model": self.model_combo.currentData() or self.model_combo.currentText().strip(),
                "editor_default_workflow_group_id": self.editor_default_group_combo.currentData() or None,
                "show_estimate_before_sending": False,
                "field_mappings": list(self._config.get("field_mappings", [])),
            }
        )

        self._addon_manager.writeConfig(ADDON_NAME, self._config)
        showInfo("AI Automation settings saved.", parent=self)
        self.accept()

    def _open_workflow_settings(self) -> None:
        dialog = WorkflowManagerDialog(parent=self)
        dialog.exec()
        self._workflow_groups = self._load_workflow_groups()
        self._populate_fields()

    def _open_browser_settings(self) -> None:
        open_browser_settings_dialog(self)

    def _open_live_config(self) -> None:
        self._open_builtin_config_editor()

    def _open_builtin_config_editor(self) -> None:
        if self._addon_manager is None:
            showCritical("Could not open the built-in config editor.", parent=self)
            return

        addon_id = self._addon_manager.addonFromModule(__name__)
        try:
            config = self._addon_manager.getConfig(ADDON_NAME)
            addons_dialog = aqt.dialogs.open("AddonsDialog", mw)
            addons_dialog.activateWindow()
            addons_dialog.raise_()
            self._raw_config_editor = ConfigEditor(  # type: ignore[attr-defined]
                addons_dialog,
                addon_id,
                config if isinstance(config, dict) else {},
            )
        except Exception as error:
            showCritical(f"Could not open the built-in config editor: {error}", parent=self)

    def _refresh_model_options(self) -> None:
        self.refresh_models_button.setEnabled(False)
        self.model_status_label.setText("Loading live model list from OpenAI...")
        pricing_overrides = self._config.get("model_pricing", {})
        api_key = self.api_key_edit.text().strip()
        current_model = str(self._config.get("model", ""))

        op = QueryOp(
            parent=self,
            op=lambda _col: self._load_model_options(api_key, pricing_overrides, current_model),
            success=self._apply_model_options_result,
        )
        op.with_progress(label="Loading OpenAI models...")
        op.run_in_background()

    def _load_config(self) -> dict[str, Any]:
        if self._addon_manager is None:
            return {}

        config = self._addon_manager.getConfig(ADDON_NAME)
        if not isinstance(config, dict):
            return {}
        return dict(config)

    def _load_workflow_groups(self) -> list[dict[str, str]]:
        try:
            parsed_config = load_config()
        except ConfigError:
            return []
        return [
            {"group_id": group.group_id, "name": group.name}
            for group in sorted(parsed_config.workflow_groups, key=lambda item: item.name.lower())
        ]

    def _load_model_options(
        self,
        api_key: str,
        pricing_overrides: dict[str, Any],
        current_model: str,
    ) -> dict[str, Any]:
        try:
            options = fetch_model_options(api_key=api_key, pricing_overrides=pricing_overrides)
            return {"options": options, "message": "Loaded current models from OpenAI."}
        except Exception as error:
            return {
                "options": fallback_model_options(
                    current_model=current_model,
                    pricing_overrides=pricing_overrides,
                ),
                "message": f"Using fallback model list: {error}",
            }

    def _apply_model_options_result(self, result: dict[str, Any]) -> None:
        options = result.get("options", [])
        current_model = self.model_combo.currentData() or str(self._config.get("model", ""))
        if isinstance(options, list):
            self._set_model_options(options, current_model=current_model)
        message = result.get("message")
        if isinstance(message, str):
            self.model_status_label.setText(message)
        self.refresh_models_button.setEnabled(True)

    def _set_model_options(self, options: list[ModelOption], *, current_model: str) -> None:
        self.model_combo.clear()
        for option in options:
            self.model_combo.addItem(option.label, option.model_id)

        current_index = self.model_combo.findData(current_model)
        if current_index >= 0:
            self.model_combo.setCurrentIndex(current_index)
            return

        if current_model:
            self.model_combo.insertItem(0, current_model + " (Current selection)", current_model)
            self.model_combo.setCurrentIndex(0)
