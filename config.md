# Starter Repo Config

This add-on stores its configuration as a JSON dictionary.

## Keys

### `enabled`

Global on/off switch for the add-on.

### `debug`

When `true`, your add-on can log extra debug information.

### `example_note_types`

Optional list of note type names used by your add-on.

Example:

```json
{
  "enabled": true,
  "debug": false,
  "example_note_types": ["Basic", "Cloze"]
}
```
