# Architecture Overview

AI Automation is currently built around prompt-driven note processing inside Anki.

The active execution surfaces are:

- Browser-driven field updates with `Transform with AI`
- reusable workflows that can be run from the workflow manager or directly from the Browser selection
- workflow groups that run their member workflows in order
- workflow triggers that can start enabled workflows automatically from saved queries

Pipelines and the structured audit JSON flow are no longer part of the active architecture.

## Runtime Flow

1. `__init__.py` imports [`addon.py`](../../addon.py), which calls `register()`.
2. [`addon.py`](../../addon.py) wires up Browser actions, workflow management, usage UI, and workflow triggers.
3. [`browser_menu.py`](../../ui/browser_menu.py) registers Browser context-menu actions for:
   - `Transform with AI`
   - `Run Workflow with AI`
   - `Run Group`
4. [`automation.py`](../../ui/automation.py) opens the manual Browser transform dialog and builds a `ManualProcessingSpec`.
5. [`workflow.py`](../../ui/workflow.py) opens the workflow manager, lets users edit workflows and groups, and runs workflows or groups in order.
6. [`workflow_engine.py`](../../core/workflow_engine.py) dispatches each workflow by `workflow_type`.
7. `field_update` workflows use [`processing.py`](../../core/processing.py) to prepare note snapshots, validate prompt placeholders and target fields, send requests, and defer note writes back to the main thread.
8. `script` workflows run a shell command once at their position in the workflow order and receive the current note ids through environment variables.
9. Workflow triggers in [`workflow_triggers.py`](../../core/workflow_triggers.py) periodically reload config, resolve query matches, and launch eligible workflows through the same workflow runner.
10. All note mutations still land back on the main Anki thread.

## Module Responsibilities

- [`addon.py`](../../addon.py): top-level registration of add-on features
- [`browser_menu.py`](../../ui/browser_menu.py): Browser integration and menu action wiring
- [`automation.py`](../../ui/automation.py): Browser transform dialog and saved-prompt management UI
- [`workflow.py`](../../ui/workflow.py): workflow manager UI, Browser-selected workflow/group runs, and ordered sequence execution
- [`workflow_dialog.py`](../../ui/workflow_dialog.py): field-update workflow editor and script-workflow editor
- [`config.py`](../../core/config.py): high-level config orchestration
- [`config_models.py`](../../core/config_models.py): typed config dataclasses and shared config IDs
- [`config_parsing.py`](../../core/config_parsing.py): config value parsing and workflow/prompt validation helpers
- [`config_prompt_library.py`](../../core/config_prompt_library.py): prompt-library file discovery and prompt-file path helpers
- [`workflow_engine.py`](../../core/workflow_engine.py): workflow dispatch and result packaging
- [`processing.py`](../../core/processing.py): note-processing orchestration, batching, and request execution
- [`processing_models.py`](../../core/processing_models.py): note-processing dataclasses and the shared progress dialog
- [`processing_support.py`](../../core/processing_support.py): writeback, result summaries, and usage aggregation
- [`processing_text.py`](../../core/processing_text.py): Markdown-to-HTML conversion and delimited multi-field response parsing
- [`prompting.py`](../../core/prompting.py): prompt placeholder extraction, field normalization, and template rendering
- [`openai_client.py`](../../services/openai_client.py): OpenAI request handling
- [`pricing.py`](../../services/pricing.py): model pricing lookup and cost estimation
- [`usage_stats.py`](../../core/usage_stats.py): local usage persistence for the usage view

## Execution Model

### Browser Transform

- The user selects notes in the Browser.
- [`automation.py`](../../ui/automation.py) resolves a prompt, model, target field, and write mode.
- [`processing.py`](../../core/processing.py) builds snapshots, confirms overwrites, runs requests in batches, and applies note updates.

### Workflow Run

- A workflow can be launched from the workflow manager or directly from the Browser selection.
- [`workflow_engine.py`](../../core/workflow_engine.py) decides whether the workflow is a `field_update` or `script` workflow.
- Field-update workflows reuse the same lower-level processing engine as Browser transforms.
- Script workflows run once in sequence and can use the provided note IDs to call external tools or custom scripts.

### Group Run

- Groups are organizational containers for workflows.
- A group run is just an ordered sequence of workflows that share the same `group_id`.
- Custom scripts are modeled as normal `script` workflows inside the group, so execution order stays visible in the UI.

## Safety

- Browser actions only appear when selected notes exist.
- Output fields and prompt placeholders are validated before requests are sent.
- A confirmation dialog appears before overwriting existing field content.
- Progress dialogs show visible batch progress and support interruption.
- Script execution is explicit and visible as a workflow row instead of being hidden behind a separate group-only hook.
- Failed notes are reported without blocking successful ones from being saved.

## Related Notes

- [`workflows-groups-pipelines.md`](./workflows-groups-pipelines.md)
- [`audit-prompt-construction.md`](./audit-prompt-construction.md)
- [`sample-user-audit-pipeline.md`](./sample-user-audit-pipeline.md)
