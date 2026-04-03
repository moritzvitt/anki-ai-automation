from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from aqt import mw
from aqt.operations import QueryOp
from aqt.qt import (
    QAction,
    QColor,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QPalette,
    QVBoxLayout,
    QWidget,
)
from aqt.utils import askUser, showCritical, showInfo

from .automation import PromptChoice
from .workflow_dialog import WorkflowDialog
from ..core.audit_flow import apply_audit_run_result
from ..core.config import (
    ConfigError,
    SavedPrompt,
    Workflow,
    WorkflowGroup,
    load_config,
    load_raw_config,
    save_workflow_state,
)
from ..core.workflow_engine import (
    WorkflowExecutionResult,
    apply_field_tag_result,
    apply_field_update_result,
    execute_workflow,
)
from .tooltips import set_hover_help


@dataclass
class WorkflowSequenceSummary:
    workflow_reports: list[str]
    failures: list[str]
    skipped: list[str]
    updated_requests: int = 0


_WORKFLOW_RUNNER_DIALOGS: list["WorkflowManagerDialog"] = []
_GROUP_FILTER_ENABLED_ONLY = "__enabled_only__"
_GROUP_FILTER_DISABLED_ONLY = "__disabled_only__"


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
            "uses a saved prompt, and performs one atomic action such as a field update or an audit."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        group_box = QGroupBox("Workflow Group")
        group_layout = QHBoxLayout(group_box)
        group_layout.addWidget(QLabel("Workflow group"))
        group_layout.addWidget(self.group_run_combo, stretch=1)
        set_hover_help(self.group_run_combo, "Filter the workflow list by group.", enabled=self._config.show_tooltips)
        self.group_run_combo.currentIndexChanged.connect(self._populate)
        run_group_button = QPushButton("Run Group")
        set_hover_help(run_group_button, "Run every workflow in the currently selected group, in order.", enabled=self._config.show_tooltips)
        run_group_button.clicked.connect(self._run_selected_group)
        group_layout.addWidget(run_group_button)
        layout.addWidget(group_box)

        layout.addWidget(QLabel("Workflows"))
        self.workflow_list.setMinimumHeight(320)
        set_hover_help(self.workflow_list, "Saved query-based workflows. Each row shows the query, workflow type, prompt, and core execution settings.", enabled=self._config.show_tooltips)
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
        selected_workflow = self._selected_workflow()
        selected_workflow_id = selected_workflow.workflow_id if selected_workflow is not None else None
        scroll_bar = self.workflow_list.verticalScrollBar()
        previous_scroll = scroll_bar.value() if scroll_bar is not None else 0
        selected_group_id = self.group_run_combo.currentData()
        self.group_run_combo.blockSignals(True)
        self.group_run_combo.clear()
        self.group_run_combo.addItem("All enabled workflows", _GROUP_FILTER_ENABLED_ONLY)
        self.group_run_combo.addItem("All disabled workflows", _GROUP_FILTER_DISABLED_ONLY)
        self.group_run_combo.addItem("All workflows", "")
        for group in self._groups:
            self.group_run_combo.addItem(group.name, group.group_id)
        if selected_group_id in (None, ""):
            selected_group_id = _GROUP_FILTER_ENABLED_ONLY
        if isinstance(selected_group_id, str):
            index = self.group_run_combo.findData(selected_group_id)
            if index >= 0:
                self.group_run_combo.setCurrentIndex(index)
        self.group_run_combo.blockSignals(False)

        current_group_id = self.group_run_combo.currentData()
        if current_group_id == _GROUP_FILTER_ENABLED_ONLY:
            self._visible_workflows = [workflow for workflow in self._workflows if workflow.enabled]
        elif current_group_id == _GROUP_FILTER_DISABLED_ONLY:
            self._visible_workflows = [workflow for workflow in self._workflows if not workflow.enabled]
        elif isinstance(current_group_id, str) and current_group_id:
            self._visible_workflows = [
                workflow for workflow in self._workflows if current_group_id in (workflow.group_ids or [])
            ]
        else:
            self._visible_workflows = list(self._workflows)

        self.workflow_list.clear()
        for index, workflow in enumerate(self._visible_workflows):
            item = QListWidgetItem()
            item.setBackground(self._workflow_row_background(index, enabled=workflow.enabled))
            self.workflow_list.addItem(item)
            row_widget = self._workflow_row_widget(workflow, index)
            item.setSizeHint(row_widget.sizeHint())
            self.workflow_list.setItemWidget(item, row_widget)

        if selected_workflow_id is not None:
            self._select_workflow_by_id(selected_workflow_id)
        if scroll_bar is not None:
            scroll_bar.setValue(previous_scroll)

    def _workflow_row_background(self, index: int, *, enabled: bool = True) -> QColor:
        palette = self.workflow_list.palette()
        base = palette.color(QPalette.ColorRole.Base)
        warm_accent = QColor("#dba95a")
        cool_accent = QColor("#66a88f")
        accent = warm_accent if index % 2 == 0 else cool_accent

        # Keep the alternating rows easy to scan while respecting the active Anki theme.
        blend_ratio = 0.12 if base.lightness() < 128 else 0.20
        background = _blend_colors(base, accent, blend_ratio)
        if enabled:
            return background
        # Disabled rows stay striped, but fade a little back toward the base color.
        return _blend_colors(background, base, 0.58)

    def _workflow_preview(self, workflow: Workflow) -> str:
        prompt_name = self._prompt_name(workflow.prompt_id)
        group_names = self._group_names(workflow.group_ids)
        group_summary = ", ".join(group_names) if group_names else "No groups"
        trigger_summary = _trigger_summary(workflow)
        type_summary = "Audit" if workflow.workflow_type == "audit" else "Field update"
        target_summary = (
            f"Schema: {workflow.schema_preset or 'custom'}"
            if workflow.workflow_type == "audit"
            else (
                workflow.target_field if not workflow.multiple_target_fields else "Delimited multi-field mode"
            )
        )
        return (
            f"{workflow.name}\n"
            f"Query: {workflow.query}\n"
            f"Enabled: {'Yes' if workflow.enabled else 'No'} | Type: {type_summary} | Prompt: {prompt_name} | Target: {target_summary} | "
            f"Mode: {workflow.mode} | Model: {workflow.model or self._config.model} | "
            f"Temp: {workflow.temperature if workflow.temperature is not None else 'global'} | "
            f"System: {self._system_prompt_name(workflow.system_prompt_id)} | "
            f"Markdown->HTML: {'Yes' if workflow.convert_markdown_to_html else 'No'} | "
            f"Delimiter: {workflow.response_delimiter or '-'} | Trigger: {trigger_summary} | Groups: {group_summary}"
        )

    def _workflow_row_widget(self, workflow: Workflow, index: int) -> QWidget:
        row = QWidget(self.workflow_list)
        background = self._workflow_row_background(index, enabled=workflow.enabled)
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row.setStyleSheet(
            f"background-color: {background.name()}; border-radius: 6px;"
        )

        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        enabled_check = QCheckBox("Enabled")
        enabled_check.setChecked(workflow.enabled)
        enabled_check.setToolTip("Toggle whether this workflow is active without opening the editor.")
        enabled_check.stateChanged.connect(
            lambda _state, workflow_id=workflow.workflow_id: self._toggle_workflow_enabled(workflow_id)
        )
        layout.addWidget(enabled_check, alignment=Qt.AlignmentFlag.AlignTop)

        preview = QLabel(self._workflow_preview(workflow))
        preview.setWordWrap(True)
        preview.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        preview_palette = preview.palette()
        if workflow.enabled:
            preview.setStyleSheet("font-weight: 500;")
        else:
            muted_text = _blend_colors(
                preview_palette.color(QPalette.ColorRole.WindowText),
                self.workflow_list.palette().color(QPalette.ColorRole.Base),
                0.42,
            )
            preview_palette.setColor(QPalette.ColorRole.WindowText, muted_text)
            preview.setPalette(preview_palette)
            preview.setStyleSheet("font-weight: 400;")
        layout.addWidget(preview, stretch=1)

        return row

    def _toggle_workflow_enabled(self, workflow_id: str) -> None:
        for index, workflow in enumerate(self._workflows):
            if workflow.workflow_id != workflow_id:
                continue
            self._workflows[index] = replace(workflow, enabled=not workflow.enabled)
            self._save_state()
            return

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
        ordered_groups = sorted(self._groups, key=lambda group: group.name.lower())
        ordered_workflows = [
            replace(workflow, position=index)
            for index, workflow in enumerate(self._workflows)
        ]
        save_workflow_state(self._raw_config, ordered_groups, ordered_workflows)
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
            workflow_type=draft.workflow_type,
            enabled=draft.enabled,
            prompt_id=draft.prompt_id,
            target_field=draft.target_field,
            mode=draft.mode,
            model=draft.model,
            temperature=draft.temperature,
            api_mode=draft.api_mode,
            system_prompt_id=draft.system_prompt_id,
            multiple_target_fields=draft.multiple_target_fields,
            convert_markdown_to_html=draft.convert_markdown_to_html,
            response_delimiter=draft.response_delimiter,
            schema_preset=draft.schema_preset,
            success_tags=draft.success_tags,
            failure_tags=draft.failure_tags,
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
            workflow_type=draft.workflow_type,
            enabled=draft.enabled,
            prompt_id=draft.prompt_id,
            target_field=draft.target_field,
            mode=draft.mode,
            model=draft.model,
            temperature=draft.temperature,
            api_mode=draft.api_mode,
            system_prompt_id=draft.system_prompt_id,
            multiple_target_fields=draft.multiple_target_fields,
            convert_markdown_to_html=draft.convert_markdown_to_html,
            response_delimiter=draft.response_delimiter,
            schema_preset=draft.schema_preset,
            success_tags=draft.success_tags,
            failure_tags=draft.failure_tags,
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
        if not workflow.enabled:
            show_tooltip("Enable the workflow before running it.", parent=self)
            return
        self._run_workflow_sequence([workflow], run_label=workflow.name)

    def _run_selected_group(self) -> None:
        group_id = self.group_run_combo.currentData()
        if not isinstance(group_id, str) or not group_id:
            show_tooltip("Choose a workflow group to run.", parent=self)
            return
        workflows = [workflow for workflow in self._workflows if workflow.enabled and group_id in (workflow.group_ids or [])]
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
            if workflow.prompt_id not in prompt_lookup and workflow.workflow_type != "audit":
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
        if workflow.workflow_type != "audit" and prompt_lookup.get(workflow.prompt_id) is None:
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

        op = QueryOp(
            parent=self,
            op=lambda _col: execute_workflow(config, workflow, note_ids=note_ids, show_feedback=False),
            success=lambda result: self._on_workflow_finished(
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
        op.with_progress(label=f"Running workflow {index + 1}/{len(workflows)}: {workflow.name}")
        op.run_in_background()

    def _on_workflow_finished(
        self,
        *,
        workflows: list[Workflow],
        index: int,
        config,
        prompt_lookup: dict[str, SavedPrompt],
        summary: WorkflowSequenceSummary,
        workflow: Workflow,
        result: WorkflowExecutionResult,
        show_summary_dialog: bool,
        on_done: Callable[[WorkflowSequenceSummary], None] | None,
    ) -> None:
        for application in result.deferred_field_update_applications:
            apply_field_update_result(application)
        for application in result.deferred_field_tag_applications:
            apply_field_tag_result(application)
        for deferred in result.deferred_audit_applications:
            apply_audit_run_result(
                deferred.result,
                workflow=workflow,
                config=config,
                show_feedback=False,
            )
        summary.updated_requests += result.updated_requests
        summary.workflow_reports.append(
            f"{workflow.name}: {len(result.succeeded_note_ids)} processed, {len(result.failed_note_ids) + len(result.skipped_note_ids)} skipped."
        )
        summary.failures.extend([f"- Workflow '{workflow.name}' {failure}" for failure in result.failures])
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


def _blend_colors(base: QColor, accent: QColor, ratio: float) -> QColor:
    ratio = max(0.0, min(1.0, ratio))
    inverse = 1.0 - ratio
    return QColor(
        round((base.red() * inverse) + (accent.red() * ratio)),
        round((base.green() * inverse) + (accent.green() * ratio)),
        round((base.blue() * inverse) + (accent.blue() * ratio)),
    )


def _trigger_summary(workflow: Workflow) -> str:
    trigger_events: list[str] = []
    if workflow.trigger_on_startup:
        trigger_events.append("startup")
    if workflow.trigger_on_periodic:
        trigger_events.append("monitor")
    if not trigger_events:
        return "manual only"
    return f"{', '.join(trigger_events)} when query matches >= {workflow.trigger_min_matches}"
