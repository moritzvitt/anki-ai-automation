# AI Automation Config

AI Automation stores its settings as a JSON object in Anki's add-on config.

## Main Keys

### `enabled`

Global on/off switch for the add-on.

### `openai_api_key`

Your OpenAI API key. The add-on will refuse to run until this is set.

### `model`

The model name used with the OpenAI Responses API.

### `system_prompt`

The default system prompt sent with every request. Keep this aligned with the JSON-only output requirement.

### `prompt_template`

Default prompt template for notes that do not override it in `field_mappings`.

Supported placeholders include the configured `input_fields` for the matched note type, plus `{{NoteType}}`.

### `batch_size`

How many notes are grouped into each processing batch. Requests are still sent one note at a time so updates stay isolated and safe.

### `request_timeout_seconds`

Timeout for each OpenAI request.

### `max_retries`

How many times a failed OpenAI request should be retried.

### `retry_backoff_seconds`

Base delay used between retries.

### `temperature`

Optional model temperature. Set to `null` to leave it unset.

### `reasoning_effort`

Optional Responses API reasoning effort. Supported values in this add-on are `minimal`, `low`, `medium`, and `high`.

### `field_mappings`

List of per-note-type processing rules.

Each mapping supports:

- `note_type`: exact note type name, or `*` as a fallback
- `input_fields`: fields expected on the note and available to the prompt
- `output_fields`: fields that must be returned by the model as JSON
- `prompt_template`: optional prompt override for this note type
- `system_prompt`: optional system prompt override for this note type

## Example

```json
{
  "enabled": true,
  "openai_api_key": "sk-...",
  "model": "gpt-5-mini",
  "system_prompt": "You improve Anki flashcards. Return only valid JSON matching the requested schema.",
  "prompt_template": "Improve the following flashcard content:\n\nFront:\n{{Front}}\n\nBack:\n{{Back}}",
  "batch_size": 5,
  "request_timeout_seconds": 90,
  "max_retries": 2,
  "retry_backoff_seconds": 2,
  "temperature": 0.2,
  "reasoning_effort": "low",
  "field_mappings": [
    {
      "note_type": "Basic",
      "input_fields": ["Front", "Back"],
      "output_fields": ["Back"]
    },
    {
      "note_type": "Basic",
      "input_fields": ["Front", "Back"],
      "output_fields": ["AI Rewrite"],
      "prompt_template": "Create a cleaner explanation for this flashcard.\n\nFront:\n{{Front}}\n\nBack:\n{{Back}}"
    },
    {
      "note_type": "*",
      "input_fields": ["Front", "Back"],
      "output_fields": ["Back"]
    }
  ]
}
```
