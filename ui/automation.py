from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aqt import mw
from aqt.browser import Browser
from aqt.qt import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QInputDialog,
    QPushButton,
    QPlainTextEdit,
    QRadioButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from aqt.utils import showCritical

from ..core.config import (
    ConfigError,
    DEFAULT_PROMPTS_DIR,
    PROMPT_LIBRARY_ROOT,
    ProcessingPreset,
    SavedPrompt,
    SavedSystemPrompt,
    SYSTEM_PROMPTS_DIR,
    USER_PROMPTS_DIR,
    load_config,
    load_raw_config,
    new_object_id,
    save_saved_prompts,
    save_saved_system_prompts,
)
from ..services.model_catalog import fallback_model_options
from ..core.processing import (
    ManualProcessingSpec,
    WRITE_MODE_APPEND,
    WRITE_MODE_OVERWRITE,
    WRITE_MODE_SKIP_NONEMPTY,
    run_manual_ai_processing,
)
from .tooltips import set_hover_help, show_tooltip

DEFAULT_MULTI_FIELD_DELIMITER = "--{field-name}--"


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
    invalid_reason: str | None
    description: str | None
    model: str | None
    temperature: float | None
    system_prompt_id: str | None
    target_field: str
    mode: str
    multiple_target_fields: bool
    convert_markdown_to_html: bool
    convert_field_html_to_markdown: bool
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


def open_browser_settings_dialog(parent: QWidget | None = None) -> None:
    if mw is None:
        return
    try:
        config = load_config()
    except ConfigError as error:
        showCritical(str(error), parent=parent or mw)
        return

    dialog = TransformWithAIDialog(
        parent=parent or mw,
        note_ids=[],
        config=config,
        settings_only=True,
    )
    dialog.exec()


