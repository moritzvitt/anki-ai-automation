# AI Automation

AI Automation is an Anki add-on that sends Browser-selected notes to the OpenAI API and writes the model response back into note fields.

Users can select one or many rows in the Anki Browser, right-click, and choose `Transform with AI`. The add-on resolves selected cards to notes, lets the user choose a shared target field plus a saved prompt, calls the official OpenAI Python client, and updates note fields after a confirmation step when existing content would be overwritten.

## Features

- Browser right-click action that works with selected notes or cards
- Saved prompt library with prompt names plus editable prompt text
- Browser transform dialog with target-field selection and append/overwrite modes
- Config-driven field mapping by note type
- Configurable prompt template and system prompt
- Structured JSON response handling for predictable field updates
- Sequential batch processing with retries and timeout controls
- Safe overwrite confirmation before existing fields are replaced
- Pre-flight token and cost estimate before requests are sent
- Tools menu usage monitor for tracked token totals and estimated spend

## File Structure

```text
ai-automation/
├── __init__.py
├── addon.py
├── browser_menu.py
├── config.py
├── openai_client.py
├── processing.py
├── prompting.py
├── manifest.json
├── config.json
├── config.md
├── CHANGELOG.md
└── docs/
```

## Installation

1. Install the add-on folder into Anki's add-ons directory.
2. Install the official OpenAI client into Anki's Python environment.
3. Open Anki, go to `Tools -> Add-ons -> AI Automation -> Config`, and use the settings window to set your API key, choose a model from the live dropdown, edit prompts, and manage note type rules.

If you need to install the dependency manually, use Anki's bundled Python. The exact path varies by platform, but the command is equivalent to:

```bash
/path/to/anki/python -m pip install openai
```

## Configuration

The add-on is configured through [`config.json`](./config.json) or Anki's built-in add-on config editor.

In Anki itself, the add-on now registers a custom config window, so clicking `Config` from the add-on manager opens a structured settings dialog instead of raw JSON. Anki still persists the values in its normal add-on config storage for the profile.

The model selector in that dialog loads a curated flashcard-writing shortlist from OpenAI's `GET /v1/models` endpoint using your API key and labels models with rough cost tiers such as `Very cheap`, `Cheap`, `Moderate`, `Expensive`, and `Very expensive`.
The note type rules are edited in a small dedicated UI instead of a raw `field_mappings` JSON block.

Important keys:

- `openai_api_key`: your OpenAI API key
- `model`: the model name sent to the OpenAI Responses API
- `prompt_template`: the default user prompt with placeholders like `{{Front}}`
- `field_mappings`: per-note-type input and output field rules
- `max_retries` and `request_timeout_seconds`: safety controls for batch processing
- `show_estimate_before_sending`: enables the confirmation popup with estimated tokens and cost
- `estimated_output_tokens_per_note`: used to forecast output tokens before the request is sent
- `model_pricing`: optional overrides for cost estimation when you use a model not covered by built-in pricing
- `prompt_history`: automatically maintained list of previous prompt templates for quick restore in the config window

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
3. The add-on resolves the selected rows to note IDs, then lets you choose a shared target field, a saved prompt, and append or overwrite mode.
4. A prompt is rendered from the note fields and sent to OpenAI.
5. Returned JSON field values are written back to the chosen note field and saved to the collection.

Open `Tools -> AI Automation Usage` to review tracked totals and recent runs. These spend figures are local add-on estimates based on model pricing, not billing-invoice truth.

The same menu also attempts to fetch official OpenAI spend for today, last 7 days, and this month through OpenAI's organization Costs API. That endpoint typically requires an organization admin key; regular project API keys may not have access.

## Packaging

To build a `.ankiaddon` archive manually:

```bash
zip -r ai-automation.ankiaddon . -x './.git/*' './.vscode/*' './__pycache__/*' './.DS_Store'
```

## Docs

- Config reference: [`config.md`](./config.md)
- Overview: [`docs/README.md`](./docs/README.md)
- Architecture notes: [`docs/architecture/overview.md`](./docs/architecture/overview.md)
- Release text draft: [`docs/release-description.md`](./docs/release-description.md)
