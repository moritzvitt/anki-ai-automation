from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from aqt import mw
from aqt.qt import (
    QAction,
    QCheckBox,
    QColor,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QPalette,
    QVBoxLayout,
    QWidget,
)
from aqt.utils import askUser, showCritical, showInfo

from .automation import (
    ProcessingPresetChoice,
    PromptChoice,
    SavedPromptDialog,
    _preset_choices_from_saved_processing_presets,
)
from ..core.config import (
    ConfigError,
    ProcessingPreset,
    SavedPrompt,
    Workflow,
    WorkflowGroup,
    load_config,
    load_raw_config,
    new_object_id,
    save_raw_config,
)
from ..services.model_catalog import fallback_model_options
from ..core.processing import (
    ManualProcessingSpec,
    ProcessingResult,
    WRITE_MODE_APPEND,
    WRITE_MODE_OVERWRITE,
    WRITE_MODE_SKIP_NONEMPTY,
    prepare_manual_ai_processing,
    start_prepared_manual_processing,
)
from .tooltips import set_hover_help, show_tooltip


@dataclass(frozen=True)
class WorkflowDraft:
    name: str
    query: str
    prompt_id: str
    target_field: str
    mode: str
    model: str | None
    temperature: float | None
    system_prompt_id: str | None
    multiple_target_fields: bool
    convert_markdown_to_html: bool
    response_delimiter: str | None
    trigger_on_startup: bool
    trigger_on_periodic: bool
    trigger_min_matches: int
    group_names: list[str]


@dataclass
class WorkflowSequenceSummary:
    workflow_reports: list[str]
    failures: list[str]
    skipped: list[str]
    updated_requests: int = 0


