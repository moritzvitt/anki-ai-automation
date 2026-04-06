# Branch Naming

Use short-lived branches for focused work. Merge them back into `main` and delete them when the work is done.

## Format

Preferred patterns:

- `feature/<area>-<change>`
- `fix/<area>-<bug>`
- `chore/<area>-<task>`
- `spike/<area>-<experiment>`

## Areas

Use a short area label that matches the part of the repo you are changing.

Common examples:

- `browser`
- `workflows`
- `pipelines`
- `prompts`
- `config`
- `docs`
- `infra`

## Examples

- `feature/browser-prompt-library-picker`
- `feature/workflows-group-editor-cleanup`
- `fix/pipelines-audit-branch-routing`
- `chore/prompts-reorganize-mlr-folders`
- `spike/browser-selection-runner`

## Rules

- Keep names lowercase.
- Use hyphens, not spaces or underscores.
- Keep one branch focused on one change.
- Prefer specific names over vague ones like `browser-stuff`.
- Do not keep feature branches forever. Merge and delete them.

## Fallback

If you are unsure, default to:

- `feature/<area>-<short-description>`

For example:

- `feature/browser-quick-tags`

## Links

- GitHub: https://github.com/moritzvitt/anki-ai-automation
- AnkiWeb: https://ankiweb.net/shared/info/1186735228
- Video: https://youtu.be/80O47uk6LCI
- Buy Me a Coffee: https://buymeacoffee.com/moritzowitsch
