# Architecture Overview

AI Automation is an Anki Browser add-on that processes selected notes with the OpenAI API and writes structured results back into configured fields.

## Runtime Flow

1. `__init__.py` imports [`addon.py`](../../addon.py), which calls `register()`.
2. [`browser_menu.py`](../../browser_menu.py) registers `gui_hooks.browser_will_show_context_menu`.
3. [`workflow_ui.py`](../../workflow_ui.py) registers a Tools menu action for query-based workflow runs.
4. When the user right-clicks selected Browser rows, the add-on adds `Transform with AI`.
5. Triggering the Browser action loads config from [`config.py`](../../config.py), resolves selected cards to note IDs, and opens the saved-prompt transform dialog in [`automation_ui.py`](../../automation_ui.py).
6. Triggering the workflow action opens a workflow manager in [`workflow_ui.py`](../../workflow_ui.py), where queries are resolved to note IDs and workflows or groups can be run in order.
7. [`processing.py`](../../processing.py) builds note snapshots, validates prompt placeholders and target fields, and confirms overwrites or appends.
8. Requests are executed in a background `QueryOp`.
9. Before sending, [`processing.py`](../../processing.py) can estimate input tokens with the OpenAI input-token endpoint and show a confirmation dialog with projected token and cost usage.
10. [`prompting.py`](../../prompting.py) renders placeholders such as `{{Front}}`.
11. [`openai_client.py`](../../openai_client.py) calls the official OpenAI client with a JSON schema for the configured output fields.
12. Successful responses are applied to notes, actual token usage is persisted locally, and notes are saved through Anki's collection API.

## Module Responsibilities

- [`browser_menu.py`](../../browser_menu.py): Browser integration and menu action wiring
- [`automation_ui.py`](../../automation_ui.py): Browser transform dialog and saved-prompt management UI
- [`workflow_ui.py`](../../workflow_ui.py): workflow manager UI, query preview, and ordered workflow/group execution
- [`config.py`](../../config.py): config loading, validation, and typed access
- [`prompting.py`](../../prompting.py): prompt template interpolation
- [`openai_client.py`](../../openai_client.py): OpenAI Responses API request and retry logic
- [`processing.py`](../../processing.py): note snapshot building, batching, failure handling, and note updates
- [`pricing.py`](../../pricing.py): pricing lookup and cost estimation
- [`usage_stats.py`](../../usage_stats.py): local usage persistence for the Tools menu monitor

## Safety

- The action only appears when the Browser has selected notes.
- Output fields are validated before any request is sent.
- A confirmation dialog appears before overwriting existing field content.
- Failed notes are reported without blocking successful ones from being saved.
