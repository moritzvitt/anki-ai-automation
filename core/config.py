from __future__ import annotations

from pathlib import Path
from typing import Any

from aqt import mw

from .automation_files import (
    import_legacy_automation_to_files,
    load_automation_files,
    ordered_automation_values,
    save_automation_items,
)
from .config_models import (
    AddonConfig,
    ConfigError,
    FieldMapping,
    ProcessingPreset,
    SavedPrompt,
    SavedSystemPrompt,
    Workflow,
    WorkflowGroup,
    new_object_id,
)
from .config_parsing import (
    parse_field_mapping,
    parse_workflow_entry,
    parse_workflow_group_entry,
    read_bool,
    read_float,
    read_int,
    read_legacy_compatible_string,
    read_legacy_saved_prompts,
    read_legacy_workflow_entries,
    read_legacy_workflow_groups,
    read_model_pricing,
    read_optional_choice,
    read_optional_float,
    read_optional_string,
    read_optional_string_list,
    read_optional_string_list_map,
    read_optional_string_map,
    read_string,
    read_string_list,
    resolved_prompt_id,
    resolved_system_prompt_id,
)
from .config_prompt_library import (
    import_legacy_prompts_to_files,
    import_legacy_system_prompts_to_files,
    load_prompt_files,
    load_system_prompt_files,
    prompt_path_for_id,
    prompt_config_scope,
    prune_removed_system_prompt_files,
    prune_removed_user_prompt_files,
    target_prompt_path,
)
from .prompt_files import read_prompt_order, write_prompt_markdown


ADDON_NAME = __name__.split(".")[0]
PROMPT_LIBRARY_ROOT = Path(__file__).resolve().parent.parent / "prompt_library"
DEFAULT_PROMPTS_DIR = PROMPT_LIBRARY_ROOT / "default_prompts"
USER_PROMPTS_DIR = PROMPT_LIBRARY_ROOT / "user_prompts"
SYSTEM_PROMPTS_DIR = PROMPT_LIBRARY_ROOT / "system_prompts"
SAVED_PROMPT_ORDER_KEY = "saved_prompt_order"
SAVED_SYSTEM_PROMPT_ORDER_KEY = "saved_system_prompt_order"
AUTOMATION_LIBRARY_ROOT = Path(__file__).resolve().parent.parent / "automation_library"
DEFAULT_GROUPS_DIR = AUTOMATION_LIBRARY_ROOT / "groups"
DEFAULT_WORKFLOWS_DIR = AUTOMATION_LIBRARY_ROOT / "workflows"
USER_GROUPS_DIR = Path(__file__).resolve().parent.parent / "user_data" / "groups"
USER_WORKFLOWS_DIR = Path(__file__).resolve().parent.parent / "user_data" / "workflows"
WORKFLOW_GROUP_ORDER_KEY = "workflow_group_order"
WORKFLOW_ORDER_KEY = "workflow_order"
DEFAULT_SYSTEM_PROMPT_ID = "default-system-prompt"


