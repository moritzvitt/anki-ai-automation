# AI Automation

AI Automation brings OpenAI-powered note rewriting directly into the Anki Browser.

Select one or many Browser rows, right-click, and choose `Process with AI`. The add-on renders a configurable prompt from your note fields, sends it to the OpenAI API, and writes structured results back into the fields you choose.

## Main Features

- Browser context-menu integration for selected notes
- Configurable prompt templates using placeholders like `{{Front}}` and `{{Back}}`
- Per-note-type field mapping so different note models can be processed differently
- Official OpenAI Python client integration with retries and timeout controls
- Safe overwrite confirmation before existing field values are replaced

## Configuration

Set your API key, model, prompt template, and field mappings in the add-on config. The add-on expects JSON output from the model so field updates stay predictable.

## Compatibility

Built for current Anki releases using modern `aqt.gui_hooks` Browser integration.
