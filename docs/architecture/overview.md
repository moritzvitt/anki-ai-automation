# Architecture Overview

AI Automation is an Anki add-on that can process notes in three complementary ways:

- Browser-driven field updates with `Transform with AI`
- independently runnable atomic workflows
- config-defined pipelines that orchestrate workflows conditionally

## Runtime Flow

1. `__init__.py` imports [`addon.py`](../../addon.py), which calls `register()`.
2. [`browser_menu.py`](../../ui/browser_menu.py) registers `gui_hooks.browser_will_show_context_menu`.
3. [`workflow.py`](../../ui/workflow.py) registers the workflow manager and query-based workflow runner.
4. [`pipelines.py`](../../ui/pipelines.py) registers the Tools menu pipeline runner.
5. When the user right-clicks selected Browser rows, the add-on adds `Transform with AI` and `Audit with AI`.
6. Triggering `Transform with AI` loads config from [`config.py`](../../core/config.py), resolves selected cards to note IDs, and opens the saved-prompt transform dialog in [`automation.py`](../../ui/automation.py).
7. Triggering the workflow action opens a workflow manager in [`workflow.py`](../../ui/workflow.py), where workflows or groups can be run in order.
8. Triggering the pipeline action opens [`pipelines.py`](../../ui/pipelines.py), which resolves the configured note selector once and then runs each pipeline step per note.
9. [`workflow_engine.py`](../../core/workflow_engine.py) dispatches atomic workflows by `workflow_type`.
10. `field_update` workflows use [`processing.py`](../../core/processing.py) to build note snapshots, validate prompt placeholders and target fields, and write returned content into note fields.
11. `audit` workflows use [`audit_flow.py`](../../core/audit_flow.py) to build structured audit requests, strip HTML from `Cloze` before auditing, validate structured output, apply audit tags, and persist audit metadata.
12. [`pipelines.py`](../../core/pipelines.py) branches declaratively on validated artifacts like `audit.status` and `audit.fields_to_update`, so later steps can run only for matching notes.
13. Requests execute in a background `QueryOp`, but note mutations are applied back on the main Anki thread.

## Module Responsibilities

- [`browser_menu.py`](../../ui/browser_menu.py): Browser integration and menu action wiring
- [`automation.py`](../../ui/automation.py): Browser transform dialog and saved-prompt management UI
- [`workflow.py`](../../ui/workflow.py): workflow manager UI, query preview, typed workflow editing, and ordered workflow/group execution
- [`pipelines.py`](../../ui/pipelines.py): config-defined pipeline picker and runner UI
- [`config.py`](../../core/config.py): config loading, validation, and typed access
- [`workflow_engine.py`](../../core/workflow_engine.py): workflow dispatch by workflow type
- [`pipelines.py`](../../core/pipelines.py): per-note pipeline orchestration and declarative branching
- [`audit_flow.py`](../../core/audit_flow.py): structured audit execution, tag application, and audit metadata persistence
- [`audit_prompts.py`](../../core/audit_prompts.py): audit schema presets and validation metadata
- [`audit_storage.py`](../../core/audit_storage.py): persisted audit log storage
- [`prompting.py`](../../core/prompting.py): prompt template interpolation
- [`openai_client.py`](../../services/openai_client.py): OpenAI Responses and Chat Completions request handling
- [`processing.py`](../../core/processing.py): note snapshot building, batching, failure handling, and note updates
- [`pricing.py`](../../services/pricing.py): pricing lookup and cost estimation
- [`usage_stats.py`](../../core/usage_stats.py): local usage persistence for the Tools menu monitor

## Safety

- The action only appears when the Browser has selected notes.
- Output fields are validated before any request is sent.
- A confirmation dialog appears before overwriting existing field content.
- Audit workflows do not rewrite study content fields directly.
- Pipelines branch on validated artifacts instead of raw model text.
- Rejected-note handling can tag and suspend cards without mixing that logic into prompt execution.
- Failed notes are reported without blocking successful ones from being saved.
