# Browser Performance Notes

The biggest reason this add-on still feels slower than `anki-smart-notes` is probably not Python overhead. It is mostly the request shape.

## Current Differences

- This add-on is currently using `gpt-5-mini` in `meta.json`.
- Smart Notes defaults to `gpt-4o-mini` in its `config.json`.
- This add-on uses the OpenAI Responses API with structured output or delimiter parsing in `services/openai_client.py`.
- Smart Notes uses a simpler Chat Completions call with just a user prompt in `src/open_ai_client.py`.
- This add-on also sends a fairly large system prompt by default, while Smart Notes does not send a system prompt in that local OpenAI path.
- This add-on currently uses `reasoning_effort: low`, which can add latency. Smart Notes does not use that reasoning setting in its OpenAI call.

Even when both process the same number of notes, this add-on is asking the model to do a heavier job per note.

## Current Runtime Values

From the current `meta.json`:

- `model: gpt-5-mini`
- `batch_size: 10`
- `max_parallel_requests: 10`

Important detail:

- Even though the repo defaults were changed to `batch_size = 20` and `max_parallel_requests = 4`, the live Anki profile still uses the old stored values above.
- `meta.json` overrides the repo defaults for this profile.

## Why Smart Notes Still Feels Faster

- faster model: `gpt-4o-mini` vs `gpt-5-mini`
- lighter endpoint usage: plain chat completion vs Responses API structured mode
- smaller payloads: less system-instruction overhead
- less strict output contract: this add-on validates field-shaped output, which is safer but slower

## Highest-Impact Next Steps

1. Change Browser runs to default to `gpt-4o-mini` or another faster model.
2. Set Browser runs to `reasoning_effort = minimal` or `null`.
3. Shorten the default system prompt substantially.
4. Add an optional Browser `fast mode` that uses plain text responses instead of structured JSON where possible.
