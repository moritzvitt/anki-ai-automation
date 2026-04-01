# AI Automation Config

AI Automation stores its settings as a JSON object in Anki's add-on config.

From inside Anki, clicking `Config` in the add-on manager opens a custom settings dialog. That dialog writes back to Anki's stored add-on configuration for the current profile. The repository's [`config.json`](./config.json) remains the default template, while your live edited values are persisted by Anki in the add-on metadata for the profile.

## Main Keys

### `enabled`

Global on/off switch for the add-on.

### `openai_api_key`

Your OpenAI API key. The add-on will refuse to run until this is set.

This same key is also used for the optional official spend lookup in `Tools -> AI Automation Usage`. OpenAI's organization Costs API typically requires an organization admin key, so a regular project key may not be able to fetch billing totals.

### `model`

The model name used with the OpenAI Responses API.

### `system_prompt`

The default system prompt sent with every request. Keep this aligned with the JSON-only output requirement.

### `prompt_template`

Default prompt template for notes that do not override it in `field_mappings`.

Supported placeholders include the configured `input_fields` for the matched note type, plus `{{NoteType}}`.

When you change this prompt in the custom settings dialog and save, the previous prompt is automatically added to `prompt_history`.

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

### `show_estimate_before_sending`

When `true`, the add-on estimates token usage before requests are sent and shows a confirmation popup with estimated cost.

### `estimated_output_tokens_per_note`

Used for the pre-flight cost forecast. Input tokens are counted through the OpenAI input-token endpoint when available, while output tokens are estimated with this per-note value.

### `usage_history_limit`

Maximum number of recent runs stored in the local usage tracker shown from the Tools menu.

### `model_pricing`

Optional pricing overrides keyed by model name. Use this when you select a model that is not included in the add-on's built-in pricing table.

### `prompt_history`

List of previously saved prompt templates. This is maintained by the custom config window so you can quickly restore an older prompt version.

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
  "show_estimate_before_sending": true,
  "estimated_output_tokens_per_note": 200,
  "usage_history_limit": 20,
  "model_pricing": {
    "gpt-5-mini": {
      "input_per_million_usd": 0.25,
      "cached_input_per_million_usd": 0.025,
      "output_per_million_usd": 2.0
    }
  },
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
