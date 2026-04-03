from __future__ import annotations

from dataclasses import dataclass

from aqt import mw
from aqt.browser import Browser
from aqt.qt import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)
from aqt.utils import showCritical

from .config import (
    ConfigError,
    ProcessingPreset,
    SavedPrompt,
    SavedSystemPrompt,
    load_config,
    load_raw_config,
    new_object_id,
    save_raw_config,
)
from .model_catalog import fallback_model_options
from .processing import (
    ManualProcessingSpec,
    WRITE_MODE_APPEND,
    WRITE_MODE_OVERWRITE,
    WRITE_MODE_SKIP_NONEMPTY,
    run_manual_ai_processing,
)
from .ui_tooltips import set_hover_help, show_tooltip


@dataclass(frozen=True)
class PromptChoice:
    prompt_id: str
    name: str
    prompt_text: str


@dataclass(frozen=True)
class ProcessingPresetChoice:
    preset_id: str
    name: str
    prompt_id: str
    model: str | None
    temperature: float | None
    system_prompt_id: str | None
    target_field: str
    mode: str
    multiple_target_fields: bool
    convert_markdown_to_html: bool
    response_delimiter: str | None


def open_transform_dialog(browser: Browser, note_ids: list[int]) -> None:
    try:
        config = load_config()
    except ConfigError as error:
        showCritical(str(error), parent=browser)
        return
    if not config.enabled:
        show_tooltip("AI Automation is disabled in the add-on config.", parent=browser)
        return

    if mw is None or mw.col is None:
        showCritical("Anki collection is not available.", parent=browser)
        return

    try:
        dialog = TransformWithAIDialog(parent=browser, note_ids=note_ids, config=config)
    except ConfigError as error:
        showCritical(str(error), parent=browser)
        return
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return

    try:
        config = load_config()
    except ConfigError as error:
        showCritical(str(error), parent=browser)
        return

    spec = dialog.processing_spec()
    if spec is None:
        return
    run_manual_ai_processing(browser, config, note_ids, spec)


