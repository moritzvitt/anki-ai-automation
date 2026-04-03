# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and this project follows semantic versioning where practical.

## Unreleased

### Added

- Workflow triggers that can run automatically on profile startup or when a query condition becomes true.
- Trigger conditions based on workflow query match counts, including thresholds such as "run when at least N notes match".
- A `skip if target field not empty` write mode for Browser runs and workflows.
- Hover help tooltips across the config dialog, Browser dialog, and workflow manager, plus a config option to disable all tooltips.
- Support for assigning a workflow to multiple groups instead of only one.
- A VS Code task and formatter script to pretty-print `meta.json` safely.
- Inline prompt and system prompt editors in the workflow dialog, plus actions to create, edit, and delete saved system prompts there.
- A Browser AI settings dialog for managing Browser presets, prompts, and defaults outside an active run.

### Changed

- Reorganized the codebase into `core/`, `ui/`, and `services/` packages to keep related modules together.
- Workflow previews now show trigger details and multiple group memberships.
- Workflow group filtering and group runs now include workflows that belong to more than one group.
- The main config dialog now focuses on core settings and links out to dedicated workflow and Browser settings dialogs.
- The default flashcard system prompt no longer forces strict JSON-only output.
- Workflow editing now uses a wider, scrollable layout with collapsible settings sections to make large workflows easier to review.
- Workflow queries now use a single-line input, and workflow group filtering uses clearer wording in the manager.
- Browser AI and saved prompt dialogs now use roomier layouts, including a consistent selection summary area and wider prompt name input.

## 0.1.0 - 2026-03-27

### Added

- Initial Anki add-on starter template.
- Minimal runnable add-on entry point and sample menu action.
- Default Anki config files and documentation placeholders.
- VS Code tasks for validation and packaging.

## 1.0.0 - 2026-04-01

### Added

- Browser context-menu integration for processing selected notes with OpenAI.
- Configurable prompt templates, note-type field mappings, and overwrite confirmation.
- OpenAI Responses API integration using the official Python client with retries and timeouts.
- Background batch processing with partial-failure reporting.
- Updated installation, configuration, and architecture documentation.
