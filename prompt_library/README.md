# Prompt Library

Each prompt lives in its own Markdown file. These files are the source of truth for the prompt library.

Rules:
- The first Markdown heading is used as the prompt name.
- Everything after the first blank line following the heading becomes the prompt text loaded by the add-on at runtime.
- Default user prompts live in `default_prompts/`.
- Personal or in-progress prompt variants can live in `user_prompts/`.
- System prompts live in `system_prompts/`.
- Saved prompts are no longer treated as text embedded in tracked `config.json`; legacy config prompts are imported into markdown files under `user_prompts/` when needed.
- Some built-in workflow and Browser presets also load their prompt text directly from this library, so these files are not only for display in the prompt picker.
