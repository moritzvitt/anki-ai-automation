from __future__ import annotations

from dataclasses import dataclass

from aqt.qt import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTimer, QVBoxLayout, QWidget

from ..services.openai_client import TokenUsage
from .. import shared_styling


WRITE_MODE_APPEND = "append"
WRITE_MODE_OVERWRITE = "overwrite"
WRITE_MODE_SKIP_NONEMPTY = "skip_nonempty"


@dataclass(frozen=True)
class NoteSnapshot:
    note_id: int
    note_type_name: str
    fields: dict[str, str]
    output_fields: list[str]
    prompt_template: str
    system_prompt: str
    write_mode: str = WRITE_MODE_OVERWRITE
    multiple_target_fields: bool = False
    convert_markdown_to_html: bool = False
    convert_field_html_to_markdown: bool = False
    response_delimiter: str = ""


@dataclass(frozen=True)
class NoteUpdate:
    note_id: int
    output_fields: dict[str, str]
    usage: TokenUsage
    estimated_cost_usd: float | None
    write_mode: str = WRITE_MODE_OVERWRITE
    convert_markdown_to_html: bool = False


@dataclass(frozen=True)
class NoteFailure:
    note_id: int
    note_type_name: str
    reason: str


@dataclass(frozen=True)
class ProcessingResult:
    updates: list[NoteUpdate]
    failures: list[NoteFailure]
    was_cancelled: bool = False


@dataclass(frozen=True)
class ProcessingEstimate:
    input_tokens: int
    estimated_output_tokens: int
    estimated_total_tokens: int
    estimated_cost_usd: float | None
    heuristic_notes: int
    pricing_available: bool


@dataclass(frozen=True)
class ManualProcessingSpec:
    prompt_name: str
    prompt_template: str
    target_field: str
    system_prompt_name: str = ""
    system_prompt: str = ""
    write_mode: str = WRITE_MODE_OVERWRITE
    model: str = ""
    temperature: float | None = None
    multiple_target_fields: bool = False
    convert_markdown_to_html: bool = False
    convert_field_html_to_markdown: bool = False
    response_delimiter: str = ""


@dataclass(frozen=True)
class PreparedManualProcessing:
    snapshots: list[NoteSnapshot]
    failures: list[NoteFailure]
    overwrite_count: int
    overwrite_fields: set[str]
    estimate: ProcessingEstimate | None


@dataclass(frozen=True)
class PromptRenderPlan:
    prompt_template: str
    prompt_fields: tuple[str, ...]


class ProcessingInterruptDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        *,
        note_count: int,
        window_title: str = "AI Processing",
        action_label: str = "Processing",
        can_interrupt: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(window_title)
        self.setModal(False)
        self.resize(380, 180)
        self._note_count = note_count
        self._action_label = action_label
        self._can_interrupt = can_interrupt
        self._spinner_frames = ("◜", "◠", "◝", "◞", "◡", "◟")
        self._spinner_index = 0

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.status_label = QLabel(self._status_text(0, interrupted=False))
        self.status_label.setWordWrap(True)
        header.addWidget(self.status_label, 1)

        self.spinner_label = QLabel(self._spinner_frames[0])
        self.spinner_label.setStyleSheet("font-size: 18px; color: palette(text);")
        header.addWidget(self.spinner_label)
        layout.addLayout(header)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(note_count)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.interrupt_button = QPushButton("Interrupt")
        self.interrupt_button.setVisible(self._can_interrupt)
        layout.addWidget(self.interrupt_button)

        self._spinner_timer = QTimer(self)
        self._spinner_timer.timeout.connect(self._advance_spinner)
        self._spinner_timer.start(120)
        shared_styling.apply_dialog_theme(self)

    def set_progress(self, completed_count: int) -> None:
        self.progress_bar.setValue(completed_count)
        self.status_label.setText(self._status_text(completed_count, interrupted=False))

    def set_interrupt_requested(self) -> None:
        self.interrupt_button.setEnabled(False)
        self.interrupt_button.setText("Interrupt Requested")
        self.status_label.setText(self._status_text(self.progress_bar.value(), interrupted=True))

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._spinner_timer.stop()
        super().closeEvent(event)

    def _advance_spinner(self) -> None:
        self._spinner_index = (self._spinner_index + 1) % len(self._spinner_frames)
        self.spinner_label.setText(self._spinner_frames[self._spinner_index])

    def _status_text(self, completed_count: int, *, interrupted: bool) -> str:
        status = (
            f"{self._action_label} {self._note_count} note(s) with AI.\n\n"
            f"Completed {completed_count}/{self._note_count} note(s)."
        )
        if not self._can_interrupt:
            return status
        if interrupted:
            return status + " Waiting for the current in-flight request(s) to finish."
        return status + " Click Interrupt to stop after the current in-flight request(s)."
