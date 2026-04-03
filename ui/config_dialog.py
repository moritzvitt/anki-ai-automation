from __future__ import annotations

from typing import Any

from aqt import mw
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
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)
from aqt.utils import showCritical, showInfo

from ..core.config import ADDON_NAME
from ..services.model_catalog import ModelOption, fallback_model_options, fetch_model_options
from .automation import open_browser_settings_dialog
from .tooltips import set_hover_help
from .workflow import WorkflowManagerDialog


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
        self.resize(980, 760)

        self._addon_manager = mw.addonManager if mw is not None else None
        self._config = self._load_config()
        self._current_prompt = str(self._config.get("prompt_template", ""))

        self.enabled_checkbox = QCheckBox("Enable AI Automation")
        self.show_tooltips_checkbox = QCheckBox("Show tooltips and hover help")
        self.use_chat_completions_checkbox = QCheckBox("Use Chat Completions API")
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(320)
        self.model_status_label = QLabel()
        self.system_prompt_edit = QPlainTextEdit()
        self.prompt_edit = QPlainTextEdit()
        self.refresh_models_button = QPushButton("Refresh Models")
        self.open_workflows_button = QPushButton("Open Workflow Settings")
        self.open_browser_settings_button = QPushButton("Open Browser Settings")

        self._build_ui()
        self._populate_fields()
        self._refresh_model_options()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        intro = QLabel(
            "Manage the core AI Automation settings here. "
            "Workflow management and Browser AI settings are available through the buttons below."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addWidget(self._build_main_settings_group())
        layout.addWidget(self._build_navigation_group())

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_main_settings_group(self) -> QGroupBox:
        group = QGroupBox("Core Settings")
        form = QFormLayout(group)

        self.api_key_edit.setPlaceholderText("sk-...")
        self.system_prompt_edit.setPlaceholderText("System prompt sent with every request")
        self.prompt_edit.setPlaceholderText("Use placeholders like {{Front}}, {{Back}}, {{NoteType}}")
        self.prompt_edit.setMinimumHeight(180)
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
            "Use the Chat Completions API instead of the Responses API for text generation. Enabled by default for speed testing.",
            enabled=help_enabled,
        )
        set_hover_help(self.api_key_edit, "OpenAI API key used for live model loading and AI requests.", enabled=help_enabled)
        set_hover_help(self.model_combo, "Default model used unless a Browser run or workflow overrides it.", enabled=help_enabled)
        set_hover_help(self.refresh_models_button, "Fetch the latest recommended model shortlist from OpenAI.", enabled=help_enabled)
        set_hover_help(self.system_prompt_edit, "System instructions sent with every request unless overridden elsewhere.", enabled=help_enabled)
        set_hover_help(self.prompt_edit, "Default user prompt template. Use {{FieldName}} placeholders to pull note content.", enabled=help_enabled)

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
        form.addRow("Model", model_row)
        form.addRow("System prompt", self.system_prompt_edit)
        form.addRow("Prompt template", self.prompt_edit)
        return group

    def _build_navigation_group(self) -> QGroupBox:
        group = QGroupBox("Other Settings")
        layout = QVBoxLayout(group)

        help_text = QLabel(
            "Open the dedicated dialogs for reusable workflows and Browser AI run settings."
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

        buttons_row = QHBoxLayout()
        self.open_workflows_button.clicked.connect(self._open_workflow_settings)
        self.open_browser_settings_button.clicked.connect(self._open_browser_settings)
        set_hover_help(
            self.open_workflows_button,
            "Open the workflow manager to create, edit, group, and trigger reusable query-based runs.",
            enabled=bool(self._config.get("show_tooltips", True)),
        )
        set_hover_help(
            self.open_browser_settings_button,
            "Open the Browser AI settings dialog for saved prompts, presets, write modes, and Browser defaults.",
            enabled=bool(self._config.get("show_tooltips", True)),
        )
        buttons_row.addWidget(self.open_workflows_button)
        buttons_row.addWidget(self.open_browser_settings_button)
        layout.addLayout(buttons_row)
        return group

    def _populate_fields(self) -> None:
        self.enabled_checkbox.setChecked(bool(self._config.get("enabled", True)))
        self.show_tooltips_checkbox.setChecked(bool(self._config.get("show_tooltips", True)))
        self.use_chat_completions_checkbox.setChecked(bool(self._config.get("use_chat_completions_api", True)))
        self.api_key_edit.setText(str(self._config.get("openai_api_key", "")))
        self.system_prompt_edit.setPlainText(str(self._config.get("system_prompt", "")))
        self.prompt_edit.setPlainText(self._current_prompt)

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

    def _save(self) -> None:
        new_prompt = self.prompt_edit.toPlainText().strip()
        if not new_prompt:
            showCritical("Prompt template must not be empty.", parent=self)
            return

        prompt_history = self._build_prompt_history(new_prompt)

        self._config.update(
            {
                "enabled": self.enabled_checkbox.isChecked(),
                "show_tooltips": self.show_tooltips_checkbox.isChecked(),
                "use_chat_completions_api": self.use_chat_completions_checkbox.isChecked(),
                "openai_api_key": self.api_key_edit.text().strip(),
                "model": self.model_combo.currentData() or self.model_combo.currentText().strip(),
                "system_prompt": self.system_prompt_edit.toPlainText().strip(),
                "prompt_template": new_prompt,
                "show_estimate_before_sending": False,
                "field_mappings": list(self._config.get("field_mappings", [])),
                "prompt_history": prompt_history,
            }
        )

        self._addon_manager.writeConfig(ADDON_NAME, self._config)
        showInfo("AI Automation settings saved.", parent=self)
        self.accept()

    def _open_workflow_settings(self) -> None:
        dialog = WorkflowManagerDialog(parent=self)
        dialog.exec()

    def _open_browser_settings(self) -> None:
        open_browser_settings_dialog(self)

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

    def _build_prompt_history(self, new_prompt: str) -> list[str]:
        history: list[str] = []
        old_prompt = self._current_prompt.strip()
        if old_prompt and old_prompt != new_prompt:
            history.append(old_prompt)

        existing_history = self._config.get("prompt_history", [])
        if isinstance(existing_history, list):
            for entry in existing_history:
                if isinstance(entry, str):
                    stripped = entry.strip()
                    if stripped and stripped != new_prompt and stripped not in history:
                        history.append(stripped)

        return history[:50]

    def _load_config(self) -> dict[str, Any]:
        if self._addon_manager is None:
            return {}

        config = self._addon_manager.getConfig(ADDON_NAME)
        if not isinstance(config, dict):
            return {}
        return dict(config)

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