_WORKFLOW_RUNNER_DIALOGS: list["WorkflowManagerDialog"] = []


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
        self._visible_workflows: list[Workflow] = []

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
        set_hover_help(self.group_run_combo, "Filter the workflow list by group, or choose a group to run all of its workflows.", enabled=self._config.show_tooltips)
        self.group_run_combo.currentIndexChanged.connect(self._populate)
        run_group_button = QPushButton("Run Group")
        set_hover_help(run_group_button, "Run every workflow in the currently selected group, in order.", enabled=self._config.show_tooltips)
        run_group_button.clicked.connect(self._run_selected_group)
        group_layout.addWidget(run_group_button)
        layout.addWidget(group_box)

        layout.addWidget(QLabel("Workflows"))
        self.workflow_list.setMinimumHeight(320)
        set_hover_help(self.workflow_list, "Saved query-based workflows. Each row shows the query, prompt, target field, and run mode.", enabled=self._config.show_tooltips)
        layout.addWidget(self.workflow_list)

        button_row = QHBoxLayout()
        add_button = QPushButton("Add")
        edit_button = QPushButton("Edit")
        delete_button = QPushButton("Delete")
        duplicate_button = QPushButton("Duplicate")
        move_up_button = QPushButton("Move Up")
        move_down_button = QPushButton("Move Down")
        run_button = QPushButton("Run Workflow")
        set_hover_help(add_button, "Create a new workflow.", enabled=self._config.show_tooltips)
        set_hover_help(edit_button, "Edit the selected workflow.", enabled=self._config.show_tooltips)
        set_hover_help(delete_button, "Delete the selected workflow.", enabled=self._config.show_tooltips)
        set_hover_help(duplicate_button, "Create a copy of the selected workflow.", enabled=self._config.show_tooltips)
        set_hover_help(move_up_button, "Move the selected workflow earlier in the run order.", enabled=self._config.show_tooltips)
        set_hover_help(move_down_button, "Move the selected workflow later in the run order.", enabled=self._config.show_tooltips)
        set_hover_help(run_button, "Run only the currently selected workflow.", enabled=self._config.show_tooltips)
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
        self._presets = _preset_choices_from_saved_processing_presets(self._config.processing_presets)
        self._groups = sorted(self._config.workflow_groups, key=lambda group: group.name.lower())
        self._workflows = sorted(self._config.workflows, key=lambda workflow: workflow.position)

    def _populate(self) -> None:
        selected_group_id = self.group_run_combo.currentData()
        self.group_run_combo.blockSignals(True)
        self.group_run_combo.clear()
        self.group_run_combo.addItem("All workflows", "")
        for group in self._groups:
            self.group_run_combo.addItem(group.name, group.group_id)
        if isinstance(selected_group_id, str):
            index = self.group_run_combo.findData(selected_group_id)
            if index >= 0:
                self.group_run_combo.setCurrentIndex(index)
        self.group_run_combo.blockSignals(False)

        current_group_id = self.group_run_combo.currentData()
        if isinstance(current_group_id, str) and current_group_id:
            self._visible_workflows = [
                workflow for workflow in self._workflows if current_group_id in (workflow.group_ids or [])
            ]
        else:
            self._visible_workflows = list(self._workflows)

        self.workflow_list.clear()
        for index, workflow in enumerate(self._visible_workflows):
            item = QListWidgetItem(self._workflow_preview(workflow))
            item.setBackground(self._workflow_row_background(index))
            self.workflow_list.addItem(item)

    def _workflow_row_background(self, index: int) -> QColor:
        palette = self.workflow_list.palette()
        base = palette.color(QPalette.ColorRole.Base)
        warm_accent = QColor("#dba95a")
        cool_accent = QColor("#66a88f")
        accent = warm_accent if index % 2 == 0 else cool_accent

        # Keep the alternating rows visible while respecting the active Anki theme.
        blend_ratio = 0.16 if base.lightness() < 128 else 0.32
        return _blend_colors(base, accent, blend_ratio)

    def _workflow_preview(self, workflow: Workflow) -> str:
        prompt_name = self._prompt_name(workflow.prompt_id)
        group_names = self._group_names(workflow.group_ids)
        group_summary = ", ".join(group_names) if group_names else "No groups"
        trigger_summary = _trigger_summary(workflow)
        return (
            f"{workflow.name}\n"
            f"Query: {workflow.query}\n"
            f"Prompt: {prompt_name} | Target: "
            f"{workflow.target_field if not workflow.multiple_target_fields else 'Delimited multi-field mode'} | "
            f"Mode: {workflow.mode} | Model: {workflow.model or self._config.model} | "
            f"Temp: {workflow.temperature if workflow.temperature is not None else 'global'} | "
            f"System: {self._system_prompt_name(workflow.system_prompt_id)} | "
            f"Markdown->HTML: {'Yes' if workflow.convert_markdown_to_html else 'No'} | "
            f"Delimiter: {workflow.response_delimiter or '-'} | Trigger: {trigger_summary} | Groups: {group_summary}"
        )

    def _prompt_name(self, prompt_id: str) -> str:
        for prompt in self._prompts:
            if prompt.prompt_id == prompt_id:
                return prompt.name
        return "Missing prompt"

    def _group_names(self, group_ids: list[str] | None) -> list[str]:
        if not group_ids:
            return []
        name_lookup = {group.group_id: group.name for group in self._groups}
        return [name_lookup[group_id] for group_id in group_ids if group_id in name_lookup]

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
                "temperature": workflow.temperature,
                "system_prompt_id": workflow.system_prompt_id,
                "multiple_target_fields": workflow.multiple_target_fields,
                "convert_markdown_to_html": workflow.convert_markdown_to_html,
                "response_delimiter": workflow.response_delimiter,
                "trigger_on_startup": workflow.trigger_on_startup,
                "trigger_on_periodic": workflow.trigger_on_periodic,
                "trigger_min_matches": workflow.trigger_min_matches,
                "group_ids": workflow.group_ids or [],
                "group_id": (workflow.group_ids or [None])[0],
                "position": index,
            }
            for index, workflow in enumerate(self._workflows)
        ]
        save_raw_config(self._raw_config)
        self._load_state()
        self._populate()

    def _selected_workflow_index(self) -> int:
        return self.workflow_list.currentRow()

    def _selected_workflow(self) -> Workflow | None:
        row = self._selected_workflow_index()
        if row < 0 or row >= len(self._visible_workflows):
            return None
        return self._visible_workflows[row]

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
            temperature=draft.temperature,
            system_prompt_id=draft.system_prompt_id,
            multiple_target_fields=draft.multiple_target_fields,
            convert_markdown_to_html=draft.convert_markdown_to_html,
            response_delimiter=draft.response_delimiter,
            trigger_on_startup=draft.trigger_on_startup,
            trigger_on_periodic=draft.trigger_on_periodic,
            trigger_min_matches=draft.trigger_min_matches,
            group_ids=self._group_ids_for_names(draft.group_names),
            position=len(self._workflows),
        )
        self._workflows.append(workflow)
        self._save_state()
        self._select_workflow_by_id(workflow.workflow_id)

    def _edit_workflow(self) -> None:
        workflow = self._selected_workflow()
        if workflow is None:
            return
        row = self._workflows.index(workflow)
        dialog = WorkflowDialog(
            parent=self,
            prompts=self._prompts,
            system_prompts=self._system_prompts,
            groups=self._groups,
            current_model=self._config.model,
            model_pricing=self._config.model_pricing,
            workflow=workflow,
            current_group_names=self._group_names(workflow.group_ids),
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
            temperature=draft.temperature,
            system_prompt_id=draft.system_prompt_id,
            multiple_target_fields=draft.multiple_target_fields,
            convert_markdown_to_html=draft.convert_markdown_to_html,
            response_delimiter=draft.response_delimiter,
            trigger_on_startup=draft.trigger_on_startup,
            trigger_on_periodic=draft.trigger_on_periodic,
            trigger_min_matches=draft.trigger_min_matches,
            group_ids=self._group_ids_for_names(draft.group_names),
        )
        self._save_state()
        self._select_workflow_by_id(workflow.workflow_id)

    def _delete_workflow(self) -> None:
        workflow = self._selected_workflow()
        if workflow is None:
            return
        row = self._workflows.index(workflow)
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

    def _duplicate_workflow(self) -> None:
        workflow = self._selected_workflow()
        if workflow is None:
            show_tooltip("Select a workflow to duplicate.", parent=self)
            return

        row = self._workflows.index(workflow)
        duplicate = replace(
            workflow,
            workflow_id=new_object_id("workflow"),
            name=f"{workflow.name} Copy",
            position=len(self._workflows),
        )
        self._workflows.insert(row + 1, duplicate)
        self._save_state()
        self._select_workflow_by_id(duplicate.workflow_id)

    def _move_selected_up(self) -> None:
        workflow = self._selected_workflow()
        if workflow is None:
            return
        row = self._workflows.index(workflow)
        if row <= 0 or row >= len(self._workflows):
            return
        self._workflows[row - 1], self._workflows[row] = self._workflows[row], self._workflows[row - 1]
        self._save_state()
        self._select_workflow_by_id(workflow.workflow_id)

    def _move_selected_down(self) -> None:
        workflow = self._selected_workflow()
        if workflow is None:
            return
        row = self._workflows.index(workflow)
        if row < 0 or row >= len(self._workflows) - 1:
            return
        self._workflows[row + 1], self._workflows[row] = self._workflows[row], self._workflows[row + 1]
        self._save_state()
        self._select_workflow_by_id(workflow.workflow_id)

    def _run_selected_workflow(self) -> None:
        workflow = self._selected_workflow()
        if workflow is None:
            show_tooltip("Select a workflow to run.", parent=self)
            return
        self._run_workflow_sequence([workflow], run_label=workflow.name)

    def _run_selected_group(self) -> None:
        group_id = self.group_run_combo.currentData()
        if not isinstance(group_id, str) or not group_id:
            show_tooltip("Choose a workflow group to run.", parent=self)
            return
        workflows = [workflow for workflow in self._workflows if group_id in (workflow.group_ids or [])]
        if not workflows:
            show_tooltip("This group does not contain any workflows.", parent=self)
            return
        group_name = self._group_names([group_id])[0] if self._group_names([group_id]) else "Selected group"
        self._run_workflow_sequence(workflows, run_label=group_name)

    def _run_workflow_sequence(
        self,
        workflows: list[Workflow],
        *,
        run_label: str,
        show_summary_dialog: bool = True,
        require_confirmation: bool = True,
        on_done: Callable[[WorkflowSequenceSummary], None] | None = None,
    ) -> None:
        try:
            config = load_config()
        except ConfigError as error:
            showCritical(str(error), parent=self)
            return

        if not config.enabled:
            show_tooltip("AI Automation is disabled in the add-on config.", parent=self)
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

        if require_confirmation:
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
            show_summary_dialog=show_summary_dialog,
            on_done=on_done,
        )

    def _run_workflow_at_index(
        self,
        *,
        workflows: list[Workflow],
        index: int,
        config,
        prompt_lookup: dict[str, SavedPrompt],
        summary: WorkflowSequenceSummary,
        show_summary_dialog: bool,
        on_done: Callable[[WorkflowSequenceSummary], None] | None,
    ) -> None:
        # Workflows intentionally run one after another so later workflows can
        # safely build on fields updated by earlier ones on the same notes.
        if index >= len(workflows):
            self.setEnabled(True)
            self._show_workflow_sequence_summary(summary, show_dialog=show_summary_dialog)
            if on_done is not None:
                on_done(summary)
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
                show_summary_dialog=show_summary_dialog,
                on_done=on_done,
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
                show_summary_dialog=show_summary_dialog,
                on_done=on_done,
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
                show_summary_dialog=show_summary_dialog,
                on_done=on_done,
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
            temperature=workflow.temperature,
            multiple_target_fields=workflow.multiple_target_fields,
            convert_markdown_to_html=workflow.convert_markdown_to_html,
            response_delimiter=workflow.response_delimiter or "",
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
                show_summary_dialog=show_summary_dialog,
                on_done=on_done,
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
                show_summary_dialog=show_summary_dialog,
                on_done=on_done,
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
        show_summary_dialog: bool,
        on_done: Callable[[WorkflowSequenceSummary], None] | None,
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
        if result.was_cancelled:
            summary.skipped.append(
                f"- Interrupted while running '{workflow.name}'. Remaining workflows were not started."
            )
            self.setEnabled(True)
            self._show_workflow_sequence_summary(summary, show_dialog=show_summary_dialog)
            if on_done is not None:
                on_done(summary)
            return
        self._run_workflow_at_index(
            workflows=workflows,
            index=index + 1,
            config=config,
            prompt_lookup=prompt_lookup,
            summary=summary,
            show_summary_dialog=show_summary_dialog,
            on_done=on_done,
        )

    def _show_workflow_sequence_summary(self, summary: WorkflowSequenceSummary, *, show_dialog: bool = True) -> None:
        if summary.updated_requests:
            show_tooltip(
                f"AI Automation ran workflows and sent {summary.updated_requests} request(s).",
                parent=self,
            )
        elif not summary.failures and not summary.skipped:
            show_tooltip("No workflows ran.", parent=self)

        if not show_dialog:
            return
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

    def _group_ids_for_names(self, group_names: list[str]) -> list[str]:
        resolved_group_ids: list[str] = []
        seen_names: set[str] = set()
        for group_name in group_names:
            normalized = group_name.strip()
            if not normalized or normalized.lower() in seen_names:
                continue
            seen_names.add(normalized.lower())
            existing_group = next((group for group in self._groups if group.name == normalized), None)
            if existing_group is not None:
                resolved_group_ids.append(existing_group.group_id)
                continue
            new_group = WorkflowGroup(group_id=new_object_id("group"), name=normalized)
            self._groups.append(new_group)
            self._groups.sort(key=lambda group: group.name.lower())
            resolved_group_ids.append(new_group.group_id)
        return resolved_group_ids

    def _remove_unused_groups(self) -> None:
        used_group_ids = {group_id for workflow in self._workflows for group_id in (workflow.group_ids or [])}
        self._groups = [group for group in self._groups if group.group_id in used_group_ids]

    def _select_workflow_by_id(self, workflow_id: str) -> None:
        for index, workflow in enumerate(self._visible_workflows):
            if workflow.workflow_id == workflow_id:
                self.workflow_list.setCurrentRow(index)
                return

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
        current_group_names: list[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Workflow")
        self.resize(720, 560)

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
        self.query_edit = QPlainTextEdit()
        self.query_count_label = QLabel("Click Refresh Count to check the query.")
        self.model_combo = QComboBox()
        self.use_global_temperature_check = QCheckBox("Use global temperature")
        self.temperature_spin = QDoubleSpinBox()
        self.preset_combo = QComboBox()
        self.prompt_combo = QComboBox()
        self.system_prompt_combo = QComboBox()
        self.prompt_preview = QPlainTextEdit()
        self.prompt_preview.setMinimumHeight(140)
        self.system_prompt_preview = QPlainTextEdit()
        self.system_prompt_preview.setMinimumHeight(120)
        self.multiple_target_fields_check = QCheckBox("Multiple target fields")
        self.convert_markdown_to_html_check = QCheckBox("Convert Markdown to HTML")
        self.delimiter_edit = QLineEdit()
        self.target_field_combo = QComboBox()
        self.target_field_combo.setEditable(True)
        self.mode_combo = QComboBox()
        self.trigger_on_startup_check = QCheckBox("Run automatically on startup")
        self.trigger_on_periodic_check = QCheckBox("Run automatically when the condition becomes true")
        self.trigger_min_matches_spin = QSpinBox()
        self.group_edit = QLineEdit()

        self._build_ui()
        self._populate(workflow)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.query_edit.setMinimumHeight(96)
        set_hover_help(self.name_edit, "Friendly workflow name shown in the manager and run confirmations.", enabled=self._show_tooltips)
        set_hover_help(self.query_edit, "Anki Browser search query used to find notes for this workflow.", enabled=self._show_tooltips)
        set_hover_help(self.query_count_label, "Shows how many notes currently match the workflow query.", enabled=self._show_tooltips)

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
        preset_row = QWidget()
        preset_layout = QHBoxLayout(preset_row)
        preset_layout.setContentsMargins(0, 0, 0, 0)
        preset_layout.addWidget(self.preset_combo, stretch=1)
        save_preset_button = QPushButton("Save")
        update_preset_button = QPushButton("Update")
        delete_preset_button = QPushButton("Delete")
        set_hover_help(self.preset_combo, "Load a saved processing preset into this workflow.", enabled=self._show_tooltips)
        set_hover_help(save_preset_button, "Save the current workflow processing settings as a reusable preset.", enabled=self._show_tooltips)
        set_hover_help(update_preset_button, "Overwrite the selected preset with the current workflow settings.", enabled=self._show_tooltips)
        set_hover_help(delete_preset_button, "Delete the selected processing preset.", enabled=self._show_tooltips)
        save_preset_button.clicked.connect(self._save_current_as_preset)
        update_preset_button.clicked.connect(self._update_selected_preset)
        delete_preset_button.clicked.connect(self._delete_selected_preset)
        preset_layout.addWidget(save_preset_button)
        preset_layout.addWidget(update_preset_button)
        preset_layout.addWidget(delete_preset_button)
        set_hover_help(self.model_combo, "Model used by this workflow. Leave it on the current selection to follow the global default.", enabled=self._show_tooltips)
        set_hover_help(self.use_global_temperature_check, "Use the global temperature from settings instead of a workflow-specific value.", enabled=self._show_tooltips)
        set_hover_help(self.temperature_spin, "Lower values are steadier; higher values allow more variation.", enabled=self._show_tooltips)
        set_hover_help(self.multiple_target_fields_check, "Expect delimited response sections that map to multiple note fields.", enabled=self._show_tooltips)
        set_hover_help(self.convert_markdown_to_html_check, "Convert generated Markdown to HTML before saving it back into notes.", enabled=self._show_tooltips)
        set_hover_help(self.delimiter_edit, "Delimiter used for multi-field responses, for example --Notes-- or --{field}--.", enabled=self._show_tooltips)
        set_hover_help(self.target_field_combo, "Single note field to update when multi-field mode is off.", enabled=self._show_tooltips)
        set_hover_help(self.mode_combo, "Choose whether the workflow overwrites, appends, or skips already-filled target fields.", enabled=self._show_tooltips)
        set_hover_help(self.prompt_preview, "Editable text of the selected user prompt. Changes are saved back to that prompt.", enabled=self._show_tooltips)
        set_hover_help(self.system_prompt_preview, "Editable text of the selected system prompt. Changes are saved back to that prompt.", enabled=self._show_tooltips)
        set_hover_help(self.trigger_on_startup_check, "Run this workflow automatically when Anki opens the profile, if the query match threshold is met.", enabled=self._show_tooltips)
        set_hover_help(self.trigger_on_periodic_check, "Keep checking this workflow in the background and run it when the condition changes from not met to met.", enabled=self._show_tooltips)
        set_hover_help(self.trigger_min_matches_spin, "Minimum number of notes matching the workflow query before the automatic trigger can fire.", enabled=self._show_tooltips)
        set_hover_help(self.group_edit, "Optional comma-separated workflow groups used to organize and batch-run related workflows.", enabled=self._show_tooltips)
        form.addRow("Preset", preset_row)
        form.addRow("Model", self.model_combo)
        temperature_row = QWidget()
        temperature_layout = QHBoxLayout(temperature_row)
        temperature_layout.setContentsMargins(0, 0, 0, 0)
        temperature_layout.addWidget(self.use_global_temperature_check)
        temperature_layout.addWidget(self.temperature_spin)
        form.addRow("Temperature", temperature_row)
        form.addRow("Prompt", prompt_row)
        form.addRow("System prompt", system_prompt_row)
        form.addRow("", self.multiple_target_fields_check)
        form.addRow("", self.convert_markdown_to_html_check)
        form.addRow("Response delimiter", self.delimiter_edit)
        form.addRow("Target field", self.target_field_combo)
        form.addRow("Mode", self.mode_combo)
        form.addRow("", self.trigger_on_startup_check)
        form.addRow("", self.trigger_on_periodic_check)
        form.addRow("Trigger min matches", self.trigger_min_matches_spin)
        form.addRow("Groups", self.group_edit)
        layout.addLayout(form)
        layout.addWidget(QLabel("Prompt"))
        layout.addWidget(self.prompt_preview)
        layout.addWidget(QLabel("System prompt"))
        layout.addWidget(self.system_prompt_preview)

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
        self._populate_group_edit()
        self._refresh_prompt_preview()
        self._refresh_system_prompt_preview()
        self._refresh_target_mode_ui()
        self._refresh_temperature_ui()

        if workflow is None:
            return

        self.name_edit.setText(workflow.name)
        self.query_edit.setPlainText(workflow.query)
        self.target_field_combo.setEditText(workflow.target_field)
        self.multiple_target_fields_check.setChecked(workflow.multiple_target_fields)
        self.convert_markdown_to_html_check.setChecked(workflow.convert_markdown_to_html)
        self._set_temperature(workflow.temperature)
        self.delimiter_edit.setText(workflow.response_delimiter or "")
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
        self._refresh_prompt_preview()
        self._refresh_system_prompt_preview()
        self._refresh_target_mode_ui()
        self._refresh_query_count()

    def workflow_draft(self) -> WorkflowDraft | None:
        name = self.name_edit.text().strip()
        query = self.query_edit.toPlainText().strip()
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
            model=str(model) or None,
            temperature=self._selected_temperature(),
            prompt_id=prompt_id,
            system_prompt_id=str(system_prompt_id) or None,
            target_field="" if self.multiple_target_fields_check.isChecked() else target_field,
            mode=str(mode),
            multiple_target_fields=self.multiple_target_fields_check.isChecked(),
            convert_markdown_to_html=self.convert_markdown_to_html_check.isChecked(),
            response_delimiter=self.delimiter_edit.text().strip() or None,
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
        return ProcessingPresetChoice(
            preset_id=preset_id,
            name=name,
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
        self._raw_config["saved_prompts"] = [
            {"id": prompt.prompt_id, "name": prompt.name, "prompt": prompt.prompt_text}
            for prompt in self._prompts
        ]
        save_raw_config(self._raw_config)

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


def run_workflows_background(
    parent: QWidget,
    workflows: list[Workflow],
    *,
    run_label: str,
    show_summary_dialog: bool = False,
    on_done: Callable[[WorkflowSequenceSummary], None] | None = None,
) -> None:
    if mw is None:
        return
    try:
        dialog = WorkflowManagerDialog(parent=parent)
    except ConfigError as error:
        showCritical(str(error), parent=parent)
        return

    _WORKFLOW_RUNNER_DIALOGS.append(dialog)

    def finish(summary: WorkflowSequenceSummary) -> None:
        if dialog in _WORKFLOW_RUNNER_DIALOGS:
            _WORKFLOW_RUNNER_DIALOGS.remove(dialog)
        dialog.deleteLater()
        if on_done is not None:
            on_done(summary)

    dialog._run_workflow_sequence(
        workflows,
        run_label=run_label,
        show_summary_dialog=show_summary_dialog,
        require_confirmation=False,
        on_done=finish,
    )


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


def _blend_colors(base: QColor, accent: QColor, ratio: float) -> QColor:
    ratio = max(0.0, min(1.0, ratio))
    inverse = 1.0 - ratio
    return QColor(
        round((base.red() * inverse) + (accent.red() * ratio)),
        round((base.green() * inverse) + (accent.green() * ratio)),
        round((base.blue() * inverse) + (accent.blue() * ratio)),
    )


def _parse_group_names(value: str) -> list[str]:
    parsed_names: list[str] = []
    seen_names: set[str] = set()
    for raw_name in value.split(","):
        normalized = raw_name.strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen_names:
            continue
        seen_names.add(key)
        parsed_names.append(normalized)
    return parsed_names


def _trigger_summary(workflow: Workflow) -> str:
    trigger_events: list[str] = []
    if workflow.trigger_on_startup:
        trigger_events.append("startup")
    if workflow.trigger_on_periodic:
        trigger_events.append("monitor")
    if not trigger_events:
        return "manual only"
    return f"{', '.join(trigger_events)} when query matches >= {workflow.trigger_min_matches}"
