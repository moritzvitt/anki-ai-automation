from __future__ import annotations

from html import escape

from aqt import gui_hooks
from aqt.editor import Editor
from aqt.qt import QMessageBox
from aqt.utils import showCritical

from ..core.config import AddonConfig, ConfigError, Workflow, load_config
from .tooltips import show_tooltip
from .workflow import run_workflows_background


_EDITOR_RUN_COMMAND = "ai_automation_editor_run_group"
_EDITOR_SELECTED_GROUP_ATTR = "_ai_automation_selected_group_id"


def register_editor_actions() -> None:
    gui_hooks.editor_did_init_buttons.append(_add_editor_group_controls)


def _add_editor_group_controls(buttons: list[str], editor: Editor) -> None:
    try:
        config = load_config()
    except ConfigError:
        return

    groups = _enabled_groups_with_workflows(config)
    selected_group_id = _initial_editor_group_id(config, groups)
    setattr(editor, _EDITOR_SELECTED_GROUP_ATTR, selected_group_id)
    editor._links[_EDITOR_RUN_COMMAND] = lambda current_editor: current_editor.call_after_note_saved(  # type: ignore[attr-defined]
        lambda: _run_group_from_editor(current_editor),
        keepFocus=True,
    )

    for group_id, _group_name in groups:
        editor._links[_editor_group_select_command(group_id)] = (  # type: ignore[attr-defined]
            lambda current_editor, selected_group_id=group_id: setattr(
                current_editor,
                _EDITOR_SELECTED_GROUP_ATTR,
                selected_group_id,
            )
        )

    buttons.append(_editor_controls_html(config, groups, selected_group_id))


def _enabled_groups_with_workflows(config: AddonConfig) -> list[tuple[str, str]]:
    enabled_group_ids = {workflow.group_id for workflow in config.workflows if workflow.enabled and workflow.group_id}
    return [
        (group.group_id, group.name)
        for group in sorted(config.workflow_groups, key=lambda item: item.name.lower())
        if group.group_id in enabled_group_ids
    ]


def _initial_editor_group_id(config: AddonConfig, groups: list[tuple[str, str]]) -> str:
    if not groups:
        return ""
    valid_group_ids = {group_id for group_id, _group_name in groups}
    if config.editor_default_workflow_group_id in valid_group_ids:
        return str(config.editor_default_workflow_group_id)
    return groups[0][0]


def _editor_controls_html(config: AddonConfig, groups: list[tuple[str, str]], selected_group_id: str) -> str:
    default_group_name = next(
        (group_name for group_id, group_name in groups if group_id == config.editor_default_workflow_group_id),
        "",
    )
    button_tooltip = (
        f"Configured default group: '{default_group_name}'. The dropdown can override it for this note. Change the default in AI Automation -> General Settings."
        if default_group_name
        else "Create with AI using the currently selected workflow group. Set a default group in AI Automation -> General Settings."
    )
    select_tooltip = "Choose which workflow group to run on the current editor note."
    if groups:
        option_html = "".join(
            (
                f'<option value="{escape(group_id, quote=True)}"'
                + (' selected="selected"' if group_id == selected_group_id else "")
                + f">{escape(group_name)}</option>"
            )
            for group_id, group_name in groups
        )
        disabled_attr = ""
    else:
        option_html = '<option value="" selected="selected">No enabled groups</option>'
        disabled_attr = ' disabled="disabled"'
    return (
        '<span class="ai-automation-editor-controls" '
        'style="display:inline-flex; align-items:center; gap:6px;">'
        f'<button tabindex="-1" class="anki-addon-button linkb" type="button" title="{escape(button_tooltip, quote=True)}" '
        f'data-cantoggle="0" data-command="{_EDITOR_RUN_COMMAND}"{disabled_attr}>Create</button>'
        f'<select tabindex="-1" title="{escape(select_tooltip, quote=True)}" '
        'style="max-width:180px; padding:4px 8px; border-radius:5px;" '
        f'onchange="pycmd(\'ai_automation_editor_select_group:\' + this.value);"'
        f'{disabled_attr}>{option_html}</select>'
        "</span>"
    )


