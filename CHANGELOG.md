# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and this project follows semantic versioning where practical.

## Unreleased

### Added

- A Browser `Audit with AI` action for `Moritz Language Reactor` notes that performs a diagnostic-only audit without rewriting study content fields.
- A branch naming convention doc under `docs/release/branch-naming.md` so future work can use short, consistent branch names like `feature/browser-prompt-library-picker`.
- Browser context-menu actions to run enabled workflows or whole workflow groups directly on the current Browser selection instead of relying on each workflow's saved query matches.
- A separate `browser_extensions` Browser module with a direct `Quick Add Existing Tag` Browser submenu for applying already-existing collection tags to the selected Browser notes, making that feature easier to split into its own add-on later.
- A determinate progress bar with interrupt support for Browser audits, workflow runs, and Browser prompt/preset runs so note-processing jobs always show visible progress while they work.
- A user-defined `MLR Audit Major Rework` workflow group plus a companion `MLR Rework Fix Major` pipeline and dedicated prompts for drafting `FIXABLE_MAJOR` follow-up content into `AI Notes`, `AI Japanese Notes`, and `AI Grammar`, while still filling the real target fields directly when they are empty.
- A structured stage-1 audit pipeline with strict JSON validation, status-based tagging, and local audit metadata persistence in `user_data/audit_log.json`.
- Dedicated audit prompt/schema and storage modules so a later auto-fix stage can reuse the validated audit output cleanly.
- A separate pipeline orchestration layer above workflows and groups, with config-defined note selection, declarative conditions, and per-note branching support.
- A new `Run AI Pipeline` Tools menu action for launching enabled pipelines from inside Anki.
- A first seeded `MLR Audit First 15` pipeline plus follow-up MLR audit workflows in both the shipped config template and the live profile config.
- Typed workflows with first-class `field_update` and `audit` workflow types.
- A real visible `mlr-audit` workflow that can be edited, listed, and referenced by pipelines like any other workflow.
- Per-row `Enabled` checkboxes in the workflow manager so workflows can be toggled without opening the editor.
- A Tools action to backfill the optional `AI Audit ...` note fields from the stored audit log after those fields are added to a note type.
- A dedicated `MLR Fix Minor -> Grammar` follow-up workflow and prompt so audit-driven support-field fixes can cover `Grammar` as well as `Japanese Notes`, `Notes`, and `Word Definition`.
- A `suspend_cards` pipeline step and an `artifact_contains` condition operator for declarative per-note branching on validated list artifacts.
- A Tools action to migrate older underscore-style AI tags such as `ai_good` and `mark` to the newer Anki tag-tree format under `ai::...`.
- A file-backed automation library under `automation_library/` plus a migration tool that exports shipped workflows, groups, and pipelines into individual `.yaml` files.

### Changed