def load_config() -> AddonConfig:
    if mw is None:
        raise ConfigError("Anki main window is not available.")

    raw = mw.addonManager.getConfig(ADDON_NAME)
    if not isinstance(raw, dict):
        raise ConfigError("The add-on config could not be loaded.")

    enabled = bool(raw.get("enabled", True))
    show_tooltips = read_bool(raw, "show_tooltips", default=True)
    use_chat_completions_api = read_bool(raw, "use_chat_completions_api", default=True)
    api_key = read_string(raw, "openai_api_key", allow_empty=True)
    model = read_string(raw, "model", default="gpt-5-mini")
    legacy_default_prompt_template = read_optional_string(raw, "prompt_template") or ""
    legacy_default_system_prompt = read_optional_string(raw, "system_prompt") or ""
    batch_size = read_int(raw, "batch_size", minimum=1, default=20)
    max_parallel_requests = read_int(raw, "max_parallel_requests", minimum=1, default=4)
    request_timeout_seconds = read_float(raw, "request_timeout_seconds", minimum=1.0, default=90.0)
    max_retries = read_int(raw, "max_retries", minimum=0, default=2)
    retry_backoff_seconds = read_float(raw, "retry_backoff_seconds", minimum=0.0, default=2.0)
    temperature = read_optional_float(raw, "temperature", minimum=0.0, maximum=2.0)
    show_estimate_before_sending = read_bool(raw, "show_estimate_before_sending", default=True)
    estimated_output_tokens_per_note = read_int(raw, "estimated_output_tokens_per_note", minimum=1, default=200)
    usage_history_limit = read_int(raw, "usage_history_limit", minimum=1, default=20)
    reasoning_effort = read_optional_choice(
        raw,
        "reasoning_effort",
        allowed={"minimal", "low", "medium", "high"},
    )
    model_pricing = read_model_pricing(raw.get("model_pricing", {}))
    prompt_history = read_optional_string_list(raw.get("prompt_history", []), "prompt_history")

    field_mappings_raw = raw.get("field_mappings", [])
    if not isinstance(field_mappings_raw, list) or not field_mappings_raw:
        raise ConfigError("Config key 'field_mappings' must be a non-empty list.")
    field_mappings = [parse_field_mapping(item, index=index) for index, item in enumerate(field_mappings_raw)]

    saved_prompts = _read_saved_prompts(raw, fallback_prompt_template=legacy_default_prompt_template)
    saved_system_prompts = _read_saved_system_prompts(
        raw,
        fallback_system_prompt=legacy_default_system_prompt,
    )
    default_prompt_template = _default_prompt_text(raw, saved_prompts, legacy_default_prompt_template)
    system_prompt = _default_system_prompt_text(raw, saved_system_prompts, legacy_default_system_prompt)
    processing_presets = _read_processing_presets(
        raw.get("saved_processing_presets", []),
        saved_prompts=saved_prompts,
        saved_system_prompts=saved_system_prompts,
    )
    workflow_groups = _read_workflow_groups(raw)
    workflows = _read_workflows(
        raw,
        saved_prompts=saved_prompts,
        workflow_groups=workflow_groups,
        saved_system_prompts=saved_system_prompts,
    )
    return AddonConfig(
        enabled=enabled,
        show_tooltips=show_tooltips,
        use_chat_completions_api=use_chat_completions_api,
        api_key=api_key,
        model=model,
        default_prompt_template=default_prompt_template,
        system_prompt=system_prompt,
        batch_size=batch_size,
        max_parallel_requests=max_parallel_requests,
        request_timeout_seconds=request_timeout_seconds,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
        show_estimate_before_sending=show_estimate_before_sending,
        estimated_output_tokens_per_note=estimated_output_tokens_per_note,
        usage_history_limit=usage_history_limit,
        model_pricing=model_pricing,
        prompt_history=prompt_history,
        field_mappings=field_mappings,
        saved_prompts=saved_prompts,
        saved_system_prompts=saved_system_prompts,
        processing_presets=processing_presets,
        workflow_groups=workflow_groups,
        workflows=workflows,
    )


def load_raw_config() -> dict[str, Any]:
    if mw is None:
        raise ConfigError("Anki main window is not available.")

    raw = mw.addonManager.getConfig(ADDON_NAME)
    if not isinstance(raw, dict):
        raise ConfigError("The add-on config could not be loaded.")
    return dict(raw)


def save_raw_config(raw_config: dict[str, Any]) -> None:
    if mw is None:
        raise ConfigError("Anki main window is not available.")
    config_scope = prompt_config_scope(raw_config)
    config_scope.pop("saved_prompts", None)
    config_scope.pop("saved_system_prompts", None)
    config_scope.pop("prompt_template", None)
    config_scope.pop("system_prompt", None)
    mw.addonManager.writeConfig(ADDON_NAME, raw_config)