class TransformWithAIDialog(QDialog):
    def __init__(self, parent: QWidget, note_ids: list[int], config, *, settings_only: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle("Browser AI Settings" if settings_only else "Transform with AI")
        self.resize(920, 720)

        self._browser = parent
        self._note_ids = note_ids
        self._config = config
        self._settings_only = settings_only
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
        self.source_fields_label = QLabel()
        self.preset_summary_label = QLabel()
        self.generation_type_group = QButtonGroup(self)
        self.generate_text_radio = QRadioButton("Text")
        self.generate_image_radio = QRadioButton("Image")
        self.generate_audio_radio = QRadioButton("Audio")
        self.model_combo = QComboBox()
        self.use_global_temperature_check = QCheckBox("Use global temperature")
        self.temperature_spin = QDoubleSpinBox()
        self.preset_combo = QComboBox()
        self.multiple_target_fields_check = QCheckBox("Multiple target fields")
        self.convert_markdown_to_html_check = QCheckBox("Convert Markdown to HTML")
        self.convert_markdown_to_html_check.setChecked(True)
        self.convert_field_html_to_markdown_check = QCheckBox("Convert field HTML to Markdown for placeholders")
        self.delimiter_label = QLabel("Response delimiter")
        self.delimiter_edit = QLineEdit()
        self.target_field_combo = QComboBox()
        self.prompt_combo = QComboBox()
        self.prompt_header_label = QLabel("Prompt")
        self.system_prompt_combo = QComboBox()
        self.system_prompt_header_label = QLabel("System prompt")
        self.final_check_summary_label = QLabel()
        self.mode_combo = QComboBox()
        self.prompt_preview = QPlainTextEdit()
        self.prompt_preview.setMinimumHeight(160)
        self.system_prompt_preview = QPlainTextEdit()
        self.system_prompt_preview.setMinimumHeight(140)
        self.pages = QTabWidget()
        self._final_tab_index = -1

        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self._go_to_previous_page)
        self.run_button = QPushButton("Run")
        self.run_button.clicked.connect(self._handle_primary_action)
        self.save_preset_footer_button = QPushButton("Save Current Configuration as Preset")
        self.save_preset_footer_button.clicked.connect(self._save_current_as_preset)
        self.multiple_target_fields_check.toggled.connect(self._refresh_target_mode_ui)
        self.multiple_target_fields_check.toggled.connect(self._refresh_final_check_summary)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        self.use_global_temperature_check.toggled.connect(self._refresh_temperature_ui)
        self.use_global_temperature_check.toggled.connect(self._refresh_final_check_summary)
        self.model_combo.currentIndexChanged.connect(self._refresh_final_check_summary)
        self.temperature_spin.valueChanged.connect(lambda _value: self._refresh_final_check_summary())
        self.target_field_combo.currentIndexChanged.connect(self._refresh_final_check_summary)
        self.mode_combo.currentIndexChanged.connect(self._refresh_final_check_summary)
        self.delimiter_edit.textChanged.connect(self._refresh_final_check_summary)
        self.prompt_combo.currentIndexChanged.connect(self._refresh_final_check_summary)
        self.system_prompt_combo.currentIndexChanged.connect(self._refresh_final_check_summary)
        self.pages.currentChanged.connect(self._refresh_navigation_ui)

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
            convert_field_html_to_markdown=self.convert_field_html_to_markdown_check.isChecked(),
            response_delimiter=self.delimiter_edit.text().strip() or DEFAULT_MULTI_FIELD_DELIMITER,
        )

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)

        intro = QLabel(
            "Manage Browser AI presets, prompts, and run defaults."
            if self._settings_only
            else "Run a saved AI prompt on the selected Browser notes using clear workflow pages for source, target, model, prompt, and system prompt."
        )
        intro.setWordWrap(True)
        root_layout.addWidget(intro)

        self.summary_group = QGroupBox("Selection")
        summary_form = QFormLayout(self.summary_group)
        self.note_count_label.setWordWrap(True)
        self.note_types_label.setWordWrap(True)
        summary_form.addRow("Notes", self.note_count_label)
        summary_form.addRow("Note types", self.note_types_label)
        set_hover_help(self.note_count_label, "How many selected Browser rows resolve to notes that can be processed.", enabled=self._config.show_tooltips)
        set_hover_help(self.note_types_label, "Shared note types across the current selection.", enabled=self._config.show_tooltips)
        root_layout.addWidget(self.summary_group)
        self.summary_group.setVisible(not self._settings_only)

        preset_group = QGroupBox("Preset")
        preset_layout = QVBoxLayout(preset_group)
        preset_picker_row = QWidget()
        preset_picker_layout = QHBoxLayout(preset_picker_row)
        preset_picker_layout.setContentsMargins(0, 0, 0, 0)
        preset_picker_layout.addWidget(self.preset_combo, stretch=1)
        save_preset_button = QPushButton("Save")
        edit_preset_button = QPushButton("Edit")
        update_preset_button = QPushButton("Update")
        delete_preset_button = QPushButton("Delete")
        set_hover_help(self.preset_combo, "Load a saved Browser-processing preset.", enabled=self._config.show_tooltips)
        set_hover_help(save_preset_button, "Save the current run settings as a reusable preset.", enabled=self._config.show_tooltips)
        set_hover_help(edit_preset_button, "Edit the selected preset name and description.", enabled=self._config.show_tooltips)
        set_hover_help(update_preset_button, "Overwrite the selected preset with the current run settings.", enabled=self._config.show_tooltips)
        set_hover_help(delete_preset_button, "Delete the selected preset.", enabled=self._config.show_tooltips)
        save_preset_button.clicked.connect(self._save_current_as_preset)
        edit_preset_button.clicked.connect(self._edit_selected_preset_metadata)
        update_preset_button.clicked.connect(self._update_selected_preset)
        delete_preset_button.clicked.connect(self._delete_selected_preset)
        preset_picker_layout.addWidget(save_preset_button)
        preset_picker_layout.addWidget(edit_preset_button)
        preset_picker_layout.addWidget(update_preset_button)
        preset_picker_layout.addWidget(delete_preset_button)
        preset_layout.addWidget(preset_picker_row)
        self.preset_summary_label.setWordWrap(True)
        self.preset_summary_label.setStyleSheet("color: palette(text);")
        preset_layout.addWidget(self.preset_summary_label)
        root_layout.addWidget(preset_group)

        set_hover_help(self.prompt_combo, "Quickly switch to another prompt in the same folder.", enabled=self._config.show_tooltips)
        set_hover_help(self.system_prompt_combo, "Quickly switch to another system prompt in the same folder.", enabled=self._config.show_tooltips)

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
        set_hover_help(self.convert_field_html_to_markdown_check, "Convert placeholder field contents from HTML to Markdown before sending the prompt to the model.", enabled=self._config.show_tooltips)
        set_hover_help(self.delimiter_edit, f"Delimiter used to split a multi-field response. Leave it blank to use the default format: {DEFAULT_MULTI_FIELD_DELIMITER}.", enabled=self._config.show_tooltips)
        set_hover_help(self.target_field_combo, "Single note field that should receive the generated output when multi-field mode is off.", enabled=self._config.show_tooltips)
        set_hover_help(self.mode_combo, "Choose whether generated text overwrites, appends, or skips already-filled target fields.", enabled=self._config.show_tooltips)
        set_hover_help(self.prompt_preview, "Editable text of the selected user prompt. Use Save Prompt to store changes to the selected prompt.", enabled=self._config.show_tooltips)
        set_hover_help(self.system_prompt_preview, "Editable text of the selected system prompt. Use Save System Prompt to store changes to the selected system prompt.", enabled=self._config.show_tooltips)
        set_hover_help(self.run_button, "Start processing the selected notes with the current settings.", enabled=self._config.show_tooltips)

        self.generation_type_group.addButton(self.generate_text_radio)
        self.generation_type_group.addButton(self.generate_image_radio)
        self.generation_type_group.addButton(self.generate_audio_radio)
        self.generate_text_radio.setChecked(True)
        self.generate_image_radio.setEnabled(False)
        self.generate_audio_radio.setEnabled(False)
        self.generate_text_radio.toggled.connect(self._refresh_final_check_summary)
        self.generate_image_radio.toggled.connect(self._refresh_final_check_summary)
        self.generate_audio_radio.toggled.connect(self._refresh_final_check_summary)
        set_hover_help(self.generate_text_radio, "Generate text updates using prompts and write them back to note fields.", enabled=self._config.show_tooltips)
        set_hover_help(self.generate_image_radio, "Image generation is not wired into this Browser workflow yet.", enabled=self._config.show_tooltips)
        set_hover_help(self.generate_audio_radio, "Audio generation is not wired into this Browser workflow yet.", enabled=self._config.show_tooltips)

        generation_page = QWidget()
        generation_page_layout = QVBoxLayout(generation_page)
        generation_page_layout.setContentsMargins(8, 8, 8, 8)
        generation_page_layout.setSpacing(12)
        generation_page_layout.addWidget(_page_intro(
            "Step 1: Choose what to generate",
            "Start by choosing the output type for this run. Text generation is available in this Browser workflow today. Image and audio generation are shown here as future workflow types but are not selectable yet.",
        ))
        generation_options = QWidget()
        generation_options_layout = QVBoxLayout(generation_options)
        generation_options_layout.setContentsMargins(0, 0, 0, 0)
        generation_options_layout.addWidget(self.generate_text_radio)
        generation_options_layout.addWidget(self.generate_image_radio)
        generation_options_layout.addWidget(self.generate_audio_radio)
        generation_page_layout.addWidget(generation_options)
        generation_note = QLabel("Current Browser processing uses the text workflow below.")
        generation_note.setWordWrap(True)
        generation_note.setStyleSheet("color: palette(text);")
        generation_page_layout.addWidget(generation_note)
        generation_page_layout.addStretch(1)

        self.source_fields_label.setWordWrap(True)
        self.source_fields_label.setStyleSheet("color: palette(text);")

        source_page = QWidget()
        source_page_layout = QVBoxLayout(source_page)
        source_page_layout.setContentsMargins(8, 8, 8, 8)
        source_page_layout.setSpacing(12)
        source_page_layout.addWidget(_page_intro(
            "Step 2: Choose the source text",
            "This add-on builds source text from the fields you reference inside your prompt and system prompt placeholders, for example `{{Front}}`, `{{Back}}`, or `{{Expression}}`. Use this page to see which shared fields are available and how placeholder field HTML should be prepared before sending it to the model.",
        ))
        source_fields_group = QWidget()
        source_fields_layout = QVBoxLayout(source_fields_group)
        source_fields_layout.setContentsMargins(0, 0, 0, 0)
        source_fields_layout.addWidget(self.source_fields_label)
        source_page_layout.addWidget(source_fields_group)
        source_reference_note = QLabel("Reference note fields directly in your prompt text with placeholders like `{{FieldName}}`.")
        source_reference_note.setWordWrap(True)
        source_reference_note.setStyleSheet("color: palette(text);")
        source_fields_layout.addWidget(source_reference_note)
        source_options_group = QWidget()
        source_options_layout = QVBoxLayout(source_options_group)
        source_options_layout.setContentsMargins(0, 0, 0, 0)
        source_options_layout.addWidget(self.convert_field_html_to_markdown_check)
        source_page_layout.addWidget(source_options_group)
        source_page_layout.addStretch(1)

        target_page = QWidget()
        target_page_layout = QVBoxLayout(target_page)
        target_page_layout.setContentsMargins(8, 8, 8, 8)
        target_page_layout.setSpacing(12)
        target_page_layout.addWidget(_page_intro(
            "Step 3: Choose the target field",
            "Pick where the generated result should be written back. You can write to one field, or switch to multi-field output if your prompt returns separate field sections.",
        ))
        target_group = QWidget()
        target_form = QFormLayout(target_group)
        target_form.setContentsMargins(0, 0, 0, 0)
        target_form.addRow("Target field", self.target_field_combo)
        target_form.addRow("Write mode", self.mode_combo)
        target_form.addRow("", self.multiple_target_fields_check)
        self.delimiter_edit.setPlaceholderText(DEFAULT_MULTI_FIELD_DELIMITER)
        target_form.addRow(self.delimiter_label, self.delimiter_edit)
        target_form.addRow("", self.convert_markdown_to_html_check)
        target_page_layout.addWidget(target_group)
        target_page_layout.addStretch(1)

        model_page = QWidget()
        model_page_layout = QVBoxLayout(model_page)
        model_page_layout.setContentsMargins(8, 8, 8, 8)
        model_page_layout.setSpacing(12)
        model_page_layout.addWidget(_page_intro(
            "Step 4: Choose the model",
            "Select which model should handle this run and how much variation you want. Lower temperature is steadier; higher temperature allows more variation.",
        ))
        model_group = QWidget()
        model_form = QFormLayout(model_group)
        model_form.setContentsMargins(0, 0, 0, 0)
        model_form.addRow("Model", self.model_combo)
        temperature_row = QWidget()
        temperature_layout = QHBoxLayout(temperature_row)
        temperature_layout.setContentsMargins(0, 0, 0, 0)
        temperature_layout.addWidget(self.use_global_temperature_check)
        temperature_layout.addWidget(self.temperature_spin)
        model_form.addRow("Temperature", temperature_row)
        model_page_layout.addWidget(model_group)
        model_page_layout.addStretch(1)

        prompt_group = QWidget()
        prompt_group_layout = QVBoxLayout(prompt_group)
        prompt_group_layout.setContentsMargins(0, 0, 0, 0)
        prompt_header = QWidget()
        prompt_header_layout = QHBoxLayout(prompt_header)
        prompt_header_layout.setContentsMargins(0, 0, 0, 0)
        choose_prompt_button = QPushButton("Library")
        rename_prompt_button = QPushButton("Rename")
        new_prompt_button = QPushButton("New")
        delete_prompt_button = QPushButton("Delete")
        save_prompt_button = QPushButton("Save")
        set_hover_help(choose_prompt_button, "Browse the prompt library folders and select a markdown prompt file.", enabled=self._config.show_tooltips)
        set_hover_help(rename_prompt_button, "Rename the selected saved user prompt without changing its prompt text.", enabled=self._config.show_tooltips)
        set_hover_help(new_prompt_button, "Create a new saved user prompt from the text currently shown in the prompt editor.", enabled=self._config.show_tooltips)
        set_hover_help(delete_prompt_button, "Delete the selected saved user prompt.", enabled=self._config.show_tooltips)
        prompt_header_layout.addWidget(self.prompt_header_label)
        prompt_header_layout.addWidget(self.prompt_combo, stretch=1)
        choose_prompt_button.clicked.connect(self._browse_prompt_library)
        rename_prompt_button.clicked.connect(self._rename_prompt)
        new_prompt_button.clicked.connect(self._create_prompt)
        delete_prompt_button.clicked.connect(self._delete_prompt)
        save_prompt_button.clicked.connect(self._save_prompt_preview)
        prompt_header_layout.addWidget(choose_prompt_button)
        prompt_header_layout.addWidget(rename_prompt_button)
        prompt_header_layout.addWidget(new_prompt_button)
        prompt_header_layout.addWidget(delete_prompt_button)
        prompt_header_layout.addWidget(save_prompt_button)
        prompt_group_layout.addWidget(prompt_header)
        prompt_group_layout.addWidget(self.prompt_preview)
        prompt_page = QWidget()
        prompt_page_layout = QVBoxLayout(prompt_page)
        prompt_page_layout.setContentsMargins(8, 8, 8, 8)
        prompt_page_layout.setSpacing(12)
        prompt_page_layout.addWidget(_page_intro(
            "Step 5: Choose the prompt",
            "Edit the user prompt that tells the model what to do with the selected notes. This is where you define the transformation instructions and placeholders like `{{Front}}` or `{{Back}}`.",
        ))
        prompt_page_layout.addWidget(prompt_group)

        system_prompt_group = QWidget()
        system_prompt_group_layout = QVBoxLayout(system_prompt_group)
        system_prompt_group_layout.setContentsMargins(0, 0, 0, 0)
        system_prompt_header = QWidget()
        system_prompt_header_layout = QHBoxLayout(system_prompt_header)
        system_prompt_header_layout.setContentsMargins(0, 0, 0, 0)
        choose_system_prompt_button = QPushButton("Library")
        rename_system_prompt_button = QPushButton("Rename")
        new_system_prompt_button = QPushButton("New")
        delete_system_prompt_button = QPushButton("Delete")
        save_system_prompt_button = QPushButton("Save")
        set_hover_help(choose_system_prompt_button, "Open the system prompt folder and select a markdown prompt file.", enabled=self._config.show_tooltips)
        set_hover_help(rename_system_prompt_button, "Rename the selected saved system prompt without changing its text.", enabled=self._config.show_tooltips)
        set_hover_help(new_system_prompt_button, "Create a new saved system prompt from the text currently shown in the system-prompt editor.", enabled=self._config.show_tooltips)
        set_hover_help(delete_system_prompt_button, "Delete the selected saved system prompt.", enabled=self._config.show_tooltips)
        system_prompt_header_layout.addWidget(self.system_prompt_header_label)
        system_prompt_header_layout.addWidget(self.system_prompt_combo, stretch=1)
        choose_system_prompt_button.clicked.connect(self._browse_system_prompt_library)
        rename_system_prompt_button.clicked.connect(self._rename_system_prompt)
        new_system_prompt_button.clicked.connect(self._create_system_prompt)
        delete_system_prompt_button.clicked.connect(self._delete_system_prompt)
        save_system_prompt_button.clicked.connect(self._save_system_prompt_preview)
        system_prompt_header_layout.addWidget(choose_system_prompt_button)
        system_prompt_header_layout.addWidget(rename_system_prompt_button)
        system_prompt_header_layout.addWidget(new_system_prompt_button)
        system_prompt_header_layout.addWidget(delete_system_prompt_button)
        system_prompt_header_layout.addWidget(save_system_prompt_button)
        system_prompt_group_layout.addWidget(system_prompt_header)
        system_prompt_group_layout.addWidget(self.system_prompt_preview)
        system_prompt_page = QWidget()
        system_prompt_page_layout = QVBoxLayout(system_prompt_page)
        system_prompt_page_layout.setContentsMargins(8, 8, 8, 8)
        system_prompt_page_layout.setSpacing(12)
        system_prompt_page_layout.addWidget(_page_intro(
            "Step 6: Choose the system prompt",
            "Use the system prompt to define the assistant's overall behavior, quality bar, tone, and formatting constraints for this run.",
        ))
        system_prompt_page_layout.addWidget(system_prompt_group)

        self.pages.addTab(generation_page, "Generate")
        self.pages.addTab(source_page, "Source Field")
        self.pages.addTab(target_page, "Target Field")
        self.pages.addTab(model_page, "Model")
        self.pages.addTab(prompt_page, "Prompt")
        self.pages.addTab(system_prompt_page, "System Prompt")
        final_check_page = QWidget()
        final_check_layout = QVBoxLayout(final_check_page)
        final_check_layout.setContentsMargins(8, 8, 8, 8)
        final_check_layout.setSpacing(12)
        final_check_layout.addWidget(_page_intro(
            "Step 7: Final check",
            "Review the sequence of choices below before starting the run. This is the last step in the workflow.",
        ))
        final_check_group = QWidget()
        final_check_group_layout = QVBoxLayout(final_check_group)
        final_check_group_layout.setContentsMargins(0, 0, 0, 0)
        self.final_check_summary_label.setWordWrap(True)
        final_check_group_layout.addWidget(self.final_check_summary_label)
        final_check_layout.addWidget(final_check_group)
        final_check_layout.addStretch(1)
        self._final_tab_index = self.pages.addTab(final_check_page, "Final Check")
        for index, title in enumerate(
            ["Generate", "Source Field", "Target Field", "Model", "Prompt", "System Prompt", "Final Check"],
            start=1,
        ):
            self.pages.setTabText(index - 1, f"{index}. {title}")
        root_layout.addWidget(self.pages, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        if self._settings_only:
            close_button = buttons.addButton("Close", QDialogButtonBox.ButtonRole.AcceptRole)
            close_button.clicked.connect(self.accept)
        else:
            buttons.addButton(self.back_button, QDialogButtonBox.ButtonRole.ActionRole)
            buttons.addButton(self.save_preset_footer_button, QDialogButtonBox.ButtonRole.ActionRole)
            buttons.addButton(self.run_button, QDialogButtonBox.ButtonRole.AcceptRole)
        root_layout.addWidget(buttons)

    def _populate(self) -> None:
        self.note_count_label.setText(str(len(self._note_ids)))
        self.note_types_label.setText(self._field_summary["note_types"])
        self.source_fields_label.setText(", ".join(self._field_choices) if self._field_choices else "No shared fields found across the current selection.")

        self._populate_model_combo()
        self._populate_preset_combo()
        self.target_field_combo.clear()
        for field_name in self._field_choices:
            self.target_field_combo.addItem(field_name, field_name)

        self._populate_prompt_combo()
        self._populate_system_prompt_combo()
        self._refresh_prompt_preview()
        self._refresh_system_prompt_preview()
        self._refresh_preset_summary()
        self._refresh_final_check_summary()
        self._refresh_target_mode_ui()
        self._refresh_temperature_ui()
        self._refresh_navigation_ui()

        has_prompt = bool(self._prompts)
        has_system_prompt = bool(self._system_prompts)
        has_model = self.model_combo.count() > 0
        self.run_button.setEnabled((not self._settings_only) and has_prompt and has_system_prompt and has_model)

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
            label = preset.name if not preset.invalid_reason else f"{preset.name} (missing prompt)"
            self.preset_combo.addItem(label, preset.preset_id)
        if selected_preset_id:
            index = self.preset_combo.findData(selected_preset_id)
            if index >= 0:
                self.preset_combo.setCurrentIndex(index)

    def _populate_prompt_combo(self) -> None:
        selected_prompt_id = self.prompt_combo.currentData()
        selected_prompt = self._prompt_by_id(str(selected_prompt_id or "")) if selected_prompt_id else None
        folder_key = _prompt_folder_key(selected_prompt.prompt_id) if selected_prompt else (
            _prompt_folder_key(self._prompts[0].prompt_id) if self._prompts else ""
        )
        self._populate_prompt_combo_for_folder(folder_key, selected_prompt_id=str(selected_prompt_id or ""))
        self._refresh_prompt_selection_label()

    def _populate_prompt_combo_for_folder(self, folder_key: str, *, selected_prompt_id: str = "") -> None:
        self.prompt_combo.clear()
        for prompt in self._prompts:
            if _prompt_folder_key(prompt.prompt_id) != folder_key:
                continue
            self.prompt_combo.addItem(prompt.name, prompt.prompt_id)
        if selected_prompt_id:
            index = self.prompt_combo.findData(selected_prompt_id)
            if index >= 0:
                self.prompt_combo.setCurrentIndex(index)
        if self.prompt_combo.currentIndex() < 0 and self.prompt_combo.count() > 0:
            self.prompt_combo.setCurrentIndex(0)

    def _selected_prompt(self) -> PromptChoice | None:
        prompt_id = self.prompt_combo.currentData()
        for prompt in self._prompts:
            if prompt.prompt_id == prompt_id:
                return prompt
        return self._prompts[0] if self._prompts else None

    def _populate_system_prompt_combo(self) -> None:
        selected_prompt_id = self.system_prompt_combo.currentData()
        selected_prompt = self._system_prompt_by_id(str(selected_prompt_id or "")) if selected_prompt_id else None
        folder_key = _prompt_folder_key(selected_prompt.prompt_id) if selected_prompt else (
            _prompt_folder_key(self._system_prompts[0].prompt_id) if self._system_prompts else ""
        )
        self._populate_system_prompt_combo_for_folder(folder_key, selected_prompt_id=str(selected_prompt_id or ""))
        self._refresh_system_prompt_selection_label()

    def _populate_system_prompt_combo_for_folder(self, folder_key: str, *, selected_prompt_id: str = "") -> None:
        self.system_prompt_combo.clear()
        for prompt in self._system_prompts:
            if _prompt_folder_key(prompt.prompt_id) != folder_key:
                continue
            self.system_prompt_combo.addItem(prompt.name, prompt.prompt_id)
        if selected_prompt_id:
            index = self.system_prompt_combo.findData(selected_prompt_id)
            if index >= 0:
                self.system_prompt_combo.setCurrentIndex(index)
        if self.system_prompt_combo.currentIndex() < 0 and self.system_prompt_combo.count() > 0:
            self.system_prompt_combo.setCurrentIndex(0)

    def _selected_system_prompt(self) -> PromptChoice | None:
        prompt_id = self.system_prompt_combo.currentData()
        for prompt in self._system_prompts:
            if prompt.prompt_id == prompt_id:
                return prompt
        return self._system_prompts[0] if self._system_prompts else None

    def _prompt_by_id(self, prompt_id: str) -> PromptChoice | None:
        for prompt in self._prompts:
            if prompt.prompt_id == prompt_id:
                return prompt
        return None

    def _system_prompt_by_id(self, prompt_id: str) -> PromptChoice | None:
        for prompt in self._system_prompts:
            if prompt.prompt_id == prompt_id:
                return prompt
        return None

    def _refresh_prompt_preview(self) -> None:
        prompt = self._selected_prompt()
        self.prompt_preview.blockSignals(True)
        self.prompt_preview.setPlainText(prompt.prompt_text if prompt else "")
        self.prompt_preview.blockSignals(False)
        self._refresh_prompt_selection_label()

    def _refresh_system_prompt_preview(self) -> None:
        prompt = self._selected_system_prompt()
        self.system_prompt_preview.blockSignals(True)
        self.system_prompt_preview.setPlainText(prompt.prompt_text if prompt else "")
        self.system_prompt_preview.blockSignals(False)
        self._refresh_system_prompt_selection_label()

    def _is_default_prompt(self, prompt_id: str) -> bool:
        return (DEFAULT_PROMPTS_DIR / f"{prompt_id}.md").exists()

    def _forked_prompt_name(self, base_name: str) -> str:
        existing_names = {prompt.name for prompt in self._prompts}
        suffix = new_object_id("prompt").split("-", 1)[-1]
        candidate = f"{base_name} ({suffix})"
        counter = 2
        while candidate in existing_names:
            candidate = f"{base_name} ({suffix}-{counter})"
            counter += 1
        return candidate

    def _save_prompt_preview(self) -> bool:
        prompt = self._selected_prompt()
        if prompt is None:
            showCritical("Choose a saved prompt before saving.", parent=self)
            return False
        updated_text = self.prompt_preview.toPlainText().strip()
        if not updated_text:
            showCritical("Prompt text must not be empty.", parent=self)
            return False
        if updated_text == prompt.prompt_text:
            return True
        if self._is_default_prompt(prompt.prompt_id) and updated_text != prompt.prompt_text:
            replacement = PromptChoice(
                prompt_id=new_object_id("prompt"),
                name=self._forked_prompt_name(prompt.name),
                prompt_text=updated_text,
            )
            self._prompts.append(replacement)
            self._save_prompts()
            self._populate_prompt_combo()
            index = self.prompt_combo.findData(replacement.prompt_id)
            if index >= 0:
                self.prompt_combo.setCurrentIndex(index)
            self._refresh_prompt_preview()
            show_tooltip(f"Saved as new user prompt '{replacement.name}'.", parent=self)
            return True
        for index, current in enumerate(self._prompts):
            if current.prompt_id == prompt.prompt_id:
                self._prompts[index] = PromptChoice(
                    prompt_id=current.prompt_id,
                    name=current.name,
                    prompt_text=updated_text,
                )
                self._save_prompts()
                self._populate_prompt_combo()
                combo_index = self.prompt_combo.findData(current.prompt_id)
                if combo_index >= 0:
                    self.prompt_combo.setCurrentIndex(combo_index)
                self._refresh_prompt_preview()
                show_tooltip(f"Saved prompt '{current.name}'.", parent=self)
                return True
        return False

    def _save_system_prompt_preview(self) -> bool:
        prompt = self._selected_system_prompt()
        if prompt is None:
            showCritical("Choose a saved system prompt before saving.", parent=self)
            return False
        updated_text = self.system_prompt_preview.toPlainText().strip()
        if not updated_text:
            showCritical("System prompt text must not be empty.", parent=self)
            return False
        for index, current in enumerate(self._system_prompts):
            if current.prompt_id == prompt.prompt_id:
                if updated_text == current.prompt_text:
                    return True
                self._system_prompts[index] = PromptChoice(
                    prompt_id=current.prompt_id,
                    name=current.name,
                    prompt_text=updated_text,
                )
                self._save_system_prompts()
                self._populate_system_prompt_combo()
                combo_index = self.system_prompt_combo.findData(current.prompt_id)
                if combo_index >= 0:
                    self.system_prompt_combo.setCurrentIndex(combo_index)
                self._refresh_system_prompt_preview()
                show_tooltip(f"Saved system prompt '{current.name}'.", parent=self)
                return True
        return False

    def _refresh_target_mode_ui(self) -> None:
        is_multi = self.multiple_target_fields_check.isChecked()
        self.target_field_combo.setEnabled(not is_multi)
        self.delimiter_label.setVisible(is_multi)
        self.delimiter_edit.setVisible(is_multi)
        if is_multi and self.mode_combo.currentData() == WRITE_MODE_SKIP_NONEMPTY:
            self._set_combo_to_data(self.mode_combo, WRITE_MODE_OVERWRITE)

    def _refresh_temperature_ui(self) -> None:
        self.temperature_spin.setEnabled(not self.use_global_temperature_check.isChecked())

    def _refresh_navigation_ui(self) -> None:
        if self._settings_only:
            return
        current_index = self.pages.currentIndex()
        on_final_page = self.pages.currentIndex() == self._final_tab_index
        self.back_button.setEnabled(current_index > 0)
        self.run_button.setText("Run" if on_final_page else "Next")
        self.save_preset_footer_button.setVisible(on_final_page)

    def _go_to_previous_page(self) -> None:
        previous_index = max(self.pages.currentIndex() - 1, 0)
        self.pages.setCurrentIndex(previous_index)

    def _handle_primary_action(self) -> None:
        if self.pages.currentIndex() != self._final_tab_index:
            next_index = min(self.pages.currentIndex() + 1, self.pages.count() - 1)
            self.pages.setCurrentIndex(next_index)
            return
        self._validate_and_accept()

    def _refresh_final_check_summary(self) -> None:
        generation_type = "Text"
        if self.generate_image_radio.isChecked():
            generation_type = "Image"
        elif self.generate_audio_radio.isChecked():
            generation_type = "Audio"
        target_mode = "Multiple fields" if self.multiple_target_fields_check.isChecked() else (
            self.target_field_combo.currentData() or self.target_field_combo.currentText().strip() or "Not selected"
        )
        prompt = self._selected_prompt()
        system_prompt = self._selected_system_prompt()
        model = self.model_combo.currentData() or self.model_combo.currentText().strip() or "Not selected"
        temperature = "Global default" if self.use_global_temperature_check.isChecked() else str(self.temperature_spin.value())
        delimiter = self.delimiter_edit.text().strip() or DEFAULT_MULTI_FIELD_DELIMITER
        source_fields = ", ".join(self._field_choices) if self._field_choices else "No shared fields"
        summary = (
            f"<b>1. Generate:</b> {generation_type}<br>"
            f"<b>2. Source fields:</b> {source_fields}<br>"
            f"<b>3. Target:</b> {target_mode}<br>"
            f"<b>4. Model:</b> {model} (Temperature: {temperature})<br>"
            f"<b>5. Prompt:</b> {prompt.name if prompt else 'Not selected'}<br>"
            f"<b>6. System prompt:</b> {system_prompt.name if system_prompt else 'Not selected'}"
        )
        if self.multiple_target_fields_check.isChecked():
            summary += f"<br><b>Multi-field delimiter:</b> {delimiter}"
        self.final_check_summary_label.setText(summary)

    def _refresh_preset_summary(self) -> None:
        preset = self._selected_preset()
        if preset is None:
            self.preset_summary_label.setText("No preset selected. Pick one, or configure the sections below and save a new preset.")
            return
        details: list[str] = []
        if preset.description:
            details.append(preset.description.strip())
        if preset.invalid_reason:
            details.append(f"Unavailable: {preset.invalid_reason}")
        else:
            if preset.target_field:
                details.append(f"Target: {preset.target_field}")
            elif preset.multiple_target_fields:
                details.append("Target: multiple fields")
            prompt = self._prompt_by_id(preset.prompt_id)
            if prompt is not None:
                details.append(f"Prompt: {prompt.name}")
            system_prompt = self._system_prompt_by_id(preset.system_prompt_id or "")
            if system_prompt is not None:
                details.append(f"System: {system_prompt.name}")
        self.preset_summary_label.setText(" | ".join(details) if details else "Preset selected.")

    def _selected_preset(self) -> ProcessingPresetChoice | None:
        preset_id = self.preset_combo.currentData()
        for preset in self._presets:
            if preset.preset_id == preset_id:
                return preset
        return None

    def _on_preset_changed(self) -> None:
        preset = self._selected_preset()
        self._refresh_preset_summary()
        if preset is None:
            return
        self._apply_preset(preset)

    def _apply_preset(self, preset: ProcessingPresetChoice) -> None:
        if preset.invalid_reason:
            return
        self._set_combo_to_data(self.model_combo, preset.model)
        self._set_combo_to_data(self.prompt_combo, preset.prompt_id)
        self._set_combo_to_data(self.system_prompt_combo, preset.system_prompt_id)
        self._set_combo_to_data(self.mode_combo, preset.mode)
        self._set_temperature(preset.temperature)
        self.multiple_target_fields_check.setChecked(preset.multiple_target_fields)
        self.convert_markdown_to_html_check.setChecked(preset.convert_markdown_to_html)
        self.convert_field_html_to_markdown_check.setChecked(preset.convert_field_html_to_markdown)
        self.delimiter_edit.setText(preset.response_delimiter or "")
        if preset.target_field:
            self._set_target_field(preset.target_field)
        self._refresh_prompt_preview()
        self._refresh_system_prompt_preview()
        self._refresh_target_mode_ui()
        self._refresh_preset_summary()

    def _browse_prompt_library(self) -> None:
        selected = _choose_prompt_from_library(
            self,
            prompts=self._prompts,
            current_prompt_id=str(self.prompt_combo.currentData() or ""),
        )
        if selected is None:
            return
        self._set_combo_to_data(self.prompt_combo, selected.prompt_id)
        self._refresh_prompt_preview()

    def _browse_system_prompt_library(self) -> None:
        selected = _choose_system_prompt_from_library(
            self,
            prompts=self._system_prompts,
            current_prompt_id=str(self.system_prompt_combo.currentData() or ""),
        )
        if selected is None:
            return
        self._set_combo_to_data(self.system_prompt_combo, selected.prompt_id)
        self._refresh_system_prompt_preview()

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
            invalid_reason=None,
            description=choice.prompt_text or None,
            model=str(self.model_combo.currentData() or self.model_combo.currentText().strip()) or None,
            temperature=self._selected_temperature(),
            system_prompt_id=str(self.system_prompt_combo.currentData() or "") or None,
            target_field="" if self.multiple_target_fields_check.isChecked() else str(target_field or ""),
            mode=str(self.mode_combo.currentData() or WRITE_MODE_OVERWRITE),
            multiple_target_fields=self.multiple_target_fields_check.isChecked(),
            convert_markdown_to_html=self.convert_markdown_to_html_check.isChecked(),
            convert_field_html_to_markdown=self.convert_field_html_to_markdown_check.isChecked(),
            response_delimiter=self.delimiter_edit.text().strip() or None,
        )
        self._presets.append(preset)
        self._save_processing_presets()
        self._populate_preset_combo()
        index = self.preset_combo.findData(preset.preset_id)
        if index >= 0:
            self.preset_combo.setCurrentIndex(index)

    def _edit_selected_preset_metadata(self) -> None:
        preset = self._selected_preset()
        if preset is None:
            show_tooltip("Choose a preset to edit.", parent=self)
            return

        dialog = SavedPromptDialog(
            parent=self,
            prompt=PromptChoice(
                prompt_id=preset.preset_id,
                name=preset.name,
                prompt_text=preset.description or "",
            ),
            window_title="Processing Preset",
            prompt_label="Description",
            placeholder_text="Optional notes about this preset",
            help_text="Edit the selected preset name and description without changing its processing settings.",
            id_prefix="processing-preset",
            require_prompt_text=False,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        choice = dialog.named_item(existing_id=preset.preset_id)
        if choice is None:
            return

        for index, current in enumerate(self._presets):
            if current.preset_id == preset.preset_id:
                self._presets[index] = ProcessingPresetChoice(
                    preset_id=current.preset_id,
                    name=choice.name,
                    prompt_id=current.prompt_id,
                    invalid_reason=current.invalid_reason,
                    description=choice.prompt_text or None,
                    model=current.model,
                    temperature=current.temperature,
                    system_prompt_id=current.system_prompt_id,
                    target_field=current.target_field,
                    mode=current.mode,
                    multiple_target_fields=current.multiple_target_fields,
                    convert_markdown_to_html=current.convert_markdown_to_html,
                    convert_field_html_to_markdown=current.convert_field_html_to_markdown,
                    response_delimiter=current.response_delimiter,
                )
                break
        self._save_processing_presets()
        self._populate_preset_combo()
        index = self.preset_combo.findData(preset.preset_id)
        if index >= 0:
            self.preset_combo.setCurrentIndex(index)
        show_tooltip(f"Updated preset details for '{choice.name}'.", parent=self)

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
                "description": preset.description,
                "prompt_id": preset.prompt_id,
                "model": preset.model,
                "temperature": preset.temperature,
                "system_prompt_id": preset.system_prompt_id,
                "target_field": preset.target_field,
                "mode": preset.mode,
                "multiple_target_fields": preset.multiple_target_fields,
                "convert_markdown_to_html": preset.convert_markdown_to_html,
                "convert_field_html_to_markdown": preset.convert_field_html_to_markdown,
                "response_delimiter": preset.response_delimiter,
            }
            for preset in self._presets
        ]
        save_raw_config(self._raw_config)

    def _current_preset_choice(self, *, preset_id: str, name: str) -> ProcessingPresetChoice:
        target_field = self.target_field_combo.currentData() or self.target_field_combo.currentText().strip()
        existing_preset = self._selected_preset()
        return ProcessingPresetChoice(
            preset_id=preset_id,
            name=name,
            prompt_id=str(self.prompt_combo.currentData() or ""),
            invalid_reason=None,
            description=existing_preset.description if existing_preset is not None and existing_preset.preset_id == preset_id else None,
            model=str(self.model_combo.currentData() or self.model_combo.currentText().strip()) or None,
            temperature=self._selected_temperature(),
            system_prompt_id=str(self.system_prompt_combo.currentData() or "") or None,
            target_field="" if self.multiple_target_fields_check.isChecked() else str(target_field or ""),
            mode=str(self.mode_combo.currentData() or WRITE_MODE_OVERWRITE),
            multiple_target_fields=self.multiple_target_fields_check.isChecked(),
            convert_markdown_to_html=self.convert_markdown_to_html_check.isChecked(),
            convert_field_html_to_markdown=self.convert_field_html_to_markdown_check.isChecked(),
            response_delimiter=self.delimiter_edit.text().strip() or None,
        )

    def _set_combo_to_data(self, combo: QComboBox, value: str | None) -> None:
        lookup = value or ""
        if combo is self.prompt_combo:
            prompt = self._prompt_by_id(lookup)
            if prompt is not None:
                self._populate_prompt_combo_for_folder(_prompt_folder_key(prompt.prompt_id), selected_prompt_id=lookup)
                return
        if combo is self.system_prompt_combo:
            prompt = self._system_prompt_by_id(lookup)
            if prompt is not None:
                self._populate_system_prompt_combo_for_folder(_prompt_folder_key(prompt.prompt_id), selected_prompt_id=lookup)
                return
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
        prompt_text = self.prompt_preview.toPlainText().strip()
        if not prompt_text:
            showCritical("Prompt text must not be empty.", parent=self)
            return
        current_prompt = self._selected_prompt()
        suggested_name = current_prompt.name if current_prompt is not None else "New prompt"
        name, accepted = QInputDialog.getText(
            self,
            "New Prompt",
            "Save the current prompt as a new prompt.\n\nName",
            text=suggested_name,
        )
        if not accepted or not name.strip():
            return
        choice = PromptChoice(
            prompt_id=new_object_id("prompt"),
            name=name.strip(),
            prompt_text=prompt_text,
        )
        self._prompts.append(choice)
        self._save_prompts()
        self._populate_prompt_combo()
        index = self.prompt_combo.findData(choice.prompt_id)
        if index >= 0:
            self.prompt_combo.setCurrentIndex(index)
        self._refresh_prompt_preview()
        show_tooltip(f"Created prompt '{choice.name}'.", parent=self)

    def _rename_prompt(self) -> None:
        prompt = self._selected_prompt()
        if prompt is None:
            return
        name, accepted = QInputDialog.getText(
            self,
            "Rename Prompt",
            "Name",
            text=prompt.name,
        )
        if not accepted or not name.strip():
            return
        replacement = PromptChoice(
            prompt_id=prompt.prompt_id,
            name=name.strip(),
            prompt_text=prompt.prompt_text,
        )
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
        show_tooltip(f"Renamed prompt to '{replacement.name}'.", parent=self)

    def _create_system_prompt(self) -> None:
        prompt_text = self.system_prompt_preview.toPlainText().strip()
        if not prompt_text:
            showCritical("System prompt text must not be empty.", parent=self)
            return
        current_prompt = self._selected_system_prompt()
        suggested_name = current_prompt.name if current_prompt is not None else "New system prompt"
        name, accepted = QInputDialog.getText(
            self,
            "New System Prompt",
            "Save the current system prompt as a new prompt.\n\nName",
            text=suggested_name,
        )
        if not accepted or not name.strip():
            return
        choice = PromptChoice(
            prompt_id=new_object_id("system-prompt"),
            name=name.strip(),
            prompt_text=prompt_text,
        )
        self._system_prompts.append(choice)
        self._save_system_prompts()
        self._populate_system_prompt_combo()
        index = self.system_prompt_combo.findData(choice.prompt_id)
        if index >= 0:
            self.system_prompt_combo.setCurrentIndex(index)
        self._refresh_system_prompt_preview()
        show_tooltip(f"Created system prompt '{choice.name}'.", parent=self)

    def _rename_system_prompt(self) -> None:
        prompt = self._selected_system_prompt()
        if prompt is None:
            return
        name, accepted = QInputDialog.getText(
            self,
            "Rename System Prompt",
            "Name",
            text=prompt.name,
        )
        if not accepted or not name.strip():
            return
        replacement = PromptChoice(
            prompt_id=prompt.prompt_id,
            name=name.strip(),
            prompt_text=prompt.prompt_text,
        )
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
        show_tooltip(f"Renamed system prompt to '{replacement.name}'.", parent=self)

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
                    prompt_id="general/default-prompt",
                    name="Default prompt",
                    prompt_text="",
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
                    prompt_text="",
                )
            ]
        self._save_system_prompts()
        self._populate_system_prompt_combo()
        self._refresh_system_prompt_preview()

    def _save_prompts(self) -> None:
        save_saved_prompts(self._raw_config, self._prompts)

    def _save_system_prompts(self) -> None:
        save_saved_system_prompts(self._raw_config, self._system_prompts)

    def _refresh_prompt_selection_label(self) -> None:
        prompt = self._selected_prompt()
        if prompt is None:
            self.prompt_header_label.setText("Prompt")
            return
        self.prompt_header_label.setText(f"Prompt: {prompt.name}")

    def _refresh_system_prompt_selection_label(self) -> None:
        prompt = self._selected_system_prompt()
        if prompt is None:
            self.system_prompt_header_label.setText("System prompt")
            return
        self.system_prompt_header_label.setText(f"System prompt: {prompt.name}")

    def _validate_and_accept(self) -> None:
        selected_preset = self._selected_preset()
        if selected_preset is not None and selected_preset.invalid_reason:
            showCritical(
                f"Cannot run preset '{selected_preset.name}'. {selected_preset.invalid_reason}",
                parent=self,
            )
            return
        if not self._save_prompt_preview():
            return
        if not self._save_system_prompt_preview():
            return
        is_multi = self.multiple_target_fields_check.isChecked()
        if not is_multi and not self._field_choices:
            showCritical("The selected notes do not share any common target field.", parent=self)
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
            description=preset.description,
            prompt_id=preset.prompt_id,
            invalid_reason=preset.invalid_reason,
            model=preset.model,
            temperature=preset.temperature,
            system_prompt_id=preset.system_prompt_id,
            target_field=preset.target_field,
            mode=preset.mode,
            multiple_target_fields=preset.multiple_target_fields,
            convert_markdown_to_html=preset.convert_markdown_to_html,
            convert_field_html_to_markdown=preset.convert_field_html_to_markdown,
            response_delimiter=preset.response_delimiter,
        )
        for preset in presets
    ]


