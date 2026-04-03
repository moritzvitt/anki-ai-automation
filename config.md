# AI Automation Config

AI Automation stores its settings as a JSON object in Anki's add-on config.

From inside Anki, clicking `Config` in the add-on manager opens a custom settings dialog. That dialog writes back to Anki's stored add-on configuration for the current profile. The repository's [`config.json`](./config.json) remains the default template, while your live edited values are persisted by Anki in the add-on metadata for the profile.

The settings dialog now keeps note type rules in a dedicated editor instead of exposing raw `field_mappings` JSON directly.

## Main Keys

### `enabled`

Global on/off switch for the add-on.

### `show_tooltips`

Controls both hover help on UI fields and the small transient status tooltips shown after some actions.

Set this to `false` if you want a quieter UI without hover hints or popup tooltip messages.

### `use_chat_completions_api`

Controls whether text generation uses the Chat Completions API instead of the Responses API.

Default: `true`

This is enabled by default for speed testing and simpler text-generation runs. Disable it if you want to compare against the Responses API path.

### `openai_api_key`

Your OpenAI API key. The add-on will refuse to run until this is set.

This same key is also used for the optional official spend lookup in `Tools -> AI Automation Usage`. OpenAI's organization Costs API typically requires an organization admin key, so a regular project key may not be able to fetch billing totals.

### `model`

The model name used with the OpenAI Responses API.

In the custom settings dialog, this is presented as a dropdown that refreshes from a curated OpenAI model shortlist relevant to text generation for flashcards. Each option includes a rough cost label based on known pricing, such as `Cheap` or `Very expensive`.

### `system_prompt`

The default system prompt sent with every request. Keep this aligned with the JSON-only output requirement.

### `prompt_template`

Default prompt template for notes that do not override it in `field_mappings`.

Supported placeholders include any actual field name on the note, plus `{{NoteType}}`.

When you change this prompt in the custom settings dialog and save, the previous prompt is automatically added to `prompt_history`.

### `batch_size`

How many notes are grouped into each processing batch. Requests are still sent one note at a time inside the batch so updates stay isolated and safe.

Default: `20`

### `max_parallel_requests`

How many note requests can run in parallel inside each batch.

Default: `4`

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

Currently not shown in the UI and effectively disabled in the runtime flow. The add-on goes straight to the normal confirmation step without a pre-flight token estimate popup.

### `estimated_output_tokens_per_note`

Reserved for future estimate UI work.

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
- `output_fields`: fields that must be returned by the model as JSON
- `prompt_template`: optional prompt override for this note type
- `system_prompt`: optional system prompt override for this note type

## Example

```json
{
  "enabled": true,
  "show_tooltips": true,
  "openai_api_key": "sk-...",
  "model": "gpt-5-mini",
  "system_prompt": "You improve Anki flashcards. Return only valid JSON matching the requested schema.",
  "prompt_template": "Improve the following flashcard content:\n\nFront:\n{{Front}}\n\nBack:\n{{Back}}",
  "batch_size": 20,
  "max_parallel_requests": 4,
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
      "output_fields": ["Back"]
    },
    {
      "note_type": "Basic",
      "output_fields": ["AI Rewrite"],
      "prompt_template": "Create a cleaner explanation for this flashcard.\n\nFront:\n{{Front}}\n\nBack:\n{{Back}}"
    },
    {
      "note_type": "*",
      "output_fields": ["Back"]
    }
  ]
}
```