def save_saved_prompts(raw_config: dict[str, Any], prompts: list[Any]) -> None:
    config_scope = prompt_config_scope(raw_config)
    ordered_ids: list[str] = []
    seen_ids: set[str] = set()
    for prompt in prompts:
        prompt_id = str(getattr(prompt, "prompt_id", "")).strip()
        name = str(getattr(prompt, "name", "")).strip()
        prompt_text = str(getattr(prompt, "prompt_text", "")).strip()
        if not prompt_id or not name or not prompt_text:
            continue
        write_prompt_markdown(
            target_prompt_path(
                prompt_id,
                default_prompts_dir=DEFAULT_PROMPTS_DIR,
                user_prompts_dir=USER_PROMPTS_DIR,
            ),
            name,
            prompt_text,
        )
        if prompt_id not in seen_ids:
            ordered_ids.append(prompt_id)
            seen_ids.add(prompt_id)

    prune_removed_user_prompt_files(seen_ids, user_prompts_dir=USER_PROMPTS_DIR)
    config_scope["saved_prompts"] = []
    config_scope[SAVED_PROMPT_ORDER_KEY] = ordered_ids
    if ordered_ids:
        config_scope["default_prompt_id"] = _default_prompt_id_from_raw(config_scope, ordered_ids)
    else:
        config_scope.pop("default_prompt_id", None)
    save_raw_config(raw_config)


def save_saved_system_prompts(raw_config: dict[str, Any], prompts: list[Any]) -> None:
    config_scope = prompt_config_scope(raw_config)
    ordered_ids: list[str] = []
    seen_ids: set[str] = set()
    for prompt in prompts:
        prompt_id = str(getattr(prompt, "prompt_id", "")).strip()
        name = str(getattr(prompt, "name", "")).strip()
        prompt_text = str(getattr(prompt, "prompt_text", "")).strip()
        if not prompt_id or not name or not prompt_text:
            continue
        write_prompt_markdown(prompt_path_for_id(SYSTEM_PROMPTS_DIR, prompt_id), name, prompt_text)
        if prompt_id not in seen_ids:
            ordered_ids.append(prompt_id)
            seen_ids.add(prompt_id)

    prune_removed_system_prompt_files(seen_ids, system_prompts_dir=SYSTEM_PROMPTS_DIR)
    config_scope["saved_system_prompts"] = []
    config_scope[SAVED_SYSTEM_PROMPT_ORDER_KEY] = ordered_ids
    if ordered_ids:
        config_scope["default_system_prompt_id"] = _default_system_prompt_id_from_raw(config_scope, ordered_ids)
    else:
        config_scope.pop("default_system_prompt_id", None)
    save_raw_config(raw_config)


def save_workflow_state(
    raw_config: dict[str, Any],
    workflow_groups: list[WorkflowGroup],
    workflows: list[Workflow],
) -> None:
    config_scope = prompt_config_scope(raw_config)
    group_ids = save_automation_items(
        workflow_groups,
        default_dir=DEFAULT_GROUPS_DIR,
        user_dir=USER_GROUPS_DIR,
        item_id_getter=lambda group: group.group_id,
        item_to_dict=_automation_item_to_dict,
    )
    workflow_ids = save_automation_items(
        workflows,
        default_dir=DEFAULT_WORKFLOWS_DIR,
        user_dir=USER_WORKFLOWS_DIR,
        item_id_getter=lambda workflow: workflow.workflow_id,
        item_to_dict=_automation_item_to_dict,
    )
    config_scope["workflow_groups"] = []
    config_scope["workflows"] = []
    config_scope[WORKFLOW_GROUP_ORDER_KEY] = group_ids
    config_scope[WORKFLOW_ORDER_KEY] = workflow_ids
    save_raw_config(raw_config)


def _read_saved_prompts(raw_config: dict[str, Any], *, fallback_prompt_template: str) -> list[SavedPrompt]:
    file_prompts, file_order = load_prompt_files(
        default_prompts_dir=DEFAULT_PROMPTS_DIR,
        user_prompts_dir=USER_PROMPTS_DIR,
    )
    config_scope = prompt_config_scope(raw_config)
    legacy_entries = read_legacy_saved_prompts(config_scope.get("saved_prompts", []))
    if legacy_entries:
        imported = import_legacy_prompts_to_files(
            file_prompts=file_prompts,
            legacy_prompts=legacy_entries,
            user_prompts_dir=USER_PROMPTS_DIR,
        )
        if imported:
            file_prompts, file_order = load_prompt_files(
                default_prompts_dir=DEFAULT_PROMPTS_DIR,
                user_prompts_dir=USER_PROMPTS_DIR,
            )
        config_scope["saved_prompts"] = []
        save_raw_config(raw_config)

    if not file_prompts:
        return [SavedPrompt(prompt_id="default-prompt", name="Default prompt", prompt_text=fallback_prompt_template)]

    configured_order = read_prompt_order(config_scope.get(SAVED_PROMPT_ORDER_KEY))
    ordered_ids = configured_order or file_order
    prompts: list[SavedPrompt] = []
    seen_ids: set[str] = set()
    for prompt_id in ordered_ids:
        prompt = file_prompts.get(prompt_id)
        if prompt is None or prompt_id in seen_ids:
            continue
        prompts.append(prompt)
        seen_ids.add(prompt_id)
    for prompt_id in file_order:
        if prompt_id in seen_ids:
            continue
        prompts.append(file_prompts[prompt_id])
        seen_ids.add(prompt_id)
    return prompts