def _page_intro(title: str, description: str) -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    title_label = QLabel(title)
    title_label.setStyleSheet("font-weight: 600;")
    description_label = QLabel(description)
    description_label.setWordWrap(True)
    description_label.setStyleSheet("color: palette(text);")
    layout.addWidget(title_label)
    layout.addWidget(description_label)
    return container


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
        self.name_edit.setMinimumWidth(760)
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


def _choose_prompt_from_library(
    parent: QWidget,
    *,
    prompts: list[PromptChoice],
    current_prompt_id: str,
) -> PromptChoice | None:
    start_directory = _prompt_start_directory(current_prompt_id)
    selected_path, _ = QFileDialog.getOpenFileName(
        parent,
        "Choose Prompt from Library",
        str(start_directory),
        "Markdown files (*.md)",
    )
    if not selected_path:
        return None
    prompt_id = _prompt_id_from_library_path(Path(selected_path))
    if not prompt_id:
        showCritical(
            "Choose a markdown file inside prompt_library/default_prompts or prompt_library/user_prompts.",
            parent=parent,
        )
        return None
    for prompt in prompts:
        if prompt.prompt_id == prompt_id:
            return prompt
    showCritical("The selected prompt file is not loaded. Reopen the dialog if you recently added it.", parent=parent)
    return None


