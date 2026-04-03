**Findings**
1. Medium: the prompt-library rebuild path has drifted away from the actual prompt inventory. [tools/build_config_from_prompts.py](/Users/moritzvitt/src/addons/ai-automation/tools/build_config_from_prompts.py#L11) still hardcodes an older prompt list and older IDs, while the shipped config now contains newer entries like `mlr-audit-prompt`, `mlr-audit-follow-up-combined`, and `mlr-audit-system`. The result is that `prompt_library/` is now serving two overlapping roles: source-of-truth for rebuildable saved prompts and runtime-only prompt assets. That’s workable, but it’s easy for future prompt additions to land in the library without being integrated consistently.

2. Medium: the typed-workflow architecture is clean overall, but there is still a legacy special case in the pipeline parser. [core/config.py](/Users/moritzvitt/src/addons/ai-automation/core/config.py#L791) still accepts `run_mlr_audit` and rewrites it to `run_workflow` with `mlr-audit`. Since the current design goal is “pipelines call workflows uniformly by ID,” this compatibility shim is now the main remaining structural redundancy in that layer.

3. Low: the repo documentation index is stale enough to hurt discoverability. [README.md](/Users/moritzvitt/src/addons/ai-automation/README.md#L21) shows an old truncated file tree that omits major current modules like `core/pipelines.py`, `core/workflow_engine.py`, `ui/pipelines.py`, `ui/audit_sync.py`, and `ui/tag_migration.py`. [docs/README.md](/Users/moritzvitt/src/addons/ai-automation/docs/README.md#L1) is also too thin now that you have several architecture docs and operational notes. The code organization itself is reasonably coherent; the index docs just haven’t kept up.

**Overall**
The repo structure is mostly good now. The split between [core](/Users/moritzvitt/src/addons/ai-automation/core), [ui](/Users/moritzvitt/src/addons/ai-automation/ui), and [services](/Users/moritzvitt/src/addons/ai-automation/services) is understandable, and the newer workflow/group/pipeline layering is much cleaner than before.

**Smallest useful cleanup next**
- Make `prompt_library/` explicitly split into “saved-prompt source” vs “runtime workflow/audit prompt assets,” or make the rebuild script derive entries from metadata instead of a hardcoded list.
- Remove the `run_mlr_audit` compatibility path once you’re comfortable migrating old configs.
- Refresh [README.md](/Users/moritzvitt/src/addons/ai-automation/README.md) and [docs/README.md](/Users/moritzvitt/src/addons/ai-automation/docs/README.md) so the documented structure matches the real one.

**Optional cleanup**
- Your local repo root also contains non-repo clutter like `.uv-cache`, `venv-ai-automation`, and `__pycache__`. That’s not a structural bug in the codebase itself, but moving or ignoring those consistently would make the workspace feel tidier.