def _read_workflow_groups(raw_config: dict[str, Any]) -> list[WorkflowGroup]:
    config_scope = prompt_config_scope(raw_config)
    file_groups, file_order = load_automation_files(
        DEFAULT_GROUPS_DIR,
        USER_GROUPS_DIR,
        parser=parse_workflow_group_entry,
        item_id_getter=lambda group: group.group_id,
    )
    legacy_groups = read_legacy_workflow_groups(config_scope.get("workflow_groups", []))
    if legacy_groups:
        if import_legacy_automation_to_files(
            USER_GROUPS_DIR,
            legacy_groups,
            item_id_getter=lambda group: str(group.group_id),
            item_to_dict=_automation_item_to_dict,
            default_dir=DEFAULT_GROUPS_DIR,
        ):
            file_groups, file_order = load_automation_files(
                DEFAULT_GROUPS_DIR,
                USER_GROUPS_DIR,
                parser=parse_workflow_group_entry,
                item_id_getter=lambda group: group.group_id,
            )
        config_scope["workflow_groups"] = []
        save_raw_config(raw_config)
    return ordered_automation_values(file_groups, config_scope.get(WORKFLOW_GROUP_ORDER_KEY), file_order)


def _read_saved_system_prompts(raw_config: dict[str, Any], *, fallback_system_prompt: str) -> list[SavedSystemPrompt]:
    file_prompts, file_order = load_system_prompt_files(system_prompts_dir=SYSTEM_PROMPTS_DIR)
    config_scope = prompt_config_scope(raw_config)
    legacy_prompts = _read_legacy_saved_system_prompts(config_scope.get("saved_system_prompts", []))
    if legacy_prompts:
        imported = import_legacy_system_prompts_to_files(
            file_prompts=file_prompts,
            legacy_prompts=legacy_prompts,
            system_prompts_dir=SYSTEM_PROMPTS_DIR,
        )
        if imported:
            file_prompts, file_order = load_system_prompt_files(system_prompts_dir=SYSTEM_PROMPTS_DIR)
        config_scope["saved_system_prompts"] = []
        save_raw_config(raw_config)

    if not file_prompts:
        return [
            SavedSystemPrompt(
                prompt_id=DEFAULT_SYSTEM_PROMPT_ID,
                name="Default system prompt",
                prompt_text=fallback_system_prompt,
            )
        ]

    configured_order = read_prompt_order(config_scope.get(SAVED_SYSTEM_PROMPT_ORDER_KEY))
    ordered_ids = configured_order or file_order
    prompts: list[SavedSystemPrompt] = []
    seen_ids: set[str] = set()
    for prompt_id in ordered_ids:
        prompt = file_prompts.get(prompt_id)
        if prompt is None or prompt_id in seen_ids:
            continue
        prompts.append(prompt)
        seen_ids.add(prompt_id)
    for prompt_id in file_order:
        if prompt_id in seen_ids:
            continue
        prompts.append(file_prompts[prompt_id])
        seen_ids.add(prompt_id)
    return prompts


def _read_legacy_saved_system_prompts(value: Any) -> list[SavedSystemPrompt]:
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise ConfigError("Config key 'saved_system_prompts' must be a list.")

    prompts: list[SavedSystemPrompt] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ConfigError(f"saved_system_prompts[{index}] must be an object.")
        prompt_id = read_string(item, "id", default=f"system-prompt-{index + 1}")
        if prompt_id in seen_ids:
            raise ConfigError(f"saved_system_prompts[{index}] uses duplicate id '{prompt_id}'.")
        seen_ids.add(prompt_id)
        prompts.append(
            SavedSystemPrompt(
                prompt_id=prompt_id,
                name=read_string(item, "name"),
                prompt_text=read_string(item, "prompt"),
            )
        )
    return prompts