def _choose_system_prompt_from_library(
    parent: QWidget,
    *,
    prompts: list[PromptChoice],
    current_prompt_id: str,
) -> PromptChoice | None:
    start_directory = _system_prompt_start_directory(current_prompt_id)
    selected_path, _ = QFileDialog.getOpenFileName(
        parent,
        "Choose System Prompt",
        str(start_directory),
        "Markdown files (*.md)",
    )
    if not selected_path:
        return None
    prompt_id = _system_prompt_id_from_library_path(Path(selected_path))
    if not prompt_id:
        showCritical(
            "Choose a markdown file inside prompt_library/system_prompts.",
            parent=parent,
        )
        return None
    for prompt in prompts:
        if prompt.prompt_id == prompt_id:
            return prompt
    showCritical("The selected system prompt file is not loaded. Reopen the dialog if you recently added it.", parent=parent)
    return None


def _prompt_start_directory(current_prompt_id: str) -> Path:
    current_path = _prompt_file_path(current_prompt_id)
    if current_path is not None:
        return current_path.parent
    return PROMPT_LIBRARY_ROOT


def _prompt_file_path(prompt_id: str) -> Path | None:
    parts = [part for part in prompt_id.replace("\\", "/").split("/") if part]
    if not parts:
        return None
    relative_path = Path(*parts).with_suffix(".md")
    for root in (USER_PROMPTS_DIR, DEFAULT_PROMPTS_DIR):
        candidate = root / relative_path
        if candidate.exists():
            return candidate
    return None


