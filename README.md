# AI Automation

<img src="https://raw.githubusercontent.com/moritzvitt/anki-ai-automation/c6cade0b7e0049877a3fc37f298942b770295207/images.webp" alt="AI Automation logo" width="128" />

AI Automation is an Anki add-on for running OpenAI-powered note updates from the Browser or from saved workflows.

You can select Browser rows and choose `Transform with AI`, or build reusable workflows that run against Anki searches, workflow groups, Browser selections, and startup/query triggers. The add-on renders prompts from note fields, sends them to OpenAI, and writes the result back into one or more note fields with configurable safety checks.

## Features

- Browser right-click action for selected notes or cards
- Workflow manager for saved query-based runs and workflow groups
- Visible custom script steps that can run inside workflow groups in normal execution order
- Optional workflow triggers on startup or when query counts reach a threshold
- Saved prompt, system prompt, and processing preset libraries
- Browser and workflow settings dialogs for managing prompts, presets, and defaults outside active runs
- Single-field or multi-field output modes
- `append`, `overwrite`, and `skip if target field not empty` write modes
- Chat Completions or Responses API support
- Batching, bounded concurrency, retries, timeout controls, and incremental note updates during Browser runs
- Optional token/cost estimate before sending
- Local usage tracking plus an OpenAI spend lookup view when the API key has access

## File Structure

```text
ai-automation/
├── __init__.py
├── addon.py
├── core/
│   ├── config.py
│   ├── config_models.py
│   ├── config_parsing.py
│   ├── config_prompt_library.py
│   ├── automation_files.py
│   ├── processing.py
│   ├── processing_models.py
│   ├── processing_support.py
│   ├── processing_text.py
│   ├── prompt_files.py
│   ├── prompting.py
│   ├── usage_stats.py
│   ├── workflow_engine.py
│   └── workflow_triggers.py
├── services/
├── scripts/
├── prompt_library/
├── ui/
├── docs/
├── tools/
├── user_data/
└── CHANGELOG.md
```

## Installation

1. Install the add-on folder into Anki's add-ons directory.
2. Install the official OpenAI client into Anki's Python environment.
3. Open Anki, go to `Tools -> Add-ons -> AI Automation -> Config`, and use the settings window to set your API key, choose a model, and open the dedicated Browser and workflow settings dialogs.

To run reusable query-based rules, open `Tools -> AI Automation: Workflow Configuration`.

If you need to install the dependency manually, use Anki's bundled Python. The exact path varies by platform, but the command is equivalent to:

```bash
/path/to/anki/python -m pip install openai
```

## Configuration

The add-on is configured through [`config.json`](./config.json) or Anki's built-in add-on config storage.

In Anki itself, clicking `Config` opens a structured core settings dialog instead of raw JSON. From there, you can jump into the dedicated Browser settings and workflow settings windows.

The model selector in that dialog loads a curated flashcard-writing shortlist from OpenAI's `GET /v1/models` endpoint using your API key and labels models with rough cost tiers such as `Very cheap`, `Cheap`, `Moderate`, `Expensive`, and `Very expensive`.
The note type rules are edited in a small dedicated UI instead of a raw `field_mappings` JSON block.

Important keys:

- `openai_api_key`: your OpenAI API key
- `use_chat_completions_api`: toggles Chat Completions vs Responses API for generation
- `model`: the default model used for generation
- `prompt_template`: the default user prompt with placeholders like `{{Front}}`
- `system_prompt`: the default system prompt
- `field_mappings`: per-note-type input and output field rules
- `max_retries` and `request_timeout_seconds`: safety controls for batch processing
- `batch_size`: how many notes are processed per outer batch
- `max_parallel_requests`: limits how many note requests can run at the same time
- `show_tooltips`: enables or disables hover help across the UI
- `show_estimate_before_sending`: enables the confirmation popup with estimated tokens and cost
- `estimated_output_tokens_per_note`: used to forecast output tokens before the request is sent
- `model_pricing`: optional overrides for cost estimation when you use a model not covered by built-in pricing
- `saved_prompts`, `saved_system_prompts`, `processing_presets`: reusable building blocks for Browser runs and workflows
- `workflows`, `workflow_groups`: reusable automations and group organization

Example mapping:

```json
{
  "note_type": "Basic",
  "output_fields": ["Back"]
}
```

The prompt can reference any field that exists on the note, plus `{{NoteType}}`. If a referenced field does not exist on a selected note, the add-on will show a clear error for that note instead of sending a broken request.

## How It Works

1. Select cards or notes in the Anki Browser.
2. Right-click and choose `Transform with AI`.
3. The add-on resolves the selected rows to note IDs, then lets you choose a target field or preset, prompt/system prompt, and write mode.
4. A prompt is rendered from the note fields and sent to OpenAI.
5. Returned content is written back to the chosen field or fields and saved to the collection.

For rule-based runs:

1. Open `Tools -> AI Automation: Workflow Configuration`.
2. Create workflows with a name, optional Anki query, prompts, target field settings, optional presets, groups, and optional trigger conditions.
3. Use `Refresh Count` while editing to preview how many notes the query currently matches.
4. Run one workflow or an entire group in the stored execution order, or launch them directly from the Browser on the current selection.

Open `Tools -> AI Automation Usage` to review tracked totals and recent runs. These spend figures are local add-on estimates based on model pricing, not billing-invoice truth.

The same menu also attempts to fetch official OpenAI spend for today, last 7 days, and this month through OpenAI's organization Costs API. That endpoint typically requires an organization admin key; regular project API keys may not have access.

## Packaging

To build a `.ankiaddon` archive manually:

```bash
python3 tools/package_ankiaddon.py
```

The packaging script excludes local `user_data`, `meta.json`, and all files under `prompt_library/user_prompts/`, while still creating an empty `prompt_library/user_prompts/` directory inside the archive.

## Docs

- Docs index: [`docs/README.md`](./docs/README.md)
- Config reference: [`config.md`](./config.md)
- Issue reporting and future issue ideas: [`ISSUES.md`](./ISSUES.md)
- Architecture notes: [`docs/architecture/overview.md`](./docs/architecture/overview.md)
- Release text draft: [`docs/release/release-description.md`](./docs/release/release-description.md)