def _default_prompt_id_from_raw(config_scope: dict[str, Any], ordered_ids: list[str]) -> str:
    configured = read_optional_string(config_scope, "default_prompt_id")
    if configured and configured in ordered_ids:
        return configured
    if "general/default-prompt" in ordered_ids:
        return "general/default-prompt"
    if "default-prompt" in ordered_ids:
        return "default-prompt"
    return ordered_ids[0]


def _default_system_prompt_id_from_raw(config_scope: dict[str, Any], ordered_ids: list[str]) -> str:
    configured = read_optional_string(config_scope, "default_system_prompt_id")
    if configured and configured in ordered_ids:
        return configured
    if DEFAULT_SYSTEM_PROMPT_ID in ordered_ids:
        return DEFAULT_SYSTEM_PROMPT_ID
    return ordered_ids[0]


def _default_prompt_text(raw_config: dict[str, Any], prompts: list[SavedPrompt], fallback: str) -> str:
    if not prompts:
        return fallback
    config_scope = prompt_config_scope(raw_config)
    default_id = _default_prompt_id_from_raw(config_scope, [prompt.prompt_id for prompt in prompts])
    for prompt in prompts:
        if prompt.prompt_id == default_id:
            return prompt.prompt_text
    return prompts[0].prompt_text


def _default_system_prompt_text(raw_config: dict[str, Any], prompts: list[SavedSystemPrompt], fallback: str) -> str:
    if not prompts:
        return fallback
    config_scope = prompt_config_scope(raw_config)
    default_id = _default_system_prompt_id_from_raw(config_scope, [prompt.prompt_id for prompt in prompts])
    for prompt in prompts:
        if prompt.prompt_id == default_id:
            return prompt.prompt_text
    return prompts[0].prompt_text


def _read_processing_presets(
    value: Any,
    *,
    saved_prompts: list[SavedPrompt],
    saved_system_prompts: list[SavedSystemPrompt],
) -> list[ProcessingPreset]:
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise ConfigError("Config key 'saved_processing_presets' must be a list.")

    allowed_prompt_ids = {prompt.prompt_id for prompt in saved_prompts}
    allowed_system_prompt_ids = {prompt.prompt_id for prompt in saved_system_prompts}
    allowed_modes = {"append", "overwrite", "skip_nonempty"}
    presets: list[ProcessingPreset] = []
    seen_ids: set[str] = set()

    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ConfigError(f"saved_processing_presets[{index}] must be an object.")

        preset_id = read_string(item, "id", default=f"processing-preset-{index + 1}")
        if preset_id in seen_ids:
            raise ConfigError(f"saved_processing_presets[{index}] uses duplicate id '{preset_id}'.")
        seen_ids.add(preset_id)

        prompt_id = read_string(item, "prompt_id")
        resolved_preset_prompt_id = resolved_prompt_id(prompt_id, allowed_prompt_ids=allowed_prompt_ids)
        invalid_reason = None
        if resolved_preset_prompt_id is None:
            resolved_preset_prompt_id = prompt_id
            invalid_reason = f"Missing saved prompt: '{prompt_id}'."

        system_prompt_id = resolved_system_prompt_id(
            read_optional_string(item, "system_prompt_id"),
            allowed_system_prompt_ids=allowed_system_prompt_ids,
        )

        mode = read_string(item, "mode", default="overwrite")
        if mode not in allowed_modes:
            raise ConfigError("Processing preset mode must be 'append', 'overwrite', or 'skip_nonempty'.")

        multiple_target_fields = read_bool(item, "multiple_target_fields", default=False)
        response_delimiter = read_optional_string(item, "response_delimiter")
        if multiple_target_fields and not response_delimiter:
            raise ConfigError(
                f"saved_processing_presets[{index}] enables multiple_target_fields but has no response_delimiter."
            )

        presets.append(
            ProcessingPreset(
                preset_id=preset_id,
                name=read_string(item, "name"),
                prompt_id=resolved_preset_prompt_id,
                invalid_reason=invalid_reason,
                description=read_optional_string(item, "description"),
                model=read_optional_string(item, "model"),
                temperature=read_optional_float(item, "temperature", minimum=0.0, maximum=2.0),
                system_prompt_id=system_prompt_id,
                target_field=read_legacy_compatible_string(
                    item,
                    "target_field",
                    aliases=("targetfield", "targetField"),
                    default="",
                    allow_empty=True,
                ),
                mode=mode,
                multiple_target_fields=multiple_target_fields,
                convert_markdown_to_html=read_bool(item, "convert_markdown_to_html", default=True),
                convert_field_html_to_markdown=read_bool(item, "convert_field_html_to_markdown", default=False),
                response_delimiter=response_delimiter,
            )
        )

    return presets