class TransformWithAIDialog(QDialog):
    def __init__(self, parent: Browser, note_ids: list[int], config) -> None:
        super().__init__(parent)
        self.setWindowTitle("Transform with AI")
        self.resize(760, 620)

        self._browser = parent
        self._note_ids = note_ids
        self._config = config
        self._raw_config = load_raw_config()
        self._prompts = _prompt_choices_from_saved_prompts(config.saved_prompts)
        self._system_prompts = _prompt_choices_from_saved_system_prompts(config.saved_system_prompts)
        self._presets = _preset_choices_from_saved_processing_presets(config.processing_presets)
        self._field_choices, self._field_summary = _collect_common_fields(note_ids)
        self._model_options = fallback_model_options(
            current_model=config.model,
            pricing_overrides=config.model_pricing,
        )

        self.note_count_label = QLabel()
        self.note_types_label = QLabel()
        self.model_combo = QComboBox()
        self.use_global_temperature_check = QCheckBox("Use global temperature")
        self.temperature_spin = QDoubleSpinBox()
        self.preset_combo = QComboBox()
        self.multiple_target_fields_check = QCheckBox("Multiple target fields")
        self.convert_markdown_to_html_check = QCheckBox("Convert Markdown to HTML")
        self.delimiter_edit = QLineEdit()
        self.target_field_combo = QComboBox()
        self.prompt_combo = QComboBox()
        self.system_prompt_combo = QComboBox()
        self.mode_combo = QComboBox()
        self.prompt_preview = QPlainTextEdit()
        self.prompt_preview.setMinimumHeight(160)
        self.system_prompt_preview = QPlainTextEdit()
        self.system_prompt_preview.setMinimumHeight(140)

        self.run_button = QPushButton("Run")
        self.run_button.clicked.connect(self._validate_and_accept)
        self.multiple_target_fields_check.toggled.connect(self._refresh_target_mode_ui)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        self.prompt_preview.textChanged.connect(self._sync_prompt_from_editor)
        self.system_prompt_preview.textChanged.connect(self._sync_system_prompt_from_editor)
        self.use_global_temperature_check.toggled.connect(self._refresh_temperature_ui)

        self._build_ui()
        self._populate()

    def processing_spec(self) -> ManualProcessingSpec | None:
        prompt = self._selected_prompt()
        system_prompt = self._selected_system_prompt()
        target_field = self.target_field_combo.currentData() or self.target_field_combo.currentText().strip()
        write_mode = self.mode_combo.currentData() or WRITE_MODE_OVERWRITE
        model = self.model_combo.currentData() or self.model_combo.currentText().strip()
        if not prompt or not system_prompt:
            return None
        if not self.multiple_target_fields_check.isChecked():
            if not isinstance(target_field, str) or not target_field.strip():
                return None
        return ManualProcessingSpec(
            prompt_name=prompt.name,
            prompt_template=self.prompt_preview.toPlainText().strip(),
            target_field="" if self.multiple_target_fields_check.isChecked() else target_field,
            system_prompt_name=system_prompt.name,
            system_prompt=self.system_prompt_preview.toPlainText().strip(),
            write_mode=str(write_mode),
            model=str(model),
            temperature=self._selected_temperature(),
            multiple_target_fields=self.multiple_target_fields_check.isChecked(),
            convert_markdown_to_html=self.convert_markdown_to_html_check.isChecked(),
            response_delimiter=self.delimiter_edit.text().strip(),
        )

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        intro = QLabel(
            "Run a saved AI prompt on the selected Browser notes."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        summary_group = QGroupBox("Selection")
        summary_form = QFormLayout(summary_group)
        self.note_count_label.setWordWrap(True)
        self.note_types_label.setWordWrap(True)
        summary_form.addRow("Notes", self.note_count_label)
        summary_form.addRow("Note types", self.note_types_label)
        set_hover_help(self.note_count_label, "How many selected Browser rows resolve to notes that can be processed.", enabled=self._config.show_tooltips)
        set_hover_help(self.note_types_label, "Shared note types across the current selection.", enabled=self._config.show_tooltips)
        layout.addWidget(summary_group)

        options_group = QGroupBox("Run Settings")
        options_form = QFormLayout(options_group)

        preset_row = QWidget()
        preset_layout = QHBoxLayout(preset_row)
        preset_layout.setContentsMargins(0, 0, 0, 0)
        preset_layout.addWidget(self.preset_combo, stretch=1)
        save_preset_button = QPushButton("Save")
        update_preset_button = QPushButton("Update")
        delete_preset_button = QPushButton("Delete")
        set_hover_help(self.preset_combo, "Load a saved Browser-processing preset.", enabled=self._config.show_tooltips)
        set_hover_help(save_preset_button, "Save the current run settings as a reusable preset.", enabled=self._config.show_tooltips)
        set_hover_help(update_preset_button, "Overwrite the selected preset with the current run settings.", enabled=self._config.show_tooltips)
        set_hover_help(delete_preset_button, "Delete the selected preset.", enabled=self._config.show_tooltips)
        save_preset_button.clicked.connect(self._save_current_as_preset)
        update_preset_button.clicked.connect(self._update_selected_preset)
        delete_preset_button.clicked.connect(self._delete_selected_preset)
        preset_layout.addWidget(save_preset_button)
        preset_layout.addWidget(update_preset_button)
        preset_layout.addWidget(delete_preset_button)

        prompt_row = QWidget()
        prompt_layout = QHBoxLayout(prompt_row)
        prompt_layout.setContentsMargins(0, 0, 0, 0)
        prompt_layout.addWidget(self.prompt_combo, stretch=1)

        new_button = QPushButton("New")
        edit_button = QPushButton("Edit")
        delete_button = QPushButton("Delete")
        set_hover_help(self.prompt_combo, "Choose the saved user prompt for this run.", enabled=self._config.show_tooltips)
        set_hover_help(new_button, "Create a new saved user prompt.", enabled=self._config.show_tooltips)
        set_hover_help(edit_button, "Edit the selected saved user prompt.", enabled=self._config.show_tooltips)
        set_hover_help(delete_button, "Delete the selected saved user prompt.", enabled=self._config.show_tooltips)
        new_button.clicked.connect(self._create_prompt)
        edit_button.clicked.connect(self._edit_prompt)
        delete_button.clicked.connect(self._delete_prompt)
        prompt_layout.addWidget(new_button)
        prompt_layout.addWidget(edit_button)
        prompt_layout.addWidget(delete_button)

        system_prompt_row = QWidget()
        system_prompt_layout = QHBoxLayout(system_prompt_row)
        system_prompt_layout.setContentsMargins(0, 0, 0, 0)
        system_prompt_layout.addWidget(self.system_prompt_combo, stretch=1)

        new_system_button = QPushButton("New")
        edit_system_button = QPushButton("Edit")
        delete_system_button = QPushButton("Delete")
        set_hover_help(self.system_prompt_combo, "Choose the saved system prompt for this run.", enabled=self._config.show_tooltips)
        set_hover_help(new_system_button, "Create a new saved system prompt.", enabled=self._config.show_tooltips)
        set_hover_help(edit_system_button, "Edit the selected saved system prompt.", enabled=self._config.show_tooltips)
        set_hover_help(delete_system_button, "Delete the selected saved system prompt.", enabled=self._config.show_tooltips)
        new_system_button.clicked.connect(self._create_system_prompt)
        edit_system_button.clicked.connect(self._edit_system_prompt)
        delete_system_button.clicked.connect(self._delete_system_prompt)
        system_prompt_layout.addWidget(new_system_button)
        system_prompt_layout.addWidget(edit_system_button)
        system_prompt_layout.addWidget(delete_system_button)

        self.prompt_combo.currentIndexChanged.connect(self._refresh_prompt_preview)
        self.system_prompt_combo.currentIndexChanged.connect(self._refresh_system_prompt_preview)
        self.mode_combo.addItem("Overwrite target field", WRITE_MODE_OVERWRITE)
        self.mode_combo.addItem("Append to target field", WRITE_MODE_APPEND)
        self.mode_combo.addItem("Skip if target field not empty", WRITE_MODE_SKIP_NONEMPTY)
        self.temperature_spin.setDecimals(2)
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.1)
        self.temperature_spin.setValue(self._config.temperature if self._config.temperature is not None else 0.2)
        self.use_global_temperature_check.setChecked(True)
        set_hover_help(self.model_combo, "Model used for this run. It can differ from the global default.", enabled=self._config.show_tooltips)
        set_hover_help(self.use_global_temperature_check, "Use the global temperature from the add-on config instead of a run-specific value.", enabled=self._config.show_tooltips)
        set_hover_help(self.temperature_spin, "Lower values are steadier; higher values allow more variation.", enabled=self._config.show_tooltips)
        set_hover_help(self.multiple_target_fields_check, "Expect the model response to contain delimited sections that map to multiple note fields.", enabled=self._config.show_tooltips)
        set_hover_help(self.convert_markdown_to_html_check, "Convert generated Markdown into Anki-friendly HTML before writing it back.", enabled=self._config.show_tooltips)
        set_hover_help(self.delimiter_edit, "Delimiter used to split a multi-field response, for example --Notes-- or --{field}--.", enabled=self._config.show_tooltips)
        set_hover_help(self.target_field_combo, "Single note field that should receive the generated output.", enabled=self._config.show_tooltips)
        set_hover_help(self.mode_combo, "Choose whether generated text overwrites, appends, or skips already-filled target fields.", enabled=self._config.show_tooltips)
        set_hover_help(self.prompt_preview, "Editable text of the selected user prompt. Changes are saved back to that prompt.", enabled=self._config.show_tooltips)
        set_hover_help(self.system_prompt_preview, "Editable text of the selected system prompt. Changes are saved back to that prompt.", enabled=self._config.show_tooltips)
        set_hover_help(self.run_button, "Start processing the selected notes with the current settings.", enabled=self._config.show_tooltips)

        options_form.addRow("Preset", preset_row)
        options_form.addRow("Model", self.model_combo)
        temperature_row = QWidget()
        temperature_layout = QHBoxLayout(temperature_row)
        temperature_layout.setContentsMargins(0, 0, 0, 0)
        temperature_layout.addWidget(self.use_global_temperature_check)
        temperature_layout.addWidget(self.temperature_spin)
        options_form.addRow("Temperature", temperature_row)
        options_form.addRow("", self.multiple_target_fields_check)
        options_form.addRow("", self.convert_markdown_to_html_check)
        self.delimiter_edit.setPlaceholderText("--Notes-- or --{field}--")
        options_form.addRow("Response delimiter", self.delimiter_edit)
        options_form.addRow("Target field", self.target_field_combo)
        options_form.addRow("Saved prompt", prompt_row)
        options_form.addRow("System prompt", system_prompt_row)
        options_form.addRow("Write mode", self.mode_combo)
        layout.addWidget(options_group)

        layout.addWidget(QLabel("Prompt"))
        layout.addWidget(self.prompt_preview)
        layout.addWidget(QLabel("System prompt"))
        layout.addWidget(self.system_prompt_preview)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        buttons.addButton(self.run_button, QDialogButtonBox.ButtonRole.AcceptRole)
        layout.addWidget(buttons)

    def _populate(self) -> None:
        self.note_count_label.setText(str(len(self._note_ids)))
        self.note_types_label.setText(self._field_summary["note_types"])

        self._populate_model_combo()
        self._populate_preset_combo()
        self.target_field_combo.clear()
        for field_name in self._field_choices:
            self.target_field_combo.addItem(field_name, field_name)

        self._populate_prompt_combo()
        self._populate_system_prompt_combo()
        self._refresh_prompt_preview()
        self._refresh_system_prompt_preview()
        self._refresh_target_mode_ui()
        self._refresh_temperature_ui()

        has_prompt = bool(self._prompts)
        has_system_prompt = bool(self._system_prompts)
        has_model = self.model_combo.count() > 0
        self.run_button.setEnabled(has_prompt and has_system_prompt and has_model)

    def _populate_model_combo(self) -> None:
        current_model = str(self._raw_config.get("model", "")).strip()
        if self._config.model:
            current_model = self._config.model
        self.model_combo.clear()
        for option in self._model_options:
            self.model_combo.addItem(option.label, option.model_id)
        if current_model:
            index = self.model_combo.findData(current_model)
            if index >= 0:
                self.model_combo.setCurrentIndex(index)
            else:
                self.model_combo.insertItem(0, current_model + " (Current selection)", current_model)
                self.model_combo.setCurrentIndex(0)

    def _populate_preset_combo(self) -> None:
        selected_preset_id = self.preset_combo.currentData()
        self.preset_combo.clear()
        self.preset_combo.addItem("Choose a preset", "")
        for preset in self._presets:
            self.preset_combo.addItem(preset.name, preset.preset_id)
        if selected_preset_id:
            index = self.preset_combo.findData(selected_preset_id)
            if index >= 0:
                self.preset_combo.setCurrentIndex(index)

    def _populate_prompt_combo(self) -> None:
        selected_prompt_id = self.prompt_combo.currentData()
        self.prompt_combo.clear()
        for prompt in self._prompts:
            self.prompt_combo.addItem(prompt.name, prompt.prompt_id)
        if selected_prompt_id:
            index = self.prompt_combo.findData(selected_prompt_id)
            if index >= 0:
                self.prompt_combo.setCurrentIndex(index)

    def _selected_prompt(self) -> PromptChoice | None:
        prompt_id = self.prompt_combo.currentData()
        for prompt in self._prompts:
            if prompt.prompt_id == prompt_id:
                return prompt
        return self._prompts[0] if self._prompts else None

    def _populate_system_prompt_combo(self) -> None:
        selected_prompt_id = self.system_prompt_combo.currentData()
        self.system_prompt_combo.clear()
        for prompt in self._system_prompts:
            self.system_prompt_combo.addItem(prompt.name, prompt.prompt_id)
        if selected_prompt_id:
            index = self.system_prompt_combo.findData(selected_prompt_id)
            if index >= 0:
                self.system_prompt_combo.setCurrentIndex(index)

    def _selected_system_prompt(self) -> PromptChoice | None:
        prompt_id = self.system_prompt_combo.currentData()
        for prompt in self._system_prompts:
            if prompt.prompt_id == prompt_id:
                return prompt
        return self._system_prompts[0] if self._system_prompts else None

    def _refresh_prompt_preview(self) -> None:
        prompt = self._selected_prompt()
        self.prompt_preview.blockSignals(True)
        self.prompt_preview.setPlainText(prompt.prompt_text if prompt else "")
        self.prompt_preview.blockSignals(False)

    def _refresh_system_prompt_preview(self) -> None:
        prompt = self._selected_system_prompt()
        self.system_prompt_preview.blockSignals(True)
        self.system_prompt_preview.setPlainText(prompt.prompt_text if prompt else "")
        self.system_prompt_preview.blockSignals(False)

    def _sync_prompt_from_editor(self) -> None:
        prompt = self._selected_prompt()
        if prompt is None:
            return
        updated_text = self.prompt_preview.toPlainText().strip()
        for index, current in enumerate(self._prompts):
            if current.prompt_id == prompt.prompt_id:
                self._prompts[index] = PromptChoice(
                    prompt_id=current.prompt_id,
                    name=current.name,
                    prompt_text=updated_text,
                )
                self._save_prompts()
                return

    def _sync_system_prompt_from_editor(self) -> None:
        prompt = self._selected_system_prompt()
        if prompt is None:
            return
        updated_text = self.system_prompt_preview.toPlainText().strip()
        for index, current in enumerate(self._system_prompts):
            if current.prompt_id == prompt.prompt_id:
                self._system_prompts[index] = PromptChoice(
                    prompt_id=current.prompt_id,
                    name=current.name,
                    prompt_text=updated_text,
                )
                self._save_system_prompts()
                return

    def _refresh_target_mode_ui(self) -> None:
        is_multi = self.multiple_target_fields_check.isChecked()
        self.target_field_combo.setEnabled(not is_multi)
        self.delimiter_edit.setEnabled(is_multi)
        if is_multi and self.mode_combo.currentData() == WRITE_MODE_SKIP_NONEMPTY:
            self._set_combo_to_data(self.mode_combo, WRITE_MODE_OVERWRITE)

    def _refresh_temperature_ui(self) -> None:
        self.temperature_spin.setEnabled(not self.use_global_temperature_check.isChecked())

    def _selected_preset(self) -> ProcessingPresetChoice | None:
        preset_id = self.preset_combo.currentData()
        for preset in self._presets:
            if preset.preset_id == preset_id:
                return preset
        return None

    def _on_preset_changed(self) -> None:
        preset = self._selected_preset()
        if preset is None:
            return
        self._apply_preset(preset)

    def _apply_preset(self, preset: ProcessingPresetChoice) -> None:
        self._set_combo_to_data(self.model_combo, preset.model)
        self._set_combo_to_data(self.prompt_combo, preset.prompt_id)
        self._set_combo_to_data(self.system_prompt_combo, preset.system_prompt_id)
        self._set_combo_to_data(self.mode_combo, preset.mode)
        self._set_temperature(preset.temperature)
        self.multiple_target_fields_check.setChecked(preset.multiple_target_fields)
        self.convert_markdown_to_html_check.setChecked(preset.convert_markdown_to_html)
        self.delimiter_edit.setText(preset.response_delimiter or "")
        if preset.target_field:
            self._set_target_field(preset.target_field)
        self._refresh_prompt_preview()
        self._refresh_system_prompt_preview()
        self._refresh_target_mode_ui()

    def _save_current_as_preset(self) -> None:
        dialog = SavedPromptDialog(
            parent=self,
            window_title="Processing Preset",
            prompt_label="Description",
            placeholder_text="Optional notes about this preset",
            help_text="Save the current Browser processing settings with a reusable name.",
            id_prefix="processing-preset",
            require_prompt_text=False,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        choice = dialog.named_item()
        if choice is None:
            return

        target_field = self.target_field_combo.currentData() or self.target_field_combo.currentText().strip()
        preset = ProcessingPresetChoice(
            preset_id=choice.prompt_id,
            name=choice.name,
            prompt_id=str(self.prompt_combo.currentData() or ""),
            model=str(self.model_combo.currentData() or self.model_combo.currentText().strip()) or None,
            temperature=self._selected_temperature(),
            system_prompt_id=str(self.system_prompt_combo.currentData() or "") or None,
            target_field="" if self.multiple_target_fields_check.isChecked() else str(target_field or ""),
            mode=str(self.mode_combo.currentData() or WRITE_MODE_OVERWRITE),
            multiple_target_fields=self.multiple_target_fields_check.isChecked(),
            convert_markdown_to_html=self.convert_markdown_to_html_check.isChecked(),
            response_delimiter=self.delimiter_edit.text().strip() or None,
        )
        self._presets.append(preset)
        self._save_processing_presets()
        self._populate_preset_combo()
        index = self.preset_combo.findData(preset.preset_id)
        if index >= 0:
            self.preset_combo.setCurrentIndex(index)

    def _update_selected_preset(self) -> None:
        preset = self._selected_preset()
        if preset is None:
            show_tooltip("Choose a preset to update.", parent=self)
            return

        updated = self._current_preset_choice(
            preset_id=preset.preset_id,
            name=preset.name,
        )
        for index, current in enumerate(self._presets):
            if current.preset_id == preset.preset_id:
                self._presets[index] = updated
                break
        self._save_processing_presets()
        self._populate_preset_combo()
        index = self.preset_combo.findData(updated.preset_id)
        if index >= 0:
            self.preset_combo.setCurrentIndex(index)
        show_tooltip(f"Updated preset '{updated.name}'.", parent=self)

    def _delete_selected_preset(self) -> None:
        preset = self._selected_preset()
        if preset is None:
            show_tooltip("Choose a preset to delete.", parent=self)
            return
        reply = QMessageBox.question(
            self,
            "Delete Processing Preset",
            f"Delete the processing preset '{preset.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._presets = [item for item in self._presets if item.preset_id != preset.preset_id]
        self._save_processing_presets()
        self._populate_preset_combo()

    def _save_processing_presets(self) -> None:
        self._raw_config["saved_processing_presets"] = [
            {
                "id": preset.preset_id,
                "name": preset.name,
                "prompt_id": preset.prompt_id,
                "model": preset.model,
                "temperature": preset.temperature,
                "system_prompt_id": preset.system_prompt_id,
                "target_field": preset.target_field,
                "mode": preset.mode,
                "multiple_target_fields": preset.multiple_target_fields,
                "convert_markdown_to_html": preset.convert_markdown_to_html,
                "response_delimiter": preset.response_delimiter,
            }
            for preset in self._presets
        ]
        save_raw_config(self._raw_config)

    def _current_preset_choice(self, *, preset_id: str, name: str) -> ProcessingPresetChoice:
        target_field = self.target_field_combo.currentData() or self.target_field_combo.currentText().strip()
        return ProcessingPresetChoice(
            preset_id=preset_id,
            name=name,
            prompt_id=str(self.prompt_combo.currentData() or ""),
            model=str(self.model_combo.currentData() or self.model_combo.currentText().strip()) or None,
            temperature=self._selected_temperature(),
            system_prompt_id=str(self.system_prompt_combo.currentData() or "") or None,
            target_field="" if self.multiple_target_fields_check.isChecked() else str(target_field or ""),
            mode=str(self.mode_combo.currentData() or WRITE_MODE_OVERWRITE),
            multiple_target_fields=self.multiple_target_fields_check.isChecked(),
            convert_markdown_to_html=self.convert_markdown_to_html_check.isChecked(),
            response_delimiter=self.delimiter_edit.text().strip() or None,
        )

    def _set_combo_to_data(self, combo: QComboBox, value: str | None) -> None:
        lookup = value or ""
        index = combo.findData(lookup)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _selected_temperature(self) -> float | None:
        if self.use_global_temperature_check.isChecked():
            return None
        return float(self.temperature_spin.value())

    def _set_temperature(self, value: float | None) -> None:
        self.use_global_temperature_check.setChecked(value is None)
        if value is not None:
            self.temperature_spin.setValue(float(value))
        self._refresh_temperature_ui()

    def _set_target_field(self, field_name: str) -> None:
        index = self.target_field_combo.findData(field_name)
        if index >= 0:
            self.target_field_combo.setCurrentIndex(index)
            return
        index = self.target_field_combo.findText(field_name)
        if index >= 0:
            self.target_field_combo.setCurrentIndex(index)
            return
        self.target_field_combo.setEditText(field_name)

    def _create_prompt(self) -> None:
        dialog = SavedPromptDialog(
            parent=self,
            window_title="Saved Prompt",
            prompt_label="Prompt",
            placeholder_text="Use placeholders like {{Front}}, {{Back}}, {{NoteType}}",
            help_text="Prompt names appear in the picker. The full prompt text is still stored and used during processing.",
            id_prefix="prompt",
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        choice = dialog.prompt_choice()
        if choice is None:
            return
        self._prompts.append(choice)
        self._save_prompts()
        self._populate_prompt_combo()
        index = self.prompt_combo.findData(choice.prompt_id)
        if index >= 0:
            self.prompt_combo.setCurrentIndex(index)
        self._refresh_prompt_preview()

    def _edit_prompt(self) -> None:
        prompt = self._selected_prompt()
        if prompt is None:
            return

        dialog = SavedPromptDialog(
            parent=self,
            prompt=prompt,
            window_title="Saved Prompt",
            prompt_label="Prompt",
            placeholder_text="Use placeholders like {{Front}}, {{Back}}, {{NoteType}}",
            help_text="Prompt names appear in the picker. The full prompt text is still stored and used during processing.",
            id_prefix="prompt",
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        replacement = dialog.prompt_choice(existing_id=prompt.prompt_id)
        if replacement is None:
            return

        for index, current in enumerate(self._prompts):
            if current.prompt_id == prompt.prompt_id:
                self._prompts[index] = replacement
                break

        self._save_prompts()
        self._populate_prompt_combo()
        index = self.prompt_combo.findData(replacement.prompt_id)
        if index >= 0:
            self.prompt_combo.setCurrentIndex(index)
        self._refresh_prompt_preview()

    def _create_system_prompt(self) -> None:
        dialog = SavedPromptDialog(
            parent=self,
            window_title="Saved System Prompt",
            prompt_label="System prompt",
            placeholder_text="You improve Anki flashcards...",
            help_text="System prompt names appear in the picker. Use this to keep reusable instruction sets with clear names.",
            id_prefix="system-prompt",
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        choice = dialog.prompt_choice()
        if choice is None:
            return
        self._system_prompts.append(choice)
        self._save_system_prompts()
        self._populate_system_prompt_combo()
        index = self.system_prompt_combo.findData(choice.prompt_id)
        if index >= 0:
            self.system_prompt_combo.setCurrentIndex(index)
        self._refresh_system_prompt_preview()

    def _edit_system_prompt(self) -> None:
        prompt = self._selected_system_prompt()
        if prompt is None:
            return

        dialog = SavedPromptDialog(
            parent=self,
            prompt=prompt,
            window_title="Saved System Prompt",
            prompt_label="System prompt",
            placeholder_text="You improve Anki flashcards...",
            help_text="System prompt names appear in the picker. Use this to keep reusable instruction sets with clear names.",
            id_prefix="system-prompt",
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        replacement = dialog.prompt_choice(existing_id=prompt.prompt_id)
        if replacement is None:
            return

        for index, current in enumerate(self._system_prompts):
            if current.prompt_id == prompt.prompt_id:
                self._system_prompts[index] = replacement
                break

        self._save_system_prompts()
        self._populate_system_prompt_combo()
        index = self.system_prompt_combo.findData(replacement.prompt_id)
        if index >= 0:
            self.system_prompt_combo.setCurrentIndex(index)
        self._refresh_system_prompt_preview()

    def _delete_prompt(self) -> None:
        prompt = self._selected_prompt()
        if prompt is None:
            return

        if prompt.prompt_id == "default-prompt" and len(self._prompts) == 1:
            showCritical("Create another saved prompt before deleting the only available prompt.", parent=self)
            return

        reply = QMessageBox.question(
            self,
            "Delete Saved Prompt",
            f"Delete the saved prompt '{prompt.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._prompts = [item for item in self._prompts if item.prompt_id != prompt.prompt_id]
        if not self._prompts:
            self._prompts = [
                PromptChoice(
                    prompt_id="default-prompt",
                    name="Default prompt",
                    prompt_text=str(self._raw_config.get("prompt_template", "")).strip(),
                )
            ]
        self._save_prompts()
        self._populate_prompt_combo()
        self._refresh_prompt_preview()

    def _delete_system_prompt(self) -> None:
        prompt = self._selected_system_prompt()
        if prompt is None:
            return

        if prompt.prompt_id == "default-system-prompt" and len(self._system_prompts) == 1:
            showCritical("Create another saved system prompt before deleting the only available system prompt.", parent=self)
            return

        reply = QMessageBox.question(
            self,
            "Delete Saved System Prompt",
            f"Delete the saved system prompt '{prompt.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._system_prompts = [item for item in self._system_prompts if item.prompt_id != prompt.prompt_id]
        if not self._system_prompts:
            self._system_prompts = [
                PromptChoice(
                    prompt_id="default-system-prompt",
                    name="Default system prompt",
                    prompt_text=str(self._raw_config.get("system_prompt", "")).strip(),
                )
            ]
        self._save_system_prompts()
        self._populate_system_prompt_combo()
        self._refresh_system_prompt_preview()

    def _save_prompts(self) -> None:
        self._raw_config["saved_prompts"] = [
            {"id": prompt.prompt_id, "name": prompt.name, "prompt": prompt.prompt_text}
            for prompt in self._prompts
        ]
        save_raw_config(self._raw_config)

    def _save_system_prompts(self) -> None:
        self._raw_config["saved_system_prompts"] = [
            {"id": prompt.prompt_id, "name": prompt.name, "prompt": prompt.prompt_text}
            for prompt in self._system_prompts
        ]
        save_raw_config(self._raw_config)

    def _validate_and_accept(self) -> None:
        is_multi = self.multiple_target_fields_check.isChecked()
        if not is_multi and not self._field_choices:
            showCritical("The selected notes do not share any common target field.", parent=self)
            return
        if is_multi and not self.delimiter_edit.text().strip():
            showCritical("Enter the response delimiter for multiple target field mode.", parent=self)
            return
        if is_multi and self.mode_combo.currentData() == WRITE_MODE_SKIP_NONEMPTY:
            showCritical(
                "Skip-if-not-empty mode is only available for a single target field.",
                parent=self,
            )
            return
        if not (self.model_combo.currentData() or self.model_combo.currentText().strip()):
            showCritical("Choose a model before running.", parent=self)
            return
        if self._selected_system_prompt() is None:
            showCritical("Choose or create a saved system prompt before running.", parent=self)
            return
        if self._selected_prompt() is None:
            showCritical("Choose or create a saved prompt before running.", parent=self)
            return
        if not is_multi and not (self.target_field_combo.currentData() or self.target_field_combo.currentText().strip()):
            showCritical("Choose a target field before running.", parent=self)
            return
        self.accept()


def _prompt_choices_from_saved_prompts(prompts: list[SavedPrompt]) -> list[PromptChoice]:
    return [
        PromptChoice(prompt_id=prompt.prompt_id, name=prompt.name, prompt_text=prompt.prompt_text)
        for prompt in prompts
    ]


def _prompt_choices_from_saved_system_prompts(prompts: list[SavedSystemPrompt]) -> list[PromptChoice]:
    return [
        PromptChoice(prompt_id=prompt.prompt_id, name=prompt.name, prompt_text=prompt.prompt_text)
        for prompt in prompts
    ]


def _preset_choices_from_saved_processing_presets(
    presets: list[ProcessingPreset],
) -> list[ProcessingPresetChoice]:
    return [
        ProcessingPresetChoice(
            preset_id=preset.preset_id,
            name=preset.name,
            prompt_id=preset.prompt_id,
            model=preset.model,
            temperature=preset.temperature,
            system_prompt_id=preset.system_prompt_id,
            target_field=preset.target_field,
            mode=preset.mode,
            multiple_target_fields=preset.multiple_target_fields,
            convert_markdown_to_html=preset.convert_markdown_to_html,
            response_delimiter=preset.response_delimiter,
        )
        for preset in presets
    ]


class SavedPromptDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        *,
        window_title: str,
        prompt_label: str,
        placeholder_text: str,
        help_text: str,
        id_prefix: str,
        prompt: PromptChoice | None = None,
        require_prompt_text: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(window_title)
        self.resize(640, 420)
        self._id_prefix = id_prefix
        self._require_prompt_text = require_prompt_text

        self.name_edit = QLineEdit()
        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setMinimumHeight(220)
        self.prompt_edit.setPlaceholderText(placeholder_text)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("Name", self.name_edit)
        form.addRow(prompt_label, self.prompt_edit)
        layout.addLayout(form)

        help_label = QLabel(help_text)
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if prompt is not None:
            self.name_edit.setText(prompt.name)
            self.prompt_edit.setPlainText(prompt.prompt_text)

    def prompt_choice(self, existing_id: str | None = None) -> PromptChoice | None:
        name = self.name_edit.text().strip()
        prompt_text = self.prompt_edit.toPlainText().strip()
        if not name or (self._require_prompt_text and not prompt_text):
            return None
        return PromptChoice(
            prompt_id=existing_id or new_object_id(self._id_prefix),
            name=name,
            prompt_text=prompt_text,
        )

    def named_item(self, existing_id: str | None = None) -> PromptChoice | None:
        return self.prompt_choice(existing_id=existing_id)

    def _validate_and_accept(self) -> None:
        if not self.name_edit.text().strip():
            showCritical("Prompt name must not be empty.", parent=self)
            return
        if self._require_prompt_text and not self.prompt_edit.toPlainText().strip():
            showCritical("Prompt text must not be empty.", parent=self)
            return
        self.accept()


def _collect_common_fields(note_ids: list[int]) -> tuple[list[str], dict[str, str]]:
    if mw is None or mw.col is None:
        return [], {"note_types": "Unavailable", "status": "Anki collection is not available."}

    field_sets: list[set[str]] = []
    note_types: list[str] = []
    for note_id in note_ids:
        note = mw.col.get_note(note_id)
        if note is None:
            continue
        note_types.append(str(note.note_type()["name"]))
        field_sets.append(set(note.keys()))

    unique_note_types = sorted(set(note_types))
    note_type_text = ", ".join(unique_note_types) if unique_note_types else "Unknown"
    if not field_sets:
        return [], {"note_types": note_type_text, "status": "No notes are available for inspection."}

    common_fields = sorted(set.intersection(*field_sets))
    if common_fields:
        status = f"{len(common_fields)} shared field(s) available across the selected notes."
    else:
        status = "No shared fields were found across the selected note types."
    return common_fields, {"note_types": note_type_text, "status": status}
