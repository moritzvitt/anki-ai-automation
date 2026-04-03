from __future__ import annotations

from aqt import mw
from aqt.operations import QueryOp
from aqt.qt import (
    QAction,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from aqt.utils import showCritical, showInfo

from ..core.audit_flow import apply_audit_run_result
from ..core.config import ConfigError, Pipeline, load_config
from ..core.pipelines import (
    PipelineRunResult,
    apply_pipeline_card_suspension,
    apply_pipeline_tag_update,
    execute_pipeline_by_id,
)
from ..core.workflow_engine import apply_field_tag_result
from ..core.workflow_engine import apply_field_update_result
from .tooltips import set_hover_help, show_tooltip


def register_pipeline_menu() -> None:
    if mw is None:
        return

    action = QAction("Run AI Pipeline", mw)
    action.triggered.connect(_open_pipeline_dialog)
    mw.form.menuTools.addAction(action)


def _open_pipeline_dialog() -> None:
    if mw is None:
        return
    try:
        dialog = PipelineManagerDialog(parent=mw)
    except ConfigError as error:
        showCritical(str(error), parent=mw)
        return
    dialog.exec()


class PipelineManagerDialog(QDialog):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Run AI Pipeline")
        self.resize(760, 500)

        self._config = load_config()
        self._pipelines = [pipeline for pipeline in self._config.pipelines if pipeline.enabled]
        self.pipeline_list = QListWidget()
        self.run_button = QPushButton("Run Pipeline")
        self._build_ui()
        self._populate()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        intro = QLabel(
            "Pipelines orchestrate note selection, audit/workflow steps, and conditional routing "
            "without overloading individual workflows or groups."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.pipeline_list.setMinimumHeight(280)
        set_hover_help(
            self.pipeline_list,
            "Config-defined pipelines. Each row shows the note selector and how many steps will run.",
            enabled=self._config.show_tooltips,
        )
        layout.addWidget(self.pipeline_list)

        button_row = QHBoxLayout()
        self.run_button.clicked.connect(self._run_selected_pipeline)
        set_hover_help(
            self.run_button,
            "Run the selected pipeline against the notes matched by its query.",
            enabled=self._config.show_tooltips,
        )
        button_row.addStretch(1)
        button_row.addWidget(self.run_button)
        layout.addLayout(button_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate(self) -> None:
        self.pipeline_list.clear()
        if not self._pipelines:
            item = QListWidgetItem("No enabled pipelines are configured yet.")
            self.pipeline_list.addItem(item)
            self.pipeline_list.setEnabled(False)
            self.run_button.setEnabled(False)
            return

        self.pipeline_list.setEnabled(True)
        self.run_button.setEnabled(True)
        for pipeline in self._pipelines:
            selector_limit = pipeline.note_selector.limit
            limit_summary = f" | Limit: {selector_limit}" if selector_limit is not None else ""
            item = QListWidgetItem(
                f"{pipeline.name}\n"
                f"Query: {pipeline.note_selector.query}{limit_summary}\n"
                f"Steps: {len(pipeline.steps)}"
            )
            item.setData(256, pipeline.pipeline_id)
            self.pipeline_list.addItem(item)
        self.pipeline_list.setCurrentRow(0)

    def _run_selected_pipeline(self) -> None:
        if mw is None:
            return
        current_item = self.pipeline_list.currentItem()
        if current_item is None:
            show_tooltip("Choose a pipeline first.", parent=self)
            return
        pipeline_id = current_item.data(256)
        if not isinstance(pipeline_id, str) or not pipeline_id:
            show_tooltip("Choose a runnable pipeline first.", parent=self)
            return

        pipeline = next((item for item in self._pipelines if item.pipeline_id == pipeline_id), None)
        if pipeline is None:
            showCritical("The selected pipeline could not be found in config.", parent=self)
            return

        self.setEnabled(False)
        op = QueryOp(
            parent=self,
            op=lambda _col: execute_pipeline_by_id(self._config, pipeline.pipeline_id),
            success=lambda result: self._on_pipeline_finished(pipeline, result),
        )
        op.with_progress(label=f"Running pipeline: {pipeline.name}")
        op.run_in_background()

    def _on_pipeline_finished(self, pipeline: Pipeline, result: PipelineRunResult) -> None:
        self.setEnabled(True)
        workflow_lookup = {workflow.workflow_id: workflow for workflow in self._config.workflows}
        for report in result.step_reports:
            for application in report.deferred_field_update_applications:
                apply_field_update_result(application)
            for application in report.deferred_field_tag_applications:
                apply_field_tag_result(application)
            for deferred in report.deferred_audit_applications:
                apply_audit_run_result(
                    deferred.result,
                    workflow=workflow_lookup.get(deferred.workflow_id),
                    config=self._config,
                    show_feedback=False,
                )
            for update in report.deferred_tag_updates:
                apply_pipeline_tag_update(update)
            for suspension in report.deferred_card_suspensions:
                apply_pipeline_card_suspension(suspension)
        success_count = sum(1 for context in result.contexts if not context.failures)
        failure_count = sum(1 for context in result.contexts if context.failures)
        show_tooltip(
            f"Pipeline '{pipeline.name}' finished for {len(result.selected_note_ids)} note(s).",
            parent=self,
        )

        lines = [
            f"Pipeline: {result.pipeline_name}",
            f"Selected notes: {len(result.selected_note_ids)}",
            f"Contexts without recorded failures: {success_count}",
            f"Contexts with failures: {failure_count}",
            "",
            "Step summary:",
        ]
        for report in result.step_reports:
            lines.append(
                f"- {report.step_id} ({report.step_type}): "
                f"{len(report.succeeded_note_ids)} succeeded, "
                f"{len(report.failed_note_ids)} failed, "
                f"{len(report.skipped_note_ids)} skipped"
            )
            for detail in report.details[:5]:
                lines.append(f"  - {detail}")
            if len(report.details) > 5:
                lines.append(f"  - ...and {len(report.details) - 5} more")

        context_failures = [
            f"- Note {context.note_id}: {failure}"
            for context in result.contexts
            for failure in context.failures[:3]
        ]
        if context_failures:
            lines.extend(["", "Note failures:"])
            lines.extend(context_failures[:20])
            if len(context_failures) > 20:
                lines.append(f"- ...and {len(context_failures) - 20} more")

        showInfo("\n".join(lines), parent=self)
