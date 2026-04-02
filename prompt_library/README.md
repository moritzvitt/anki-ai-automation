# Prompt Library

Each prompt lives in its own Markdown file.

Rules:
- The first Markdown heading is used as the prompt name.
- Everything after the first blank line following the heading becomes the prompt text saved into `config.json`.
- User prompts live in `user_prompts/`.
- System prompts live in `system_prompts/`.

To rebuild the prompt sections in `config.json`, run:

```bash
python3 tools/build_config_from_prompts.py
```
