from __future__ import annotations

import json
from typing import Any

from aqt import mw
from aqt.qt import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QDoubleSpinBox,
    QVBoxLayout,
    QWidget,
)
from aqt.utils import showCritical, showInfo

from .config import ADDON_NAME


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
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.model_edit = QLineEdit()
        self.system_prompt_edit = QPlainTextEdit()
        self.prompt_edit = QPlainTextEdit()
        self.field_mappings_edit = QPlainTextEdit()
        self.model_pricing_edit = QPlainTextEdit()
        self.prompt_history_list = QListWidget()
        self.show_estimate_checkbox = QCheckBox("Show token/cost estimate before sending")
        self.batch_size_spin = QSpinBox()
        self.request_timeout_spin = QSpinBox()
        self.max_retries_spin = QSpinBox()
        self.retry_backoff_spin = QDoubleSpinBox()
        self.temperature_spin = QDoubleSpinBox()
        self.reasoning_effort_combo = QComboBox()
        self.estimated_output_tokens_spin = QSpinBox()
        self.usage_history_limit_spin = QSpinBox()

        self._build_ui()
        self._populate_fields()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        intro = QLabel(
            "Edit AI Automation settings in a structured form. "
            "Saving writes to Anki's stored add-on config for this profile."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        content_layout = QGridLayout()
        content_layout.setColumnStretch(0, 3)
        content_layout.setColumnStretch(1, 2)
        layout.addLayout(content_layout)

        content_layout.addWidget(self._build_main_settings_group(), 0, 0)
        content_layout.addWidget(self._build_prompt_history_group(), 0, 1)
        content_layout.addWidget(self._build_advanced_group(), 1, 0, 1, 2)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_main_settings_group(self) -> QGroupBox:
        group = QGroupBox("Core Settings")
        form = QFormLayout(group)

        self.api_key_edit.setPlaceholderText("sk-...")
        self.model_edit.setPlaceholderText("gpt-5-mini")
        self.system_prompt_edit.setPlaceholderText("System prompt sent with every request")
        self.prompt_edit.setPlaceholderText("Use placeholders like {{Front}}, {{Back}}, {{NoteType}}")
        self.prompt_edit.setMinimumHeight(180)

        form.addRow(self.enabled_checkbox)
        form.addRow("API key", self.api_key_edit)
        form.addRow("Model", self.model_edit)
        form.addRow("System prompt", self.system_prompt_edit)
        form.addRow("Prompt template", self.prompt_edit)
        return group

    def _build_prompt_history_group(self) -> QGroupBox:
        group = QGroupBox("Prompt History")
        layout = QVBoxLayout(group)

        help_text = QLabel(
            "When you save a changed prompt, the previous prompt is kept here so you can restore it later."
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        layout.addWidget(self.prompt_history_list)

        button_row = QHBoxLayout()
        use_selected_button = QPushButton("Use Selected Prompt")
        delete_selected_button = QPushButton("Delete Selected")
        use_selected_button.clicked.connect(self._use_selected_prompt)
        delete_selected_button.clicked.connect(self._delete_selected_prompt)
        button_row.addWidget(use_selected_button)
        button_row.addWidget(delete_selected_button)
        layout.addLayout(button_row)
        return group

    def _build_advanced_group(self) -> QGroupBox:
        group = QGroupBox("Advanced Settings")
        layout = QVBoxLayout(group)

        form = QFormLayout()
        self.batch_size_spin.setRange(1, 500)
        self.request_timeout_spin.setRange(1, 3600)
        self.max_retries_spin.setRange(0, 20)
        self.retry_backoff_spin.setRange(0.0, 300.0)
        self.retry_backoff_spin.setDecimals(2)
        self.temperature_spin.setRange(-1.0, 2.0)
        self.temperature_spin.setDecimals(2)
        self.temperature_spin.setSingleStep(0.1)
        self.reasoning_effort_combo.addItems(["", "minimal", "low", "medium", "high"])
        self.estimated_output_tokens_spin.setRange(1, 100000)
        self.usage_history_limit_spin.setRange(1, 1000)

        temperature_help = QLabel("Set to -1 to store JSON null and omit temperature from requests.")
        temperature_help.setWordWrap(True)

        form.addRow(self.show_estimate_checkbox)
        form.addRow("Batch size", self.batch_size_spin)
        form.addRow("Request timeout (seconds)", self.request_timeout_spin)
        form.addRow("Max retries", self.max_retries_spin)
        form.addRow("Retry backoff (seconds)", self.retry_backoff_spin)
        form.addRow("Temperature", self.temperature_spin)
        form.addRow("", temperature_help)
        form.addRow("Reasoning effort", self.reasoning_effort_combo)
        form.addRow("Estimated output tokens per note", self.estimated_output_tokens_spin)
        form.addRow("Usage history limit", self.usage_history_limit_spin)
        layout.addLayout(form)

        mappings_label = QLabel(
            "Field mappings and model pricing remain editable as JSON here so complex structures stay fully supported."
        )
        mappings_label.setWordWrap(True)
        layout.addWidget(mappings_label)

        self.field_mappings_edit.setMinimumHeight(180)
        self.model_pricing_edit.setMinimumHeight(120)
        layout.addWidget(QLabel("Field mappings JSON"))
        layout.addWidget(self.field_mappings_edit)
        layout.addWidget(QLabel("Model pricing JSON"))
        layout.addWidget(self.model_pricing_edit)
        return group

    def _populate_fields(self) -> None:
        self.enabled_checkbox.setChecked(bool(self._config.get("enabled", True)))
        self.api_key_edit.setText(str(self._config.get("openai_api_key", "")))
        self.model_edit.setText(str(self._config.get("model", "")))
        self.system_prompt_edit.setPlainText(str(self._config.get("system_prompt", "")))
        self.prompt_edit.setPlainText(self._current_prompt)
        self.show_estimate_checkbox.setChecked(bool(self._config.get("show_estimate_before_sending", True)))
        self.batch_size_spin.setValue(int(self._config.get("batch_size", 5)))
        self.request_timeout_spin.setValue(int(float(self._config.get("request_timeout_seconds", 90))))
        self.max_retries_spin.setValue(int(self._config.get("max_retries", 2)))
        self.retry_backoff_spin.setValue(float(self._config.get("retry_backoff_seconds", 2.0)))

        temperature = self._config.get("temperature")
        self.temperature_spin.setValue(-1.0 if temperature is None else float(temperature))

        reasoning_effort = str(self._config.get("reasoning_effort", "") or "")
        index = self.reasoning_effort_combo.findText(reasoning_effort)
        self.reasoning_effort_combo.setCurrentIndex(max(0, index))

        self.estimated_output_tokens_spin.setValue(int(self._config.get("estimated_output_tokens_per_note", 200)))
        self.usage_history_limit_spin.setValue(int(self._config.get("usage_history_limit", 20)))

        self.field_mappings_edit.setPlainText(
            json.dumps(self._config.get("field_mappings", []), indent=2, ensure_ascii=True)
        )
        self.model_pricing_edit.setPlainText(
            json.dumps(self._config.get("model_pricing", {}), indent=2, ensure_ascii=True)
        )

        self.prompt_history_list.clear()
        for prompt in self._config.get("prompt_history", []):
            if isinstance(prompt, str) and prompt.strip():
                self.prompt_history_list.addItem(_history_preview(prompt))

    def _save(self) -> None:
        try:
            field_mappings = json.loads(self.field_mappings_edit.toPlainText() or "[]")
            model_pricing = json.loads(self.model_pricing_edit.toPlainText() or "{}")
        except json.JSONDecodeError as error:
            showCritical(f"Invalid JSON in advanced settings: {error}", parent=self)
            return

        if not isinstance(field_mappings, list):
            showCritical("Field mappings JSON must be a list.", parent=self)
            return
        if not isinstance(model_pricing, dict):
            showCritical("Model pricing JSON must be an object.", parent=self)
            return

        new_prompt = self.prompt_edit.toPlainText().strip()
        if not new_prompt:
            showCritical("Prompt template must not be empty.", parent=self)
            return

        prompt_history = self._build_prompt_history(new_prompt)

        self._config.update(
            {
                "enabled": self.enabled_checkbox.isChecked(),
                "openai_api_key": self.api_key_edit.text().strip(),
                "model": self.model_edit.text().strip(),
                "system_prompt": self.system_prompt_edit.toPlainText().strip(),
                "prompt_template": new_prompt,
                "show_estimate_before_sending": self.show_estimate_checkbox.isChecked(),
                "batch_size": self.batch_size_spin.value(),
                "request_timeout_seconds": self.request_timeout_spin.value(),
                "max_retries": self.max_retries_spin.value(),
                "retry_backoff_seconds": self.retry_backoff_spin.value(),
                "temperature": None if self.temperature_spin.value() < 0 else self.temperature_spin.value(),
                "reasoning_effort": self.reasoning_effort_combo.currentText() or None,
                "estimated_output_tokens_per_note": self.estimated_output_tokens_spin.value(),
                "usage_history_limit": self.usage_history_limit_spin.value(),
                "field_mappings": field_mappings,
                "model_pricing": model_pricing,
                "prompt_history": prompt_history,
            }
        )

        self._addon_manager.writeConfig(ADDON_NAME, self._config)
        showInfo("AI Automation settings saved.", parent=self)
        self.accept()

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

    def _use_selected_prompt(self) -> None:
        row = self.prompt_history_list.currentRow()
        history = self._config.get("prompt_history", [])
        if not isinstance(history, list) or row < 0 or row >= len(history):
            return
        selected_prompt = history[row]
        if isinstance(selected_prompt, str):
            self.prompt_edit.setPlainText(selected_prompt)

    def _delete_selected_prompt(self) -> None:
        row = self.prompt_history_list.currentRow()
        history = self._config.get("prompt_history", [])
        if not isinstance(history, list) or row < 0 or row >= len(history):
            return

        reply = QMessageBox.question(
            self,
            "Delete Prompt History Entry",
            "Remove the selected prompt from history?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        del history[row]
        self._config["prompt_history"] = history
        self._populate_fields()

    def _load_config(self) -> dict[str, Any]:
        if self._addon_manager is None:
            return {}

        config = self._addon_manager.getConfig(ADDON_NAME)
        if not isinstance(config, dict):
            return {}
        return dict(config)


def _history_preview(prompt: str) -> str:
    single_line = " ".join(prompt.split())
    return single_line[:100] + ("..." if len(single_line) > 100 else "")
