# Architecture

## Overview

AI Automation is organized around three main areas:

- `core/` for workflow definitions, config parsing, prompt rendering, and processing logic
- `services/` for OpenAI-facing integrations such as model lookup, pricing, billing, and request execution
- `ui/` for Browser actions, workflow dialogs, configuration dialogs, menus, and user-facing controls

The add-on registers its startup hooks from `__init__.py` and `addon.py`, then exposes actions through the shared `Moritz Add-ons` menu and Browser integrations.

## Main Entry Points

- `__init__.py`: Anki import entry point
- `addon.py`: add-on bootstrap and hook wiring
- `ui/browser_menu.py`: Browser actions
- `ui/top_level_menu.py`: main window menu integration

## Core Modules

- `core/workflow_engine.py`: executes workflow steps against note sets
- `core/processing.py`: main note-processing orchestration
- `core/prompting.py`: prompt rendering from note content
- `core/config*.py`: config models, parsing, and defaults
- `core/automation_files.py` and `core/prompt_files.py`: persisted workflow and prompt storage

## Service Layer

- `services/openai_client.py`: OpenAI request handling
- `services/model_catalog.py`: model metadata
- `services/pricing.py` and `services/billing.py`: pricing and spend support

## UI Layer

- `ui/automation.py`: automation and workflow UI
- `ui/workflow.py` and `ui/workflow_dialog.py`: workflow editing and execution dialogs
- `ui/config_dialog.py`: add-on configuration
- `ui/editor_actions.py`: editor-facing actions where applicable

## Shared Workspace Conventions

- `shared_menu.py`: integrates with the shared `Moritz Add-ons` top-level menu
- `shared_styling.py`: applies optional global styling when the `Global Styling` add-on is installed

## Data Flow

1. The user starts a Browser action or workflow.
2. A query or selection resolves to note IDs.
3. Prompt templates are rendered from note fields.
4. The OpenAI client executes the configured request.
5. Results are written back to one or more note fields according to the selected write mode.

## Supporting Files

- `config.json`: add-on defaults
- `config.md`: config documentation
- `manifest.json`: Anki metadata
- `tools/package_ankiaddon.py`: packaging helper
