# AI Automation 1.1.0

AI Automation adds OpenAI-powered note updates to Anki through Browser actions and reusable workflows.

Select notes in the Browser and choose `Transform with AI`, or create workflows that run against saved Anki queries, groups, Browser selections, and optional triggers. Prompts can use note fields like `{{Front}}` and `{{Back}}`, and results can be written back to one field or split across multiple fields.

## Highlights

- Browser processing for selected notes or cards
- Reusable workflows with groups, visible custom script steps, and optional triggers
- Saved prompts, system prompts, and processing presets
- `append`, `overwrite`, and `skip if target field not empty` write modes
- Chat Completions and Responses API support
- Faster batch processing with retries, timeouts, progress feedback, and incremental Browser updates

Built for current Anki releases using modern `aqt.gui_hooks` integration.
