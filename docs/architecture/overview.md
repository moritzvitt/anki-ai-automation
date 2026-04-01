# Architecture Overview

AI Automation is an Anki Browser add-on that processes selected notes with the OpenAI API and writes structured results back into configured fields.

## Runtime Flow

1. `__init__.py` imports [`addon.py`](../../addon.py), which calls `register()`.
2. [`browser_menu.py`](../../browser_menu.py) registers `gui_hooks.browser_will_show_context_menu`.
3. When the user right-clicks selected Browser rows, the add-on adds `Process with AI`.
4. Triggering the action loads and validates config from [`config.py`](../../config.py).
5. [`processing.py`](../../processing.py) resolves note snapshots, matches `field_mappings`, and confirms overwrites.
6. Requests are executed in a background `QueryOp`.
7. Before sending, [`processing.py`](../../processing.py) can estimate input tokens with the OpenAI input-token endpoint and show a confirmation dialog with projected token and cost usage.
8. [`prompting.py`](../../prompting.py) renders placeholders such as `{{Front}}`.
9. [`openai_client.py`](../../openai_client.py) calls the official OpenAI client with a JSON schema for the configured output fields.
10. Successful responses are applied to notes, actual token usage is persisted locally, and notes are saved through Anki's collection API.

## Module Responsibilities

- [`browser_menu.py`](../../browser_menu.py): Browser integration and menu action wiring
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