def _prompt_id_from_library_path(path: Path) -> str | None:
    resolved_path = path.resolve()
    for root in (USER_PROMPTS_DIR, DEFAULT_PROMPTS_DIR):
        try:
            relative_path = resolved_path.relative_to(root.resolve())
        except ValueError:
            continue
        return relative_path.with_suffix("").as_posix()
    return None


def _system_prompt_start_directory(current_prompt_id: str) -> Path:
    current_path = _system_prompt_file_path(current_prompt_id)
    if current_path is not None:
        return current_path.parent
    return SYSTEM_PROMPTS_DIR


def _system_prompt_file_path(prompt_id: str) -> Path | None:
    parts = [part for part in prompt_id.replace("\\", "/").split("/") if part]
    if not parts:
        return None
    candidate = SYSTEM_PROMPTS_DIR.joinpath(*parts).with_suffix(".md")
    if candidate.exists():
        return candidate
    return None


def _system_prompt_id_from_library_path(path: Path) -> str | None:
    resolved_path = path.resolve()
    try:
        relative_path = resolved_path.relative_to(SYSTEM_PROMPTS_DIR.resolve())
    except ValueError:
        return None
    return relative_path.with_suffix("").as_posix()


def _prompt_folder_key(prompt_id: str) -> str:
    path = Path(prompt_id.replace("\\", "/"))
    parent = path.parent.as_posix()
    return "" if parent == "." else parent


def _prompt_relative_path_label(prompt_id: str) -> str:
    return f"{prompt_id}.md"


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
