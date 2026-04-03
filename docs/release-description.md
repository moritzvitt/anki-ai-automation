# AI Automation

AI Automation brings OpenAI-powered note updates to Anki through both Browser actions and reusable workflows.

Select notes in the Browser and choose `Transform with AI`, or create saved workflows that run against Anki queries, workflow groups, and optional startup/query-count triggers. Prompts can use note fields like `{{Front}}` and `{{Back}}`, and the add-on can write results back to a single field or split them across multiple fields.

## Main Features

- Browser context-menu processing for selected notes or cards
- Reusable workflows with saved queries, groups, and optional triggers
- Saved prompts, system prompts, and processing presets
- `append`, `overwrite`, and `skip if target field not empty` write modes
- Chat Completions and Responses API support
- Batch processing with retries, timeouts, incremental Browser updates, and optional cost estimates
- Local usage tracking and OpenAI spend lookup when the API key supports it

## Configuration

The add-on includes a structured config dialog for core settings, plus dedicated Browser settings and workflow settings windows. Set your API key, model, prompts, presets, batching behavior, and note-type rules there instead of editing raw JSON by hand.

## Compatibility

Built for current Anki releases using modern `aqt.gui_hooks` integration.
