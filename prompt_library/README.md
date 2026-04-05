# Prompt Library

Each prompt lives in its own Markdown file.

Rules:
- The first Markdown heading is used as the prompt name.
- Everything after the first blank line following the heading becomes the prompt text saved into `config.json`.
- Default user prompts live in `default_prompts/`.
- Personal or in-progress prompt variants can live in `user_prompts/`.
- System prompts live in `system_prompts/`.
- Some built-in workflow/audit presets also load their prompt text directly from this library, so these files are not only for rebuilding saved prompt entries.