def _run_group_from_editor(editor: Editor) -> None:
    if editor.note is None:
        show_tooltip("Open a note in the editor first.", parent=editor.parentWindow)
        return

    try:
        config = load_config()
    except ConfigError as error:
        showCritical(str(error), parent=editor.parentWindow)
        return

    if not config.enabled:
        show_tooltip("AI Automation is disabled in the add-on config.", parent=editor.parentWindow)
        return

    selected_group_id = str(getattr(editor, _EDITOR_SELECTED_GROUP_ATTR, "") or "")
    if not selected_group_id:
        show_tooltip("Choose a workflow group first.", parent=editor.parentWindow)
        return

    workflows = [
        workflow
        for workflow in sorted(config.workflows, key=lambda item: item.position)
        if workflow.enabled and workflow.group_id == selected_group_id
    ]
    if not workflows:
        show_tooltip("This workflow group does not contain any enabled workflows.", parent=editor.parentWindow)
        return

    skipped_workflows = _workflows_missing_target_fields(editor, workflows)
    skipped_workflow_ids = {workflow.workflow_id for workflow, _missing_fields in skipped_workflows}
    runnable_workflows = [
        workflow for workflow in workflows if workflow.workflow_id not in skipped_workflow_ids
    ]
    if skipped_workflows and not _confirm_skip_incompatible_workflows(editor, selected_group_id, config, skipped_workflows):
        return
    if not runnable_workflows:
        show_tooltip("No workflows in this group can run on the current note type.", parent=editor.parentWindow)
        return

    note_id = int(editor.note.id)
    group_name = next(
        (group.name for group in config.workflow_groups if group.group_id == selected_group_id),
        "Selected workflow group",
    )
    run_workflows_background(
        editor.parentWindow,
        runnable_workflows,
        run_label=f"{group_name} (current editor note)",
        note_ids_override=[note_id],
        show_summary_dialog=False,
        on_done=lambda _summary: _refresh_editor_note(editor, note_id=note_id),
    )


def _workflows_missing_target_fields(editor: Editor, workflows: list[Workflow]) -> list[tuple[Workflow, list[str]]]:
    if editor.note is None:
        return []
    available_fields = set(editor.note.keys())
    skipped: list[tuple[Workflow, list[str]]] = []
    for workflow in workflows:
        if workflow.workflow_type != "field_update" or workflow.multiple_target_fields:
            continue
        target_field = (workflow.target_field or "").strip()
        if target_field and target_field not in available_fields:
            skipped.append((workflow, [target_field]))
    return skipped


def _confirm_skip_incompatible_workflows(
    editor: Editor,
    group_id: str,
    config: AddonConfig,
    skipped_workflows: list[tuple[Workflow, list[str]]],
) -> bool:
    group_name = next((group.name for group in config.workflow_groups if group.group_id == group_id), "Selected group")
    lines = [
        f"Some workflows in '{group_name}' target fields that do not exist on this note.",
        "",
        "Those workflows will be skipped if you continue:",
    ]
    for workflow, missing_fields in skipped_workflows[:8]:
        lines.append(f"- {workflow.name}: {', '.join(missing_fields)}")
    if len(skipped_workflows) > 8:
        lines.append(f"- ...and {len(skipped_workflows) - 8} more")
    lines.extend(["", "Continue and skip those workflows?"])
    message_box = QMessageBox(editor.parentWindow)
    message_box.setWindowTitle("Workflow Group Warning")
    message_box.setText("\n".join(lines))
    continue_button = message_box.addButton("Continue", QMessageBox.ButtonRole.AcceptRole)
    message_box.addButton("Abort", QMessageBox.ButtonRole.RejectRole)
    message_box.setDefaultButton(continue_button)
    message_box.exec()
    return message_box.clickedButton() == continue_button


def _refresh_editor_note(editor: Editor, *, note_id: int) -> None:
    current_note = editor.note
    if current_note is None:
        return
    try:
        if int(current_note.id) != note_id:
            return
    except Exception:
        return
    try:
        current_note.load()
        editor.loadNoteKeepingFocus()
    except Exception:
        return


def _editor_group_select_command(group_id: str) -> str:
    return f"ai_automation_editor_select_group:{group_id}"
