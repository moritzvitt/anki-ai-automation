from __future__ import annotations

from dataclasses import dataclass

from aqt import mw
from aqt.qt import (
    Qt,
    QAbstractScrollArea,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTimer,
    QVBoxLayout,
    QWidget,
)
from aqt.utils import showCritical

from .automation import (
    ProcessingPresetChoice,
    PromptChoice,
    SavedPromptDialog,
    _preset_choices_from_saved_processing_presets,
)
from .tooltips import set_hover_help, show_tooltip
from ..core.audit_prompts import AUDIT_SCHEMA_PRESET_MLR, available_audit_schema_presets
from ..core.config import (
    ProcessingPreset,
    Workflow,
    WorkflowGroup,
    load_config,
    load_raw_config,
    new_object_id,
    save_raw_config,
    save_saved_prompts,
)
from ..core.processing import (
    WRITE_MODE_APPEND,
    WRITE_MODE_OVERWRITE,
    WRITE_MODE_SKIP_NONEMPTY,
)
from ..services.model_catalog import fallback_model_options


@dataclass(frozen=True)
class WorkflowDraft:
    name: str
    query: str
    workflow_type: str
    enabled: bool
    prompt_id: str
    target_field: str
    mode: str
    model: str | None
    temperature: float | None
    api_mode: str | None
    system_prompt_id: str | None
    multiple_target_fields: bool
    convert_markdown_to_html: bool
    response_delimiter: str | None
    schema_preset: str | None
    success_tags: list[str] | None
    failure_tags: list[str] | None
    trigger_on_startup: bool
    trigger_on_periodic: bool
    trigger_min_matches: int
    group_names: list[str]

class WorkflowDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        *,
        prompts: list[PromptChoice],
        system_prompts: list[PromptChoice],
        groups: list[WorkflowGroup],
        current_model: str,
        model_pricing: dict,
        workflow: Workflow | None = None,
        current_group_names: list[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Workflow")
        self.resize(1440, 840)

        self._raw_config = load_raw_config()
        self._prompts = list(prompts)
        self._system_prompts = list(system_prompts)
        loaded_presets = load_config().processing_presets
        self._presets = _preset_choices_from_saved_processing_presets(loaded_presets)
        self._groups = list(groups)
        self._current_group_names = current_group_names or []
        self._current_model = current_model
        self._show_tooltips = load_config().show_tooltips
        self._model_options = fallback_model_options(
            current_model=current_model,
            pricing_overrides=model_pricing,
        )

        self.name_edit = QLineEdit()
        self.query_edit = QLineEdit()
        self.query_count_label = QLabel("Click Refresh Count to check the query.")
        self.workflow_type_combo = QComboBox()
        self.enabled_check = QCheckBox("Enabled")
        self.model_combo = QComboBox()
        self.api_mode_combo = QComboBox()
        self.use_global_temperature_check = QCheckBox("Use global temperature")
        self.temperature_spin = QDoubleSpinBox()
        self.preset_combo = QComboBox()
        self.success_tags_edit = QLineEdit()
        self.failure_tags_edit = QLineEdit()
        self.prompt_combo = QComboBox()
        self.system_prompt_combo = QComboBox()
        self.prompt_preview = QPlainTextEdit()
        self.prompt_preview.setMinimumHeight(140)
        self.system_prompt_preview = QPlainTextEdit()
        self.system_prompt_preview.setMinimumHeight(120)
        self.multiple_target_fields_check = QCheckBox("Multiple target fields")
        self.convert_markdown_to_html_check = QCheckBox("Convert Markdown to HTML")
        self.convert_markdown_to_html_check.setChecked(True)
        self.delimiter_edit = QLineEdit()
        self.target_field_combo = QComboBox()
        self.target_field_combo.setEditable(True)
        self.mode_combo = QComboBox()
        self.schema_preset_combo = QComboBox()
        self.trigger_on_startup_check = QCheckBox("Run automatically on startup")
        self.trigger_on_periodic_check = QCheckBox("Run automatically when the condition becomes true")
        self.trigger_min_matches_spin = QSpinBox()
        self.group_edit = QLineEdit()
        self.preset_group: QWidget | None = None
        self.prompt_group: QWidget | None = None
        self._scroll_area: QScrollArea | None = None
        self._scroll_content: QWidget | None = None
        self._buttons_box: QDialogButtonBox | None = None
        self._preset_form: QFormLayout | None = None
        self._preset_row: QWidget | None = None
        self._preset_group_toggle: QPushButton | None = None

        self._build_ui()
        self._populate(workflow)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        content = QWidget()
        scroll_area.setWidget(content)
        self._scroll_area = scroll_area
        self._scroll_content = content
        content_layout = QVBoxLayout(content)
        form = QFormLayout()

        self.query_edit.setMinimumWidth(760)
        self.name_edit.setMinimumWidth(760)
        set_hover_help(self.name_edit, "Friendly workflow name shown in the manager and run confirmations.", enabled=self._show_tooltips)
        set_hover_help(self.query_edit, "Anki Browser search query used to find notes for this workflow.", enabled=self._show_tooltips)
        set_hover_help(self.query_count_label, "Shows how many notes currently match the workflow query.", enabled=self._show_tooltips)
        set_hover_help(self.workflow_type_combo, "Atomic workflow behavior type. Field update writes note fields, while audit validates structured output and applies tags/metadata.", enabled=self._show_tooltips)
        set_hover_help(self.enabled_check, "Disabled workflows stay in the registry but are skipped in normal manual/group runs.", enabled=self._show_tooltips)

        prompt_row = QWidget()
        prompt_layout = QHBoxLayout(prompt_row)
        prompt_layout.setContentsMargins(0, 0, 0, 0)
        prompt_layout.addWidget(self.prompt_combo, stretch=1)
        new_button = QPushButton("New")
        edit_button = QPushButton("Edit")
        delete_button = QPushButton("Delete")
        set_hover_help(self.prompt_combo, "Choose the saved user prompt for this workflow.", enabled=self._show_tooltips)
        set_hover_help(new_button, "Create a new saved user prompt.", enabled=self._show_tooltips)
        set_hover_help(edit_button, "Edit the selected saved user prompt.", enabled=self._show_tooltips)
        set_hover_help(delete_button, "Delete the selected saved user prompt.", enabled=self._show_tooltips)
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
        set_hover_help(self.system_prompt_combo, "Choose the saved system prompt for this workflow.", enabled=self._show_tooltips)
        set_hover_help(new_system_button, "Create a new saved system prompt.", enabled=self._show_tooltips)
        set_hover_help(edit_system_button, "Edit the selected saved system prompt.", enabled=self._show_tooltips)
        set_hover_help(delete_system_button, "Delete the selected saved system prompt.", enabled=self._show_tooltips)
        new_system_button.clicked.connect(self._create_system_prompt)
        edit_system_button.clicked.connect(self._edit_system_prompt)
        delete_system_button.clicked.connect(self._delete_system_prompt)
        system_prompt_layout.addWidget(new_system_button)
        system_prompt_layout.addWidget(edit_system_button)
        system_prompt_layout.addWidget(delete_system_button)

        query_row = QWidget()
        query_layout = QVBoxLayout(query_row)
        query_layout.setContentsMargins(0, 0, 0, 0)
        query_layout.addWidget(self.query_edit)
        refresh_row = QHBoxLayout()
        refresh_row.setContentsMargins(0, 0, 0, 0)
        refresh_button = QPushButton("Refresh Count")
        set_hover_help(refresh_button, "Run the Anki search query now and show the current match count.", enabled=self._show_tooltips)
        refresh_button.clicked.connect(self._refresh_query_count)
        refresh_row.addWidget(refresh_button)
        refresh_row.addWidget(self.query_count_label, stretch=1)
        query_layout.addLayout(refresh_row)

        self._populate_model_combo()
        self.workflow_type_combo.addItem("Field update", "field_update")
        self.workflow_type_combo.addItem("Audit", "audit")
        self.api_mode_combo.addItem("Global default", "global_default")
        self.api_mode_combo.addItem("Responses API", "responses")
        self.api_mode_combo.addItem("Chat Completions API", "chat_completions")
        for preset in available_audit_schema_presets():
            self.schema_preset_combo.addItem(preset.name, preset.preset_id)
        self.workflow_type_combo.currentIndexChanged.connect(self._refresh_workflow_type_ui)
        self._populate_preset_combo()
        self.mode_combo.addItem("Overwrite target field", WRITE_MODE_OVERWRITE)
        self.mode_combo.addItem("Append to target field", WRITE_MODE_APPEND)
        self.mode_combo.addItem("Skip if target field not empty", WRITE_MODE_SKIP_NONEMPTY)
        self.multiple_target_fields_check.toggled.connect(self._refresh_target_mode_ui)
        self.use_global_temperature_check.toggled.connect(self._refresh_temperature_ui)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        self.prompt_combo.currentIndexChanged.connect(self._refresh_prompt_preview)
        self.system_prompt_combo.currentIndexChanged.connect(self._refresh_system_prompt_preview)
        self.prompt_preview.textChanged.connect(self._sync_prompt_from_editor)
        self.system_prompt_preview.textChanged.connect(self._sync_system_prompt_from_editor)
        self.delimiter_edit.setPlaceholderText("--Notes-- or --{field}--")
        self.temperature_spin.setDecimals(2)
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.1)
        self.temperature_spin.setValue(0.2)
        self.use_global_temperature_check.setChecked(True)
        self.trigger_min_matches_spin.setRange(1, 1_000_000)
        self.trigger_min_matches_spin.setValue(1)

        form.addRow("Name", self.name_edit)
        form.addRow("Query", query_row)
        form.addRow("Workflow type", self.workflow_type_combo)
        form.addRow("", self.enabled_check)

        preset_row = QWidget()
        self._preset_row = preset_row
        preset_layout = QHBoxLayout(preset_row)
        preset_layout.setContentsMargins(0, 0, 0, 0)
        preset_layout.addWidget(self.preset_combo, stretch=1)
        save_preset_button = QPushButton("Save")
        edit_preset_button = QPushButton("Edit")
        update_preset_button = QPushButton("Update")
        delete_preset_button = QPushButton("Delete")
        set_hover_help(self.preset_combo, "Load a saved processing preset into this workflow.", enabled=self._show_tooltips)
        set_hover_help(save_preset_button, "Save the current workflow processing settings as a reusable preset.", enabled=self._show_tooltips)
        set_hover_help(edit_preset_button, "Edit the selected preset name and description.", enabled=self._show_tooltips)
        set_hover_help(update_preset_button, "Overwrite the selected preset with the current workflow settings.", enabled=self._show_tooltips)
        set_hover_help(delete_preset_button, "Delete the selected processing preset.", enabled=self._show_tooltips)
        save_preset_button.clicked.connect(self._save_current_as_preset)
        edit_preset_button.clicked.connect(self._edit_selected_preset_metadata)
        update_preset_button.clicked.connect(self._update_selected_preset)
        delete_preset_button.clicked.connect(self._delete_selected_preset)
        preset_layout.addWidget(save_preset_button)
        preset_layout.addWidget(edit_preset_button)
        preset_layout.addWidget(update_preset_button)
        preset_layout.addWidget(delete_preset_button)
        set_hover_help(self.model_combo, "Model used by this workflow. Leave it on the current selection to follow the global default.", enabled=self._show_tooltips)
        set_hover_help(self.api_mode_combo, "Per-workflow API preference. Audit workflows currently require the Responses API for structured validation.", enabled=self._show_tooltips)
        set_hover_help(self.use_global_temperature_check, "Use the global temperature from settings instead of a workflow-specific value.", enabled=self._show_tooltips)
        set_hover_help(self.temperature_spin, "Lower values are steadier; higher values allow more variation.", enabled=self._show_tooltips)
        set_hover_help(self.multiple_target_fields_check, "Expect delimited response sections that map to multiple note fields.", enabled=self._show_tooltips)
        set_hover_help(self.convert_markdown_to_html_check, "Convert generated Markdown to HTML before saving it back into notes.", enabled=self._show_tooltips)
        set_hover_help(self.delimiter_edit, "Delimiter used for multi-field responses, for example --Notes-- or --{field}--.", enabled=self._show_tooltips)
        set_hover_help(self.target_field_combo, "Single note field to update when multi-field mode is off.", enabled=self._show_tooltips)
        set_hover_help(self.mode_combo, "Choose whether the workflow overwrites, appends, or skips already-filled target fields.", enabled=self._show_tooltips)
        set_hover_help(self.success_tags_edit, "Comma-separated note tags to add when this field-update workflow succeeds for a note.", enabled=self._show_tooltips)
        set_hover_help(self.failure_tags_edit, "Comma-separated note tags to add when this field-update workflow fails for a note.", enabled=self._show_tooltips)
        set_hover_help(self.prompt_preview, "Editable text of the selected user prompt. Changes are saved back to that prompt.", enabled=self._show_tooltips)
        set_hover_help(self.system_prompt_preview, "Editable text of the selected system prompt. Changes are saved back to that prompt.", enabled=self._show_tooltips)
        set_hover_help(self.trigger_on_startup_check, "Run this workflow automatically when Anki opens the profile, if the query match threshold is met.", enabled=self._show_tooltips)
        set_hover_help(self.trigger_on_periodic_check, "Keep checking this workflow in the background and run it when the condition changes from not met to met.", enabled=self._show_tooltips)
        set_hover_help(self.trigger_min_matches_spin, "Minimum number of notes matching the workflow query before the automatic trigger can fire.", enabled=self._show_tooltips)
        set_hover_help(self.group_edit, "Optional comma-separated workflow groups used to organize and batch-run related workflows.", enabled=self._show_tooltips)

        content_layout.addLayout(form)

        preset_form = QFormLayout()
        self._preset_form = preset_form
        preset_form.addRow("Preset", preset_row)
        preset_form.addRow("Model", self.model_combo)
        preset_form.addRow("API mode", self.api_mode_combo)
        temperature_row = QWidget()
        temperature_layout = QHBoxLayout(temperature_row)
        temperature_layout.setContentsMargins(0, 0, 0, 0)
        temperature_layout.addWidget(self.use_global_temperature_check)
        temperature_layout.addWidget(self.temperature_spin)
        preset_form.addRow("Temperature", temperature_row)
        preset_form.addRow("", self.multiple_target_fields_check)
        preset_form.addRow("", self.convert_markdown_to_html_check)
        preset_form.addRow("Response delimiter", self.delimiter_edit)
        preset_form.addRow("Target field", self.target_field_combo)
        preset_form.addRow("Mode", self.mode_combo)
        preset_form.addRow("Success tags", self.success_tags_edit)
        preset_form.addRow("Failure tags", self.failure_tags_edit)
        preset_form.addRow("Schema preset", self.schema_preset_combo)
        preset_form.addRow("", self.trigger_on_startup_check)
        preset_form.addRow("", self.trigger_on_periodic_check)
        preset_form.addRow("Trigger min matches", self.trigger_min_matches_spin)
        preset_form.addRow("Groups", self.group_edit)
        self.preset_group = self._make_collapsible_section("Preset Settings", preset_form, expanded=True)
        content_layout.addWidget(self.preset_group)

        prompt_layout_group = QVBoxLayout()
        prompt_layout_group.addWidget(prompt_row)
        prompt_layout_group.addWidget(QLabel("Prompt"))
        prompt_layout_group.addWidget(self.prompt_preview)
        prompt_layout_group.addWidget(system_prompt_row)
        prompt_layout_group.addWidget(QLabel("System prompt"))
        prompt_layout_group.addWidget(self.system_prompt_preview)
        self.prompt_group = self._make_collapsible_section("Prompt Settings", prompt_layout_group, expanded=False)
        content_layout.addWidget(self.prompt_group)

        help_text = QLabel(
            "Queries use normal Anki Browser syntax and operate on notes. "
            "Use Refresh Count to preview how many notes currently match."
        )
        help_text.setWordWrap(True)
        content_layout.addWidget(help_text)
        content_layout.addStretch(1)
        layout.addWidget(scroll_area)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        self._buttons_box = buttons
        layout.addWidget(buttons)

    def _make_collapsible_section(
        self,
        title: str,
        inner_layout: QFormLayout | QVBoxLayout,
        *,
        expanded: bool,
    ) -> QWidget:
        section = QWidget(self)
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(4)

        toggle = QPushButton(section)
        toggle.setCheckable(True)
        toggle.setChecked(expanded)
        toggle.setFlat(True)
        toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        toggle.setStyleSheet("QPushButton { border: none; font-weight: 600; text-align: left; padding: 2px 0; }")

        content = QWidget(section)
        content.setLayout(inner_layout)
        content.setVisible(expanded)

        def _set_toggle_label(is_expanded: bool) -> None:
            toggle.setText(f"{'▾' if is_expanded else '▸'} {title}")

        def _toggle_section(is_expanded: bool) -> None:
            _set_toggle_label(is_expanded)
            content.setVisible(is_expanded)
            if is_expanded:
                QTimer.singleShot(0, self._expand_window_to_fit_content)

        _set_toggle_label(expanded)
        toggle.toggled.connect(_toggle_section)
        section_layout.addWidget(toggle)
        section_layout.addWidget(content)
        if title == "Preset Settings":
            self._preset_group_toggle = toggle
        return section

    def _expand_window_to_fit_content(self) -> None:
        if self._scroll_content is not None:
            self._scroll_content.adjustSize()
        if self._scroll_area is not None:
            self._scroll_area.updateGeometry()
        self.layout().activate()
        hint = self.layout().sizeHint()
        screen = self.screen()
        if screen is not None:
            available = screen.availableGeometry()
            max_width = max(available.width() - 60, 720)
            max_height = max(available.height() - 60, 520)
        else:
            max_width = hint.width()
            max_height = hint.height()
        width_padding = 24
        height_padding = 24
        if self._scroll_area is not None:
            width_padding += self._scroll_area.frameWidth() * 2
            height_padding += self._scroll_area.frameWidth() * 2
        target_width = min(max(self.width(), hint.width() + width_padding), max_width)
        target_height = min(max(self.height(), hint.height() + height_padding), max_height)
        self.resize(target_width, target_height)

    def _populate(self, workflow: Workflow | None) -> None:
        self._populate_prompt_combo()
        self._populate_system_prompt_combo()
        self._populate_group_edit()
        self._refresh_prompt_preview()
        self._refresh_system_prompt_preview()
        self._refresh_target_mode_ui()
        self._refresh_temperature_ui()
        self.enabled_check.setChecked(True)
        self._set_combo_to_data(self.api_mode_combo, "global_default")
        self._set_combo_to_data(self.schema_preset_combo, AUDIT_SCHEMA_PRESET_MLR)
        self._refresh_workflow_type_ui()

        if workflow is None:
            return

        self.name_edit.setText(workflow.name)
        self.query_edit.setText(workflow.query)
        self._set_combo_to_data(self.workflow_type_combo, workflow.workflow_type)
        self.enabled_check.setChecked(workflow.enabled)
        self.target_field_combo.setEditText(workflow.target_field)
        self.multiple_target_fields_check.setChecked(workflow.multiple_target_fields)
        self.convert_markdown_to_html_check.setChecked(workflow.convert_markdown_to_html)
        self._set_temperature(workflow.temperature)
        self.delimiter_edit.setText(workflow.response_delimiter or "")
        self._set_combo_to_data(self.api_mode_combo, workflow.api_mode or "global_default")
        self._set_combo_to_data(self.schema_preset_combo, workflow.schema_preset or AUDIT_SCHEMA_PRESET_MLR)
        self.trigger_on_startup_check.setChecked(workflow.trigger_on_startup)
        self.trigger_on_periodic_check.setChecked(workflow.trigger_on_periodic)
        self.trigger_min_matches_spin.setValue(workflow.trigger_min_matches)
        model_value = workflow.model or self._current_model
        model_index = self.model_combo.findData(model_value)
        if model_index >= 0:
            self.model_combo.setCurrentIndex(model_index)
        prompt_index = self.prompt_combo.findData(workflow.prompt_id)
        if prompt_index >= 0:
            self.prompt_combo.setCurrentIndex(prompt_index)
        system_prompt_index = self.system_prompt_combo.findData(workflow.system_prompt_id or "")
        if system_prompt_index >= 0:
            self.system_prompt_combo.setCurrentIndex(system_prompt_index)
        mode_index = self.mode_combo.findData(workflow.mode)
        if mode_index >= 0:
            self.mode_combo.setCurrentIndex(mode_index)
        self.group_edit.setText(", ".join(self._current_group_names))
        self.success_tags_edit.setText(", ".join(workflow.success_tags or []))
        self.failure_tags_edit.setText(", ".join(workflow.failure_tags or []))
        self._refresh_prompt_preview()
        self._refresh_system_prompt_preview()
        self._refresh_workflow_type_ui()
        self._refresh_target_mode_ui()
        self._refresh_query_count()

    def workflow_draft(self) -> WorkflowDraft | None:
        name = self.name_edit.text().strip()
        query = self.query_edit.text().strip()
        workflow_type = str(self.workflow_type_combo.currentData() or "field_update")
        model = self.model_combo.currentData() or self.model_combo.currentText().strip()
        prompt_id = self.prompt_combo.currentData() or self.prompt_combo.currentText().strip()
        system_prompt_id = self.system_prompt_combo.currentData() or ""
        target_field = self.target_field_combo.currentText().strip()
        mode = self.mode_combo.currentData() or WRITE_MODE_OVERWRITE
        if not isinstance(prompt_id, str):
            return None
        return WorkflowDraft(
            name=name,
            query=query,
            workflow_type=workflow_type,
            enabled=self.enabled_check.isChecked(),
            model=str(model) or None,
            temperature=self._selected_temperature(),
            api_mode=str(self.api_mode_combo.currentData() or "global_default"),
            prompt_id=prompt_id,
            system_prompt_id=str(system_prompt_id) or None,
            target_field="" if workflow_type == "audit" or self.multiple_target_fields_check.isChecked() else target_field,
            mode=str(mode),
            multiple_target_fields=workflow_type != "audit" and self.multiple_target_fields_check.isChecked(),
            convert_markdown_to_html=self.convert_markdown_to_html_check.isChecked(),
            response_delimiter=None if workflow_type == "audit" else (self.delimiter_edit.text().strip() or None),
            schema_preset=str(self.schema_preset_combo.currentData() or AUDIT_SCHEMA_PRESET_MLR) if workflow_type == "audit" else None,
            success_tags=None if workflow_type == "audit" else _parse_tag_list(self.success_tags_edit.text()),
            failure_tags=None if workflow_type == "audit" else _parse_tag_list(self.failure_tags_edit.text()),
            trigger_on_startup=self.trigger_on_startup_check.isChecked(),
            trigger_on_periodic=self.trigger_on_periodic_check.isChecked(),
            trigger_min_matches=int(self.trigger_min_matches_spin.value()),
            group_names=_parse_group_names(self.group_edit.text()),
        )

    def _populate_model_combo(self) -> None:
        self.model_combo.clear()
        for option in self._model_options:
            self.model_combo.addItem(option.label, option.model_id)
        if self._current_model:
            index = self.model_combo.findData(self._current_model)
            if index >= 0:
                self.model_combo.setCurrentIndex(index)
            else:
                self.model_combo.insertItem(0, self._current_model + " (Current selection)", self._current_model)
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

    def _populate_group_edit(self) -> None:
        known_group_names = ", ".join(group.name for group in sorted(self._groups, key=lambda item: item.name.lower()))
        if known_group_names:
            self.group_edit.setPlaceholderText(f"Comma-separated, e.g. {known_group_names}")
        else:
            self.group_edit.setPlaceholderText("Comma-separated group names")

    def _selected_prompt(self) -> PromptChoice | None:
        prompt_id = self.prompt_combo.currentData()
        for prompt in self._prompts:
            if prompt.prompt_id == prompt_id:
                return prompt
        return self._prompts[0] if self._prompts else None

    def _refresh_prompt_preview(self) -> None:
        prompt = self._selected_prompt()
        self.prompt_preview.blockSignals(True)
        self.prompt_preview.setPlainText(prompt.prompt_text if prompt else "")
        self.prompt_preview.blockSignals(False)

    def _populate_system_prompt_combo(self) -> None:
        self.system_prompt_combo.clear()
        self.system_prompt_combo.addItem("Default system prompt", "")
        for prompt in self._system_prompts:
            self.system_prompt_combo.addItem(prompt.name, prompt.prompt_id)

    def _selected_system_prompt(self) -> PromptChoice | None:
        prompt_id = self.system_prompt_combo.currentData()
        if not prompt_id:
            return None
        for prompt in self._system_prompts:
            if prompt.prompt_id == prompt_id:
                return prompt
        return None

    def _refresh_system_prompt_preview(self) -> None:
        prompt = self._selected_system_prompt()
        self.system_prompt_preview.blockSignals(True)
        self.system_prompt_preview.setPlainText(prompt.prompt_text if prompt else self._raw_config.get("system_prompt", ""))
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
        updated_text = self.system_prompt_preview.toPlainText().strip()
        if prompt is None:
            self._raw_config["system_prompt"] = updated_text
            save_raw_config(self._raw_config)
            return
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

    def _refresh_workflow_type_ui(self) -> None:
        is_audit = (self.workflow_type_combo.currentData() or "field_update") == "audit"
        self.preset_combo.setEnabled(not is_audit)
        self.multiple_target_fields_check.setEnabled(not is_audit)
        self.convert_markdown_to_html_check.setEnabled(not is_audit)
        self.target_field_combo.setEnabled(not is_audit and not self.multiple_target_fields_check.isChecked())
        self.mode_combo.setEnabled(not is_audit)
        self.delimiter_edit.setEnabled(not is_audit and self.multiple_target_fields_check.isChecked())
        self.schema_preset_combo.setEnabled(is_audit)
        if is_audit:
            self.multiple_target_fields_check.setChecked(False)
            self._set_combo_to_data(self.api_mode_combo, "responses")
        self._set_preset_form_row_visible(self._preset_row, not is_audit)
        self._set_preset_form_row_visible(self.multiple_target_fields_check, not is_audit)
        self._set_preset_form_row_visible(self.convert_markdown_to_html_check, not is_audit)
        self._set_preset_form_row_visible(self.delimiter_edit, not is_audit)
        self._set_preset_form_row_visible(self.target_field_combo, not is_audit)
        self._set_preset_form_row_visible(self.mode_combo, not is_audit)
        self._set_preset_form_row_visible(self.success_tags_edit, not is_audit)
        self._set_preset_form_row_visible(self.failure_tags_edit, not is_audit)
        self._set_preset_form_row_visible(self.schema_preset_combo, is_audit)
        self._update_preset_group_title(is_audit=is_audit)
        self._refresh_target_mode_ui()

    def _set_preset_form_row_visible(self, field: QWidget | None, visible: bool) -> None:
        if self._preset_form is None or field is None:
            return
        label = self._preset_form.labelForField(field)
        if label is not None:
            label.setVisible(visible)
        field.setVisible(visible)

    def _update_preset_group_title(self, *, is_audit: bool) -> None:
        if self._preset_group_toggle is None:
            return
        title = "Audit Settings" if is_audit else "Preset Settings"
        prefix = "▾" if self._preset_group_toggle.isChecked() else "▸"
        self._preset_group_toggle.setText(f"{prefix} {title}")

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
        self._refresh_target_mode_ui()

    def _save_current_as_preset(self) -> None:
        dialog = SavedPromptDialog(
            parent=self,
            window_title="Processing Preset",
            prompt_label="Description",
            placeholder_text="Optional notes about this preset",
            help_text="Save the current processing settings as a reusable preset for Browser runs and workflows.",
            id_prefix="processing-preset",
            require_prompt_text=False,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        choice = dialog.named_item()
        if choice is None:
            return

        preset = ProcessingPresetChoice(
            preset_id=choice.prompt_id,
            name=choice.name,
            prompt_id=str(self.prompt_combo.currentData() or ""),
            description=choice.prompt_text or None,
            model=str(self.model_combo.currentData() or self.model_combo.currentText().strip()) or None,
            temperature=self._selected_temperature(),
            system_prompt_id=str(self.system_prompt_combo.currentData() or "") or None,
            target_field="" if self.multiple_target_fields_check.isChecked() else self.target_field_combo.currentText().strip(),
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
            help_text="Edit the selected preset name and description without changing its workflow settings.",
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
                    description=choice.prompt_text or None,
                    prompt_id=current.prompt_id,
                    model=current.model,
                    temperature=current.temperature,
                    system_prompt_id=current.system_prompt_id,
                    target_field=current.target_field,
                    mode=current.mode,
                    multiple_target_fields=current.multiple_target_fields,
                    convert_markdown_to_html=current.convert_markdown_to_html,
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
                "response_delimiter": preset.response_delimiter,
            }
            for preset in self._presets
        ]
        save_raw_config(self._raw_config)

    def _current_preset_choice(self, *, preset_id: str, name: str) -> ProcessingPresetChoice:
        existing_preset = self._selected_preset()
        return ProcessingPresetChoice(
            preset_id=preset_id,
            name=name,
            description=existing_preset.description if existing_preset is not None and existing_preset.preset_id == preset_id else None,
            prompt_id=str(self.prompt_combo.currentData() or ""),
            model=str(self.model_combo.currentData() or self.model_combo.currentText().strip()) or None,
            temperature=self._selected_temperature(),
            system_prompt_id=str(self.system_prompt_combo.currentData() or "") or None,
            target_field="" if self.multiple_target_fields_check.isChecked() else self.target_field_combo.currentText().strip(),
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

    def _refresh_query_count(self) -> None:
        query = self.query_edit.text().strip()
        if not query:
            self.query_count_label.setText("Enter a query first.")
            return

        try:
            note_ids = _find_note_ids_for_query(query)
        except RuntimeError as error:
            self.query_count_label.setText(f"Query error: {error}")
            return

        self.query_count_label.setText(f"Matches {len(note_ids)} note(s).")
        common_fields = _common_fields_for_notes(note_ids)
        current_target = self.target_field_combo.currentText().strip()
        self.target_field_combo.clear()
        for field_name in common_fields:
            self.target_field_combo.addItem(field_name)
        if current_target:
            self.target_field_combo.setEditText(current_target)

    def _create_prompt(self) -> None:
        dialog = SavedPromptDialog(
            parent=self,
            window_title="Saved Prompt",
            prompt_label="Prompt",
            placeholder_text="Use placeholders like {{Front}}, {{Back}}, {{NoteType}}",
            help_text="Prompt names appear in the picker. The full prompt text is stored for workflow runs.",
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
            help_text="Prompt names appear in the picker. The full prompt text is stored for workflow runs.",
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
        self._save_prompts()
        self._populate_prompt_combo()
        self._refresh_prompt_preview()

    def _save_prompts(self) -> None:
        save_saved_prompts(self._raw_config, self._prompts)

    def _create_system_prompt(self) -> None:
        dialog = SavedPromptDialog(
            parent=self,
            window_title="Saved System Prompt",
            prompt_label="System prompt",
            placeholder_text="You improve Anki flashcards...",
            help_text="System prompt names appear in the picker. The full system prompt text is stored for workflow runs.",
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
            help_text="System prompt names appear in the picker. The full system prompt text is stored for workflow runs.",
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

    def _delete_system_prompt(self) -> None:
        prompt = self._selected_system_prompt()
        if prompt is None:
            showCritical("Choose a saved system prompt before deleting.", parent=self)
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
        self._save_system_prompts()
        self._populate_system_prompt_combo()
        self._refresh_system_prompt_preview()

    def _save_system_prompts(self) -> None:
        self._raw_config["saved_system_prompts"] = [
            {"id": prompt.prompt_id, "name": prompt.name, "prompt": prompt.prompt_text}
            for prompt in self._system_prompts
        ]
        save_raw_config(self._raw_config)

    def _validate_and_accept(self) -> None:
        draft = self.workflow_draft()
        if draft is None:
            showCritical("Workflow values could not be read.", parent=self)
            return
        if not draft.name:
            showCritical("Workflow name must not be empty.", parent=self)
            return
        if not draft.query:
            showCritical("Workflow query must not be empty.", parent=self)
            return
        if not draft.prompt_id:
            showCritical("Choose a saved prompt for this workflow.", parent=self)
            return
        if draft.workflow_type == "audit":
            if not draft.schema_preset:
                showCritical("Choose an audit schema preset.", parent=self)
                return
            if draft.api_mode == "chat_completions":
                showCritical("Audit workflows currently require the Responses API.", parent=self)
                return
            self.accept()
            return
        if draft.multiple_target_fields and not draft.response_delimiter:
            showCritical("Enter the response delimiter for multiple target field mode.", parent=self)
            return
        if draft.multiple_target_fields and draft.mode == WRITE_MODE_SKIP_NONEMPTY:
            showCritical(
                "Skip-if-not-empty mode is only available for a single target field.",
                parent=self,
            )
            return
        if not draft.multiple_target_fields and not draft.target_field:
            showCritical("Target field must not be empty.", parent=self)
            return
        self.accept()


def _find_note_ids_for_query(query: str) -> list[int]:
    if mw is None or mw.col is None:
        raise RuntimeError("Anki collection is not available.")

    try:
        note_ids = list(mw.col.find_notes(query))
    except Exception as error:
        raise RuntimeError(str(error)) from error
    return [int(note_id) for note_id in note_ids]
