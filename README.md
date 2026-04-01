# AI Automation

AI Automation is an Anki add-on that sends selected Browser notes to the OpenAI API and writes the model response back into configured fields.

Users can select one or many rows in the Anki Browser, right-click, and choose `Process with AI`. The add-on renders a configurable prompt template with note fields such as `{{Front}}` and `{{Back}}`, calls the official OpenAI Python client, and updates configured output fields after a confirmation step when existing content would be overwritten.

## Features

- Browser right-click action that only appears when notes are selected
- Config-driven field mapping by note type
- Configurable prompt template and system prompt
- Structured JSON response handling for predictable field updates
- Sequential batch processing with retries and timeout controls
- Safe overwrite confirmation before existing fields are replaced

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
3. Open Anki, go to `Tools -> Add-ons -> AI Automation -> Config`, and set your API key plus field mappings.

If you need to install the dependency manually, use Anki's bundled Python. The exact path varies by platform, but the command is equivalent to:

```bash
/path/to/anki/python -m pip install openai
```

## Configuration

The add-on is configured through [`config.json`](./config.json) or Anki's built-in add-on config editor.

Important keys:

- `openai_api_key`: your OpenAI API key
- `model`: the model name sent to the OpenAI Responses API
- `prompt_template`: the default user prompt with placeholders like `{{Front}}`
- `field_mappings`: per-note-type input and output field rules
- `max_retries` and `request_timeout_seconds`: safety controls for batch processing

Example mapping:

```json
{
  "note_type": "Basic",
  "input_fields": ["Front", "Back"],
  "output_fields": ["Back"]
}
```

The prompt can reference the fields listed in the matched `input_fields` mapping, plus `{{NoteType}}`.

## How It Works

1. Select cards or notes in the Anki Browser.
2. Right-click and choose `Process with AI`.
3. The add-on resolves the matching `field_mappings` entry for each selected note.
4. A prompt is rendered from the note fields and sent to OpenAI.
5. Returned JSON field values are written back to the note and saved to the collection.

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
