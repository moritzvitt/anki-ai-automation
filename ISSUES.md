# Issues

This file is a lightweight guide for opening and tracking issues for AI Automation.

## Best Practices For Reporting Issues

- Say what you were trying to do in plain language.
- Include the exact place in Anki where it happened.
  Examples: `Browser -> right click -> Transform with AI`, `Tools -> AI Automation: Workflow Configuration`, `Tools -> Add-ons -> AI Automation -> Config`.
- Include the note type, target field, and whether you were using a one-off Browser run or a saved workflow.
- Include the Anki version, add-on version, operating system, and model name.
- Include the exact error message or traceback if one appeared.
- Describe the expected result and the actual result.
- If the problem depends on prompt formatting, include a minimal prompt example.
- If the problem depends on note content, include a small redacted example note.
- Mention whether the run used `append`, `overwrite`, or `skip if target field not empty`.
- Mention whether the issue is reproducible every time or only sometimes.

## Good Bug Report Template

```md
### Summary
Short description of the problem.

### Where It Happened
Example: Browser -> right click -> Transform with AI

### Steps To Reproduce
1. Open ...
2. Select ...
3. Run ...

### Expected Result
What should have happened.

### Actual Result
What happened instead.

### Environment
- Anki version:
- Add-on version:
- OS:
- Model:

### Extra Context
- Note type:
- Target field(s):
- Prompt or workflow used:
- Write mode:
- Error message / traceback:
```

## Best Practices For Feature Requests

- Start with the user problem, not the implementation.
- Explain who benefits and how often the workflow comes up.
- Describe the current workaround, if any.
- Be clear whether the request is for Browser runs, workflows, config UI, usage tracking, or prompt/preset management.
- If the feature could overwrite note data, explain the safety expectation.
- If relevant, include a rough UI path where you expect the feature to live.

## Good Future Issue Areas

- Better onboarding for first-time users inside Anki.
- More example prompts and starter workflow presets.
- Clearer failure summaries for partial-success batch runs.
- Easier debugging for prompt rendering and missing-field errors.
- Better visibility into workflow triggers and why they fired.
- Import/export for prompts, presets, and workflows.
- More guardrails before large overwrite-heavy runs.
- Better docs and screenshots for AnkiWeb and GitHub.

## Triage Guidelines

- `bug`: something that worked incorrectly or unsafely
- `ux`: confusing or hard-to-find behavior in the UI
- `docs`: missing or unclear documentation
- `enhancement`: improvement to an existing flow
- `feature`: new capability

Good issues for this repo are concrete, reproducible, and framed around the user workflow in Anki.