- Workflow and preset loading now fall back to `default-system-prompt` for normal runs and `mlr-audit-system` for audit workflows when a saved `system_prompt_id` no longer exists, so stale user automation files do not block Browser audits or config loading.
- Workflow loading now allows empty saved queries, the workflow editor can save query-less workflows for Browser-selected note runs, and creating a new workflow from the manager no longer fails on a missing ID helper import.
- Pipeline loading now drops stale `run_workflow` and `run_group` steps that reference deleted automation items instead of aborting startup, while still rejecting pipelines that would become completely empty.
- OpenAI requests and input-token estimation now retry with a safer `reasoning.effort` fallback when chat-latest GPT-5 models reject the configured effort level.
- Prompt selection in the Browser AI dialog and workflow editor now uses a prompt-library file picker instead of a flat dropdown, and prompt loading/saving now supports nested folders under `prompt_library/default_prompts` and `prompt_library/user_prompts`.
- The shipped and user prompt libraries are now grouped into clearer subfolders by purpose, and the bundled MLR audit loader now follows the new nested default-prompt path.
- Legacy preset and workflow prompt IDs now resolve more safely after prompt-file renames, including explicit aliases for shipped default prompts and renamed user prompts in the MLR prompt folder.
- The built-in fallback OpenAI model catalog now includes the current GPT-5 chat/pro aliases plus manual fallback entries for `gpt-5.3-chat-latest` and `gpt-5.4-chat-latest`, so those models can be selected even when the live model fetch is unavailable.
- Workflow membership is single-group again across config loading, the workflow editor, group filters, Browser group runs, and pipeline group dispatch; older `group_ids` data is still tolerated by collapsing it to the first valid group on load.
- The shipped MLR audit prompt and its follow-up prompts were refreshed to match the newer cloze-focused audit criteria, narrower support-field update scope, and current `FIXABLE_MINOR` follow-up flow.
- Browser audits can now be re-run on already-audited notes, verify persisted audit tags more reliably, refresh the currently open Browser note after a successful audit, and no longer show the temporary audit debug report popup.
- The workflow manager and workflow editor now load again after the YAML/prompt refactor, and prompt editing in the workflow dialog now uses explicit save buttons while forking shipped default prompts into new user prompts instead of overwriting the defaults.
- Shipped default prompts are now protected from in-place edits across the prompt UIs, with edited defaults being saved as new user prompts with a unique suffix, and several MLR prompt texts were refreshed to match the current audit and follow-up flow.
- Running workflows from the workflow manager now resolves query note IDs correctly again instead of failing with a missing helper error.
- Field-update workflows can now add configurable success and failure tags, and the workflow editor exposes those tags directly for normal field-update workflows.
- Field-update workflow note writes are now deferred and applied on the main thread, which makes manually run workflows and pipeline-driven field updates more stable on macOS.
- Pipeline tag steps and card-suspension steps now defer their Anki mutations until the main thread, reducing crashes from background-thread UI/collection interactions.
- Delimited multi-field parsing now accepts `{Field Name}` section headers and keeps valid partial field updates even when some requested sections are missing or malformed.
- The seeded MLR follow-up workflows now add explicit success and failure tags so fixed and failed notes can be filtered more easily after audit-driven processing.
- AI audit/fix tags now use Anki’s native tag-tree format like `ai::audit::good`, `ai::fix::minor`, and `ai::review::manual`, and the persistent `done_today` tag has been replaced with the more accurate `ai::audit::processed`.
- Simplified the core settings dialog by removing prompt fields, adding a clearer add-on summary, renaming the model selector to `Default model`, and adding a button that opens Anki's built-in raw JSON config editor.
- Added a Responses API helper for strict JSON-schema audit requests, and preserved Browser selection order so the first 15 selected notes can be audited predictably.
- Workflows now expose reusable execution hooks so pipelines can orchestrate atomic workflow runs without duplicating prompt/update logic, and pipelines now dispatch workflows uniformly by workflow ID instead of using a special audit-only execution path.
- The config docs now document `pipelines` and note that workflow and pipeline queries can use `limit:x` when the separate `limit-search-results` add-on is installed.
- Workflow config loading is now more tolerant of older saved key names and correctly allows empty `target_field` values for audit workflows.
- Audit workflow side effects now apply on the main thread after background execution, which makes Browser audits and pipeline audits more stable and avoids mutating notes from the worker thread.
- The seeded `MLR Audit First 15` pipeline now runs the audit and then conditionally executes field-specific follow-up workflows for `FIXABLE_MINOR` notes in one pass.
- Rejected notes in the seeded MLR audit pipeline are now tagged `ai::review::mark` and have their cards suspended automatically.
- Prompt preparation now strips HTML from both `Cloze` and `Subtitle` before any API request is sent, including audits and normal field-update workflows.
- The architecture docs were refreshed to match the typed workflow model, pipeline branching behavior, and current MLR audit-follow-up flow.
- The sample audit pipeline docs and standalone Mermaid diagram were updated to show the current seeded follow-up branches and reject-handling path instead of the earlier audit-only prototype.
- The docs tree is now organized more clearly into `docs/architecture`, `docs/release`, and `docs/for me`, and includes a dedicated note explaining how audit prompts and schemas are combined into structured requests.
- Prompt storage now treats markdown files as the source of truth: shipped prompts live in `prompt_library/default_prompts`, user-created prompts live in `prompt_library/user_prompts`, and legacy saved prompts from config are imported into markdown files instead of remaining embedded in Anki config JSON.
- Markdown-to-HTML conversion is now enabled by default for new Browser runs and workflows, and the seeded MLR audit-related workflows and presets now default to HTML conversion as well.
- The MLR audit follow-up workflows are now modeled consistently: the four field-specific follow-up workflows use single-target output mode, and a separate combined-support-fields workflow is available in its own group for one-shot follow-up runs.
- Workflows, groups, and pipelines are no longer stored as large embedded JSON arrays in `config.json` / `meta.json`; the JSON config now keeps only ordering metadata while live automation definitions are loaded from per-file YAML storage.
- Shipped default prompts used by the Browser prompt picker now all follow the normal markdown `# Heading` prompt-file format, so runtime-only defaults do not break the saved-prompt loader.
- Split the bulky workflow/config implementation into smaller helper modules so automation file storage, prompt file handling, YAML parsing, and the workflow editor dialog are easier to maintain, and fixed the per-file automation loader so workflow triggers can parse YAML-backed groups/workflows at startup again.