def _read_workflows(
    raw_config: dict[str, Any],
    *,
    saved_prompts: list[SavedPrompt],
    workflow_groups: list[WorkflowGroup],
    saved_system_prompts: list[SavedSystemPrompt] | None = None,
) -> list[Workflow]:
    config_scope = prompt_config_scope(raw_config)
    allowed_prompt_ids = {prompt.prompt_id for prompt in saved_prompts}
    allowed_system_prompt_ids = {prompt.prompt_id for prompt in (saved_system_prompts or [])}
    allowed_group_ids = {group.group_id for group in workflow_groups}
    parser = lambda item, index: parse_workflow_entry(
        item,
        index=index,
        allowed_prompt_ids=allowed_prompt_ids,
        allowed_system_prompt_ids=allowed_system_prompt_ids,
        allowed_group_ids=allowed_group_ids,
        allowed_modes={"append", "overwrite", "skip_nonempty"},
        allowed_workflow_types={"field_update", "script"},
        allowed_api_modes={"global_default", "responses", "chat_completions"},
    )
    file_workflows, file_order = load_automation_files(
        DEFAULT_WORKFLOWS_DIR,
        USER_WORKFLOWS_DIR,
        parser=parser,
        item_id_getter=lambda workflow: workflow.workflow_id,
    )
    legacy_workflows = read_legacy_workflow_entries(config_scope.get("workflows", []))
    if legacy_workflows:
        if import_legacy_automation_to_files(
            USER_WORKFLOWS_DIR,
            legacy_workflows,
            item_id_getter=lambda workflow: str(workflow.get("id", "")),
            item_to_dict=_automation_item_to_dict,
            default_dir=DEFAULT_WORKFLOWS_DIR,
        ):
            file_workflows, file_order = load_automation_files(
                DEFAULT_WORKFLOWS_DIR,
                USER_WORKFLOWS_DIR,
                parser=parser,
                item_id_getter=lambda workflow: workflow.workflow_id,
            )
        config_scope["workflows"] = []
        save_raw_config(raw_config)
    return ordered_automation_values(file_workflows, config_scope.get(WORKFLOW_ORDER_KEY), file_order)


def _automation_item_to_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, WorkflowGroup):
        return {"id": item.group_id, "name": item.name}
    if isinstance(item, Workflow):
        return {
            "id": item.workflow_id,
            "name": item.name,
            "query": item.query,
            "workflow_type": item.workflow_type,
            "enabled": item.enabled,
            "script_command": item.script_command,
            "prompt_id": item.prompt_id,
            "target_field": item.target_field,
            "mode": item.mode,
            "model": item.model,
            "temperature": item.temperature,
            "api_mode": item.api_mode,
            "system_prompt_id": item.system_prompt_id,
            "multiple_target_fields": item.multiple_target_fields,
            "convert_markdown_to_html": item.convert_markdown_to_html,
            "convert_field_html_to_markdown": item.convert_field_html_to_markdown,
            "response_delimiter": item.response_delimiter,
            "success_tags": item.success_tags,
            "failure_tags": item.failure_tags,
            "trigger_on_startup": item.trigger_on_startup,
            "trigger_on_periodic": item.trigger_on_periodic,
            "trigger_min_matches": item.trigger_min_matches,
            "group_ids": [item.group_id] if item.group_id else [],
            "group_id": item.group_id,
            "position": item.position,
        }
    if isinstance(item, dict):
        return item
    raise TypeError(f"Unsupported automation item type: {type(item)!r}")
