from __future__ import annotations

from dataclasses import dataclass, replace

from aqt import mw
from aqt.qt import (
    QAction,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
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
from aqt.utils import askUser, showCritical, showInfo, tooltip

from .automation_ui import PromptChoice, SavedPromptDialog
from .config import (
    ConfigError,
    SavedPrompt,
    Workflow,
    WorkflowGroup,
    load_config,
    load_raw_config,
    new_object_id,
    save_raw_config,
)
from .model_catalog import fallback_model_options
from .processing import (
    ManualProcessingSpec,
    ProcessingResult,
    WRITE_MODE_APPEND,
    WRITE_MODE_OVERWRITE,
    prepare_manual_ai_processing,
    start_prepared_manual_processing,
)


@dataclass(frozen=True)
class WorkflowDraft:
    name: str
    query: str
    prompt_id: str
    target_field: str
    mode: str
    model: str | None
    system_prompt_id: str | None
    group_name: str | None


@dataclass
class WorkflowSequenceSummary:
    workflow_reports: list[str]
    failures: list[str]
    skipped: list[str]
    updated_requests: int = 0


def register_workflow_menu() -> None:
    if mw is None:
        return

    action = QAction("Process specific cards with AI", mw)
    action.triggered.connect(_open_workflow_manager)
    mw.form.menuTools.addAction(action)


def _open_workflow_manager() -> None:
    if mw is None:
        return
    try:
        dialog = WorkflowManagerDialog(parent=mw)
    except ConfigError as error:
        showCritical(str(error), parent=mw)
        return
    dialog.exec()


class WorkflowManagerDialog(QDialog):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Process Specific Cards with AI")
        self.resize(860, 680)

        self._raw_config = load_raw_config()
        self._load_state()

        self.workflow_list = QListWidget()
        self.group_run_combo = QComboBox()

        self._build_ui()
        self._populate()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        intro = QLabel(
            "Manage reusable query-based AI workflows. Each workflow runs an Anki search, "
            "uses a saved prompt, and writes to one target field."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        group_box = QGroupBox("Run Group")
        group_layout = QHBoxLayout(group_box)
        group_layout.addWidget(QLabel("Workflow group"))
        group_layout.addWidget(self.group_run_combo, stretch=1)
        run_group_button = QPushButton("Run Group")
        run_group_button.clicked.connect(self._run_selected_group)
        group_layout.addWidget(run_group_button)
        layout.addWidget(group_box)

        layout.addWidget(QLabel("Workflows"))
        self.workflow_list.setMinimumHeight(320)
        layout.addWidget(self.workflow_list)

        button_row = QHBoxLayout()
        add_button = QPushButton("Add")
        edit_button = QPushButton("Edit")
        delete_button = QPushButton("Delete")
        duplicate_button = QPushButton("Duplicate")
        move_up_button = QPushButton("Move Up")
        move_down_button = QPushButton("Move Down")
        run_button = QPushButton("Run Workflow")
        add_button.clicked.connect(self._add_workflow)
        edit_button.clicked.connect(self._edit_workflow)
        delete_button.clicked.connect(self._delete_workflow)
        duplicate_button.clicked.connect(self._duplicate_workflow)
        move_up_button.clicked.connect(self._move_selected_up)
        move_down_button.clicked.connect(self._move_selected_down)
        run_button.clicked.connect(self._run_selected_workflow)
        button_row.addWidget(add_button)
        button_row.addWidget(edit_button)
        button_row.addWidget(delete_button)
        button_row.addWidget(duplicate_button)
        button_row.addWidget(move_up_button)
        button_row.addWidget(move_down_button)
        button_row.addStretch(1)
        button_row.addWidget(run_button)
        layout.addLayout(button_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _load_state(self) -> None:
        self._config = load_config()
        self._prompts = [
            PromptChoice(prompt_id=prompt.prompt_id, name=prompt.name, prompt_text=prompt.prompt_text)
            for prompt in self._config.saved_prompts
        ]
        self._system_prompts = [
            PromptChoice(prompt_id=prompt.prompt_id, name=prompt.name, prompt_text=prompt.prompt_text)
            for prompt in self._config.saved_system_prompts
        ]
        self._groups = sorted(self._config.workflow_groups, key=lambda group: group.name.lower())
        self._workflows = sorted(self._config.workflows, key=lambda workflow: workflow.position)

    def _populate(self) -> None:
        self.workflow_list.clear()
        for workflow in self._workflows:
            self.workflow_list.addItem(self._workflow_preview(workflow))

        self.group_run_combo.clear()
        self.group_run_combo.addItem("Choose a group", "")
        for group in self._groups:
            self.group_run_combo.addItem(group.name, group.group_id)

    def _workflow_preview(self, workflow: Workflow) -> str:
        prompt_name = self._prompt_name(workflow.prompt_id)
        group_name = self._group_name(workflow.group_id) or "No group"
        return (
            f"{workflow.name}\n"
            f"Query: {workflow.query}\n"
            f"Prompt: {prompt_name} | Target: {workflow.target_field} | "
            f"Mode: {workflow.mode} | Model: {workflow.model or self._config.model} | "
            f"System: {self._system_prompt_name(workflow.system_prompt_id)} | Group: {group_name}"
        )

    def _prompt_name(self, prompt_id: str) -> str:
        for prompt in self._prompts:
            if prompt.prompt_id == prompt_id:
                return prompt.name
        return "Missing prompt"

    def _group_name(self, group_id: str | None) -> str | None:
        if group_id is None:
            return None
        for group in self._groups:
            if group.group_id == group_id:
                return group.name
        return None

    def _system_prompt_name(self, prompt_id: str | None) -> str:
        if prompt_id is None:
            return "Default system prompt"
        for prompt in self._system_prompts:
            if prompt.prompt_id == prompt_id:
                return prompt.name
        return "Missing system prompt"

    def _save_state(self) -> None:
        self._raw_config = load_raw_config()
        self._raw_config["workflow_groups"] = [
            {"id": group.group_id, "name": group.name}
            for group in sorted(self._groups, key=lambda group: group.name.lower())
        ]
        self._raw_config["workflows"] = [
            {
                "id": workflow.workflow_id,
                "name": workflow.name,
                "query": workflow.query,
                "prompt_id": workflow.prompt_id,
                "target_field": workflow.target_field,
                "mode": workflow.mode,
                "model": workflow.model,
                "system_prompt_id": workflow.system_prompt_id,
                "group_id": workflow.group_id,
                "position": index,
            }
            for index, workflow in enumerate(self._workflows)
        ]
        save_raw_config(self._raw_config)
        self._load_state()
        self._populate()

    def _selected_workflow_index(self) -> int:
        return self.workflow_list.currentRow()

    def _add_workflow(self) -> None:
        dialog = WorkflowDialog(
            parent=self,
            prompts=self._prompts,
            system_prompts=self._system_prompts,
            groups=self._groups,
            current_model=self._config.model,
            model_pricing=self._config.model_pricing,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        draft = dialog.workflow_draft()
        if draft is None:
            return
        workflow = Workflow(
            workflow_id=new_object_id("workflow"),
            name=draft.name,
            query=draft.query,
            prompt_id=draft.prompt_id,
            target_field=draft.target_field,
            mode=draft.mode,
            model=draft.model,
            system_prompt_id=draft.system_prompt_id,
            group_id=self._group_id_for_name(draft.group_name),
            position=len(self._workflows),
        )
        self._workflows.append(workflow)
        self._save_state()
        self.workflow_list.setCurrentRow(len(self._workflows) - 1)

    def _edit_workflow(self) -> None:
        row = self._selected_workflow_index()
        if row < 0 or row >= len(self._workflows):
            return
        workflow = self._workflows[row]
        dialog = WorkflowDialog(
            parent=self,
            prompts=self._prompts,
            system_prompts=self._system_prompts,
            groups=self._groups,
            current_model=self._config.model,
            model_pricing=self._config.model_pricing,
            workflow=workflow,
            current_group_name=self._group_name(workflow.group_id),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        draft = dialog.workflow_draft()
        if draft is None:
            return
        self._workflows[row] = replace(
            workflow,
            name=draft.name,
            query=draft.query,
            prompt_id=draft.prompt_id,
            target_field=draft.target_field,
            mode=draft.mode,
            model=draft.model,
            system_prompt_id=draft.system_prompt_id,
            group_id=self._group_id_for_name(draft.group_name),
        )
        self._save_state()
        self.workflow_list.setCurrentRow(row)

    def _delete_workflow(self) -> None:
        row = self._selected_workflow_index()
        if row < 0 or row >= len(self._workflows):
            return

        workflow = self._workflows[row]
        reply = QMessageBox.question(
            self,
            "Delete Workflow",
            f"Delete workflow '{workflow.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        del self._workflows[row]
        self._remove_unused_groups()
        self._save_state()
        if self._workflows:
            self.workflow_list.setCurrentRow(min(row, len(self._workflows) - 1))

    def _duplicate_workflow(self) -> None:
        row = self._selected_workflow_index()
        if row < 0 or row >= len(self._workflows):
            tooltip("Select a workflow to duplicate.", parent=self)
            return

        workflow = self._workflows[row]
        duplicate = replace(
            workflow,
            workflow_id=new_object_id("workflow"),
            name=f"{workflow.name} Copy",
            position=len(self._workflows),
        )
        self._workflows.insert(row + 1, duplicate)
        self._save_state()
        self.workflow_list.setCurrentRow(row + 1)

    def _move_selected_up(self) -> None:
        row = self._selected_workflow_index()
        if row <= 0 or row >= len(self._workflows):
            return
        self._workflows[row - 1], self._workflows[row] = self._workflows[row], self._workflows[row - 1]
        self._save_state()
        self.workflow_list.setCurrentRow(row - 1)

    def _move_selected_down(self) -> None:
        row = self._selected_workflow_index()
        if row < 0 or row >= len(self._workflows) - 1:
            return
        self._workflows[row + 1], self._workflows[row] = self._workflows[row], self._workflows[row + 1]
        self._save_state()
        self.workflow_list.setCurrentRow(row + 1)

    def _run_selected_workflow(self) -> None:
        row = self._selected_workflow_index()
        if row < 0 or row >= len(self._workflows):
            tooltip("Select a workflow to run.", parent=self)
            return
        self._run_workflow_sequence([self._workflows[row]], run_label=self._workflows[row].name)

    def _run_selected_group(self) -> None:
        group_id = self.group_run_combo.currentData()
        if not isinstance(group_id, str) or not group_id:
            tooltip("Choose a workflow group to run.", parent=self)
            return
        workflows = [workflow for workflow in self._workflows if workflow.group_id == group_id]
        if not workflows:
            tooltip("This group does not contain any workflows.", parent=self)
            return
        group_name = self._group_name(group_id) or "Selected group"
        self._run_workflow_sequence(workflows, run_label=group_name)

    def _run_workflow_sequence(self, workflows: list[Workflow], *, run_label: str) -> None:
        try:
            config = load_config()
        except ConfigError as error:
            showCritical(str(error), parent=self)
            return

        if not config.enabled:
            tooltip("AI Automation is disabled in the add-on config.", parent=self)
            return

        prompt_lookup = {prompt.prompt_id: prompt for prompt in config.saved_prompts}
        query_counts: list[tuple[Workflow, int]] = []
        for workflow in workflows:
            if workflow.prompt_id not in prompt_lookup:
                showCritical(
                    f"Workflow '{workflow.name}' references a missing saved prompt.",
                    parent=self,
                )
                return
            try:
                query_counts.append((workflow, len(_find_note_ids_for_query(workflow.query))))
            except RuntimeError as error:
                showCritical(f"Workflow '{workflow.name}' query error:\n\n{error}", parent=self)
                return

        confirmation_lines = [
            f"Ready to run {len(workflows)} workflow(s) for '{run_label}'.",
            "",
            "Current query matches:",
        ]
        for workflow, count in query_counts[:20]:
            confirmation_lines.append(f"- {workflow.name}: {count} note(s)")
        if len(query_counts) > 20:
            confirmation_lines.append(f"- ...and {len(query_counts) - 20} more workflows")
        confirmation_lines.extend(["", "Continue?"])
        if not askUser("\n".join(confirmation_lines), parent=self):
            return

        self.setEnabled(False)
        summary = WorkflowSequenceSummary(workflow_reports=[], failures=[], skipped=[])
        self._run_workflow_at_index(
            workflows=workflows,
            index=0,
            config=config,
            prompt_lookup=prompt_lookup,
            summary=summary,
        )

    def _run_workflow_at_index(
        self,
        *,
        workflows: list[Workflow],
        index: int,
        config,
        prompt_lookup: dict[str, SavedPrompt],
        summary: WorkflowSequenceSummary,
    ) -> None:
        if index >= len(workflows):
            self.setEnabled(True)
            self._show_workflow_sequence_summary(summary)
            return

        workflow = workflows[index]
        prompt = prompt_lookup.get(workflow.prompt_id)
        if prompt is None:
            summary.failures.append(f"- Workflow '{workflow.name}': saved prompt is missing.")
            self._run_workflow_at_index(
                workflows=workflows,
                index=index + 1,
                config=config,
                prompt_lookup=prompt_lookup,
                summary=summary,
            )
            return

        try:
            note_ids = _find_note_ids_for_query(workflow.query)
        except RuntimeError as error:
            summary.failures.append(f"- Workflow '{workflow.name}': query failed: {error}")
            self._run_workflow_at_index(
                workflows=workflows,
                index=index + 1,
                config=config,
                prompt_lookup=prompt_lookup,
                summary=summary,
            )
            return

        if not note_ids:
            summary.skipped.append(f"- {workflow.name}: no matching notes.")
            self._run_workflow_at_index(
                workflows=workflows,
                index=index + 1,
                config=config,
                prompt_lookup=prompt_lookup,
                summary=summary,
            )
            return

        spec = ManualProcessingSpec(
            prompt_name=prompt.name,
            prompt_template=prompt.prompt_text,
            target_field=workflow.target_field,
            system_prompt_name=self._system_prompt_name(workflow.system_prompt_id),
            system_prompt=self._system_prompt_text(workflow.system_prompt_id),
            write_mode=workflow.mode,
            model=workflow.model or config.model,
        )
        prepared = prepare_manual_ai_processing(
            config,
            note_ids,
            spec,
            include_estimate=False,
        )
        if not prepared.snapshots:
            summary.workflow_reports.append(f"{workflow.name}: 0 processed, {len(prepared.failures)} skipped.")
            summary.failures.extend(
                [f"- Workflow '{workflow.name}': {failure.reason}" for failure in prepared.failures]
            )
            self._run_workflow_at_index(
                workflows=workflows,
                index=index + 1,
                config=config,
                prompt_lookup=prompt_lookup,
                summary=summary,
            )
            return

        start_prepared_manual_processing(
            self,
            config,
            prepared,
            progress_label=f"Running workflow {index + 1}/{len(workflows)}: {workflow.name}",
            show_feedback=False,
            on_done=lambda result: self._on_workflow_finished(
                workflows=workflows,
                index=index,
                config=config,
                prompt_lookup=prompt_lookup,
                summary=summary,
                workflow=workflow,
                result=result,
            ),
        )

    def _on_workflow_finished(
        self,
        *,
        workflows: list[Workflow],
        index: int,
        config,
        prompt_lookup: dict[str, SavedPrompt],
        summary: WorkflowSequenceSummary,
        workflow: Workflow,
        result: ProcessingResult,
    ) -> None:
        summary.updated_requests += len(result.updates)
        summary.workflow_reports.append(
            f"{workflow.name}: {len(result.updates)} processed, {len(result.failures)} skipped."
        )
        summary.failures.extend(
            [
                f"- Workflow '{workflow.name}' note {failure.note_id} ({failure.note_type_name}): {failure.reason}"
                for failure in result.failures
            ]
        )
        self._run_workflow_at_index(
            workflows=workflows,
            index=index + 1,
            config=config,
            prompt_lookup=prompt_lookup,
            summary=summary,
        )

    def _show_workflow_sequence_summary(self, summary: WorkflowSequenceSummary) -> None:
        if summary.updated_requests:
            tooltip(
                f"AI Automation ran workflows and sent {summary.updated_requests} request(s).",
                parent=self,
            )
        elif not summary.failures and not summary.skipped:
            tooltip("No workflows ran.", parent=self)

        report_lines = ["Workflow run summary:", ""]
        report_lines.extend(f"- {line}" for line in summary.workflow_reports)
        if summary.skipped:
            report_lines.extend(["", "Skipped:"])
            report_lines.extend(summary.skipped)
        if summary.failures:
            report_lines.extend(["", "Failures:"])
            report_lines.extend(summary.failures[:40])
            if len(summary.failures) > 40:
                report_lines.append(f"- ...and {len(summary.failures) - 40} more")
        showInfo("\n".join(report_lines), parent=self)

    def _group_id_for_name(self, group_name: str | None) -> str | None:
        if group_name is None or not group_name.strip():
            return None
        normalized = group_name.strip()
        for group in self._groups:
            if group.name == normalized:
                return group.group_id

        new_group = WorkflowGroup(group_id=new_object_id("group"), name=normalized)
        self._groups.append(new_group)
        self._groups.sort(key=lambda group: group.name.lower())
        return new_group.group_id

    def _remove_unused_groups(self) -> None:
        used_group_ids = {workflow.group_id for workflow in self._workflows if workflow.group_id}
        self._groups = [group for group in self._groups if group.group_id in used_group_ids]

    def _system_prompt_text(self, prompt_id: str | None) -> str:
        if prompt_id is None:
            return self._config.system_prompt
        for prompt in self._system_prompts:
            if prompt.prompt_id == prompt_id:
                return prompt.prompt_text
        return self._config.system_prompt


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
        current_group_name: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Workflow")
        self.resize(720, 560)

        self._raw_config = load_raw_config()
        self._prompts = list(prompts)
        self._system_prompts = list(system_prompts)
        self._groups = list(groups)
        self._current_group_name = current_group_name or ""
        self._current_model = current_model
        self._model_options = fallback_model_options(
            current_model=current_model,
            pricing_overrides=model_pricing,
        )

        self.name_edit = QLineEdit()
        self.query_edit = QPlainTextEdit()
        self.query_count_label = QLabel("Click Refresh Count to check the query.")
        self.model_combo = QComboBox()
        self.prompt_combo = QComboBox()
        self.system_prompt_combo = QComboBox()
        self.target_field_combo = QComboBox()
        self.target_field_combo.setEditable(True)
        self.mode_combo = QComboBox()
        self.group_combo = QComboBox()
        self.group_combo.setEditable(True)

        self._build_ui()
        self._populate(workflow)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.query_edit.setMinimumHeight(96)

        prompt_row = QWidget()
        prompt_layout = QHBoxLayout(prompt_row)
        prompt_layout.setContentsMargins(0, 0, 0, 0)
        prompt_layout.addWidget(self.prompt_combo, stretch=1)
        new_button = QPushButton("New")
        edit_button = QPushButton("Edit")
        delete_button = QPushButton("Delete")
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

        query_row = QWidget()
        query_layout = QVBoxLayout(query_row)
        query_layout.setContentsMargins(0, 0, 0, 0)
        query_layout.addWidget(self.query_edit)
        refresh_row = QHBoxLayout()
        refresh_row.setContentsMargins(0, 0, 0, 0)
        refresh_button = QPushButton("Refresh Count")
        refresh_button.clicked.connect(self._refresh_query_count)
        refresh_row.addWidget(refresh_button)
        refresh_row.addWidget(self.query_count_label, stretch=1)
        query_layout.addLayout(refresh_row)

        self._populate_model_combo()
        self.mode_combo.addItem("Overwrite target field", WRITE_MODE_OVERWRITE)
        self.mode_combo.addItem("Append to target field", WRITE_MODE_APPEND)

        form.addRow("Name", self.name_edit)
        form.addRow("Query", query_row)
        form.addRow("Model", self.model_combo)
        form.addRow("Prompt", prompt_row)
        form.addRow("System prompt", system_prompt_row)
        form.addRow("Target field", self.target_field_combo)
        form.addRow("Mode", self.mode_combo)
        form.addRow("Group", self.group_combo)
        layout.addLayout(form)

        help_text = QLabel(
            "Queries use normal Anki Browser syntax and operate on notes. "
            "Use Refresh Count to preview how many notes currently match."
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate(self, workflow: Workflow | None) -> None:
        self._populate_prompt_combo()
        self._populate_system_prompt_combo()
        self._populate_group_combo()

        if workflow is None:
            return

        self.name_edit.setText(workflow.name)
        self.query_edit.setPlainText(workflow.query)
        self.target_field_combo.setEditText(workflow.target_field)
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
        self.group_combo.setEditText(self._current_group_name)
        self._refresh_query_count()

    def workflow_draft(self) -> WorkflowDraft | None:
        name = self.name_edit.text().strip()
        query = self.query_edit.toPlainText().strip()
        model = self.model_combo.currentData() or self.model_combo.currentText().strip()
        prompt_id = self.prompt_combo.currentData() or self.prompt_combo.currentText().strip()
        system_prompt_id = self.system_prompt_combo.currentData() or ""
        target_field = self.target_field_combo.currentText().strip()
        mode = self.mode_combo.currentData() or WRITE_MODE_OVERWRITE
        group_name = self.group_combo.currentText().strip()
        if not isinstance(prompt_id, str):
            return None
        return WorkflowDraft(
            name=name,
            query=query,
            model=str(model) or None,
            prompt_id=prompt_id,
            system_prompt_id=str(system_prompt_id) or None,
            target_field=target_field,
            mode=str(mode),
            group_name=group_name or None,
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

    def _populate_prompt_combo(self) -> None:
        selected_prompt_id = self.prompt_combo.currentData()
        self.prompt_combo.clear()
        for prompt in self._prompts:
            self.prompt_combo.addItem(prompt.name, prompt.prompt_id)
        if selected_prompt_id:
            index = self.prompt_combo.findData(selected_prompt_id)
            if index >= 0:
                self.prompt_combo.setCurrentIndex(index)

    def _populate_group_combo(self) -> None:
        self.group_combo.clear()
        self.group_combo.addItem("", "")
        for group in sorted(self._groups, key=lambda item: item.name.lower()):
            self.group_combo.addItem(group.name, group.group_id)
        if self._current_group_name:
            self.group_combo.setEditText(self._current_group_name)

    def _selected_prompt(self) -> PromptChoice | None:
        prompt_id = self.prompt_combo.currentData()
        for prompt in self._prompts:
            if prompt.prompt_id == prompt_id:
                return prompt
        return self._prompts[0] if self._prompts else None

    def _populate_system_prompt_combo(self) -> None:
        self.system_prompt_combo.clear()
        self.system_prompt_combo.addItem("Default system prompt", "")
        for prompt in self._system_prompts:
            self.system_prompt_combo.addItem(prompt.name, prompt.prompt_id)

    def _refresh_query_count(self) -> None:
        query = self.query_edit.toPlainText().strip()
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

    def _save_prompts(self) -> None:
        self._raw_config["saved_prompts"] = [
            {"id": prompt.prompt_id, "name": prompt.name, "prompt": prompt.prompt_text}
            for prompt in self._prompts
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
        if not draft.target_field:
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


def _common_fields_for_notes(note_ids: list[int]) -> list[str]:
    if mw is None or mw.col is None or not note_ids:
        return []

    field_sets: list[set[str]] = []
    for note_id in note_ids:
        note = mw.col.get_note(note_id)
        if note is None:
            continue
        field_sets.append(set(note.keys()))
    if not field_sets:
        return []
    return sorted(set.intersection(*field_sets))