### Removed

- Removed the older shipped MLR maintenance, audit-follow-up, and card-optimization workflow/group YAML definitions plus the corresponding `FIXABLE_MAJOR` rework workflow YAMLs from `user_data`, reducing the prompt-focused branch back down to the automation set that is still actively used.

## 1.1.0 - 2026-04-03

### Added

- Workflow triggers that can run automatically on profile startup or when a query condition becomes true.
- Trigger conditions based on workflow query match counts, including thresholds such as "run when at least N notes match".
- A `skip if target field not empty` write mode for Browser runs and workflows.
- Hover help tooltips across the config dialog, Browser dialog, and workflow manager, plus a config option to disable all tooltips.
- Support for assigning a workflow to multiple groups instead of only one.
- A VS Code task and formatter script to pretty-print `meta.json` safely.
- Inline prompt and system prompt editors in the workflow dialog.
- A Browser AI settings dialog for managing Browser presets, prompts, and defaults outside an active run.
- A config option to use the Chat Completions API for generation, enabled by default so Browser runs can be compared directly against the Responses API.

### Changed

- Reorganized the codebase into `core/`, `ui/`, and `services/` packages to keep related modules together.
- Workflow previews now show trigger details and multiple group memberships.
- Workflow group filtering and group runs now include workflows that belong to more than one group.
- The main config dialog now focuses on core settings and links out to dedicated workflow and Browser settings dialogs.
- The default flashcard system prompt no longer forces strict JSON-only output.
- Workflow editing now uses a wider, scrollable layout with collapsible settings sections to make large workflows easier to review.
- Workflow queries now use a single-line input, and workflow group filtering uses clearer wording in the manager.
- Browser AI and saved prompt dialogs now use roomier layouts, including a consistent selection summary area and wider prompt name input.
- Browser `Transform with AI` processing now runs in explicit batches with incremental note updates after each finished batch, making large runs feel more responsive and improving interrupt behavior.
- Browser AI processing now reuses OpenAI clients, caches prompt template parsing, and uses tuned default batch/concurrency settings for steadier throughput.
- Added internal notes documenting the current Browser performance gap versus `anki-smart-notes` and the highest-impact follow-up options.
- Processing presets can now store editable descriptions, and the Browser/workflow preset menus now let you edit preset name and description directly.
- Unsupported temperature-value errors now fall back more gracefully by retrying without `temperature`.

## 1.0.0 - 2026-04-01

### Added

- Browser context-menu integration for processing selected notes with OpenAI.
- Configurable prompt templates, note-type field mappings, and overwrite confirmation.
- OpenAI Responses API integration using the official Python client with retries and timeouts.
- Background batch processing with partial-failure reporting.
- Updated installation, configuration, and architecture documentation.

## 0.1.0 - 2026-03-27

### Added

- Initial Anki add-on starter template.
- Minimal runnable add-on entry point and sample menu action.
- Default Anki config files and documentation placeholders.
- VS Code tasks for validation and packaging.
