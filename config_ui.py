from __future__ import annotations

import json
from typing import Any

from aqt import mw
from aqt.operations import QueryOp
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
    QVBoxLayout,
    QWidget,
)
from aqt.utils import showCritical, showInfo

from .config import ADDON_NAME
from .model_catalog import ModelOption, fallback_model_options, fetch_model_options


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
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(320)
        self.model_status_label = QLabel()
        self.system_prompt_edit = QPlainTextEdit()
        self.prompt_edit = QPlainTextEdit()
        self.note_type_rules_list = QListWidget()
        self.prompt_history_list = QListWidget()
        self.refresh_models_button = QPushButton("Refresh Models")

        self._build_ui()
        self._populate_fields()
        self._refresh_model_options()

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
        content_layout.addWidget(self._build_note_type_rules_group(), 1, 0, 1, 2)

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
        form.addRow("API key", self.api_key_edit)
        form.addRow("Model", model_row)
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

    def _build_note_type_rules_group(self) -> QGroupBox:
        group = QGroupBox("Note Type Rules")
        layout = QVBoxLayout(group)

        rules_label = QLabel(
            "Choose how notes are written back by note type. Prompt placeholders determine what content is sent."
        )
        rules_label.setWordWrap(True)
        layout.addWidget(rules_label)

        self.note_type_rules_list.setMinimumHeight(180)
        layout.addWidget(QLabel("Note type rules"))
        layout.addWidget(self.note_type_rules_list)

        rules_buttons = QHBoxLayout()
        add_rule_button = QPushButton("Add Rule")
        edit_rule_button = QPushButton("Edit Rule")
        delete_rule_button = QPushButton("Delete Rule")
        add_rule_button.clicked.connect(self._add_rule)
        edit_rule_button.clicked.connect(self._edit_rule)
        delete_rule_button.clicked.connect(self._delete_rule)
        rules_buttons.addWidget(add_rule_button)
        rules_buttons.addWidget(edit_rule_button)
        rules_buttons.addWidget(delete_rule_button)
        layout.addLayout(rules_buttons)

        return group

    def _populate_fields(self) -> None:
        self.enabled_checkbox.setChecked(bool(self._config.get("enabled", True)))
        self.api_key_edit.setText(str(self._config.get("openai_api_key", "")))
        self.system_prompt_edit.setPlainText(str(self._config.get("system_prompt", "")))
        self.prompt_edit.setPlainText(self._current_prompt)
        self._populate_rule_list()

        self._set_model_options(
            fallback_model_options(
                current_model=str(self._config.get("model", "")),
                pricing_overrides=self._config.get("model_pricing", {}),
            ),
            current_model=str(self._config.get("model", "")),
        )
        self.model_status_label.setText("Model list not loaded yet. Click Refresh Models to fetch the live list.")

        self.prompt_history_list.clear()
        for prompt in self._config.get("prompt_history", []):
            if isinstance(prompt, str) and prompt.strip():
                self.prompt_history_list.addItem(_history_preview(prompt))

    def _save(self) -> None:
        new_prompt = self.prompt_edit.toPlainText().strip()
        if not new_prompt:
            showCritical("Prompt template must not be empty.", parent=self)
            return

        prompt_history = self._build_prompt_history(new_prompt)

        self._config.update(
            {
                "enabled": self.enabled_checkbox.isChecked(),
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

    def _populate_rule_list(self) -> None:
        self.note_type_rules_list.clear()
        for mapping in self._config.get("field_mappings", []):
            if isinstance(mapping, dict):
                self.note_type_rules_list.addItem(_rule_preview(mapping))

    def _add_rule(self) -> None:
        dialog = MappingDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            mappings = list(self._config.get("field_mappings", []))
            mappings.append(dialog.mapping())
            self._config["field_mappings"] = mappings
            self._populate_rule_list()

    def _edit_rule(self) -> None:
        row = self.note_type_rules_list.currentRow()
        mappings = self._config.get("field_mappings", [])
        if not isinstance(mappings, list) or row < 0 or row >= len(mappings):
            return

        mapping = mappings[row]
        if not isinstance(mapping, dict):
            return

        dialog = MappingDialog(parent=self, mapping=mapping)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            mappings[row] = dialog.mapping()
            self._config["field_mappings"] = mappings
            self._populate_rule_list()
            self.note_type_rules_list.setCurrentRow(row)

    def _delete_rule(self) -> None:
        row = self.note_type_rules_list.currentRow()
        mappings = self._config.get("field_mappings", [])
        if not isinstance(mappings, list) or row < 0 or row >= len(mappings):
            return

        reply = QMessageBox.question(
            self,
            "Delete Note Type Rule",
            "Remove the selected note type rule?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        del mappings[row]
        self._config["field_mappings"] = mappings
        self._populate_rule_list()

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


def _history_preview(prompt: str) -> str:
    single_line = " ".join(prompt.split())
    return single_line[:100] + ("..." if len(single_line) > 100 else "")


def _rule_preview(mapping: dict[str, Any]) -> str:
    note_type = str(mapping.get("note_type", "*"))
    output_fields = mapping.get("output_fields", [])
    output_text = ", ".join(output_fields) if isinstance(output_fields, list) else ""
    extras: list[str] = []
    if mapping.get("prompt_template"):
        extras.append("custom prompt")
    if mapping.get("system_prompt"):
        extras.append("custom system")
    suffix = f" [{', '.join(extras)}]" if extras else ""
    return f"{note_type} -> {output_text}{suffix}"


class MappingDialog(QDialog):
    def __init__(self, parent: QWidget, mapping: dict[str, Any] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Note Type Rule")
        self.resize(620, 520)

        self.note_type_edit = QLineEdit()
        self.output_fields_edit = QLineEdit()
        self.prompt_template_edit = QPlainTextEdit()
        self.system_prompt_edit = QPlainTextEdit()

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.note_type_edit.setPlaceholderText("Basic or *")
        self.output_fields_edit.setPlaceholderText("Back or Japanese Notes, Extra Field")
        self.prompt_template_edit.setPlaceholderText("Optional custom prompt for this note type")
        self.system_prompt_edit.setPlaceholderText("Optional custom system prompt for this note type")
        self.prompt_template_edit.setMinimumHeight(140)
        self.system_prompt_edit.setMinimumHeight(120)
        form.addRow("Note type", self.note_type_edit)
        form.addRow("Output fields", self.output_fields_edit)
        form.addRow("Prompt override", self.prompt_template_edit)
        form.addRow("System override", self.system_prompt_edit)
        layout.addLayout(form)

        help_text = QLabel(
            "Prompt placeholders are the source of truth for what gets sent. "
            "Use output fields here to define which note fields the model should update."
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if mapping:
            self.note_type_edit.setText(str(mapping.get("note_type", "*")))
            output_fields = mapping.get("output_fields", [])
            if isinstance(output_fields, list):
                self.output_fields_edit.setText(", ".join(str(field) for field in output_fields))
            self.prompt_template_edit.setPlainText(str(mapping.get("prompt_template") or ""))
            self.system_prompt_edit.setPlainText(str(mapping.get("system_prompt") or ""))

    def mapping(self) -> dict[str, Any]:
        mapping: dict[str, Any] = {
            "note_type": self.note_type_edit.text().strip() or "*",
            "output_fields": [
                field.strip()
                for field in self.output_fields_edit.text().split(",")
                if field.strip()
            ],
        }
        prompt_template = self.prompt_template_edit.toPlainText().strip()
        system_prompt = self.system_prompt_edit.toPlainText().strip()
        if prompt_template:
            mapping["prompt_template"] = prompt_template
        if system_prompt:
            mapping["system_prompt"] = system_prompt
        return mapping

    def _validate_and_accept(self) -> None:
        mapping = self.mapping()
        if not mapping["output_fields"]:
            showCritical("At least one output field is required.", parent=self)
            return
        self.accept()
