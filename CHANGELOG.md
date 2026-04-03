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

### Changed

- Reorganized the codebase into `core/`, `ui/`, and `services/` packages to keep related modules together.
- Workflow previews now show trigger details and multiple group memberships.
- Workflow group filtering and group runs now include workflows that belong to more than one group.

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
