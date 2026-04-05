from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import uuid
from typing import Any

from aqt import mw

from .automation_files import (
    import_legacy_automation_to_files,
    load_automation_files,
    ordered_automation_values,
    save_automation_items,
)
from .prompt_files import read_prompt_markdown, read_prompt_order, write_prompt_markdown
from ..services.pricing import ModelPricing


ADDON_NAME = __name__.split(".")[0]
PROMPT_LIBRARY_ROOT = Path(__file__).resolve().parent.parent / "prompt_library"
DEFAULT_PROMPTS_DIR = PROMPT_LIBRARY_ROOT / "default_prompts"
USER_PROMPTS_DIR = PROMPT_LIBRARY_ROOT / "user_prompts"
SAVED_PROMPT_ORDER_KEY = "saved_prompt_order"
AUTOMATION_LIBRARY_ROOT = Path(__file__).resolve().parent.parent / "automation_library"
DEFAULT_GROUPS_DIR = AUTOMATION_LIBRARY_ROOT / "groups"
DEFAULT_WORKFLOWS_DIR = AUTOMATION_LIBRARY_ROOT / "workflows"
DEFAULT_PIPELINES_DIR = AUTOMATION_LIBRARY_ROOT / "pipelines"
USER_GROUPS_DIR = Path(__file__).resolve().parent.parent / "user_data" / "groups"
USER_WORKFLOWS_DIR = Path(__file__).resolve().parent.parent / "user_data" / "workflows"
USER_PIPELINES_DIR = Path(__file__).resolve().parent.parent / "user_data" / "pipelines"
WORKFLOW_GROUP_ORDER_KEY = "workflow_group_order"
WORKFLOW_ORDER_KEY = "workflow_order"
PIPELINE_ORDER_KEY = "pipeline_order"
DEFAULT_SYSTEM_PROMPT_ID = "default-system-prompt"
DEFAULT_AUDIT_SYSTEM_PROMPT_ID = "mlr-audit-system"
LEGACY_DEFAULT_PROMPT_ID_ALIASES = {
    "default-prompt": "general/default-prompt",
    "card-quality-check": "review/card-quality-check",
    "full-card-optimization": "review/full-card-optimization",
    "update-grammar-notes": "field-updates/update-grammar-notes",
    "update-japanese-notes": "field-updates/update-japanese-notes",
    "mlr-audit": "mlr/audit/mlr-audit",
    "mlr-audit-follow-up-combined": "mlr/audit/mlr-audit-follow-up-combined",
    "mlr-card-quality-check": "mlr/review/mlr-card-quality-check",
    "mlr-cloze-optimization": "mlr/transform/mlr-cloze-optimization",
    "mlr-fix-only-whats-wrong": "mlr/transform/mlr-fix-only-whats-wrong",
    "mlr-full-field-refactor": "mlr/transform/mlr-full-field-refactor",
    "mlr-grammar-field-improver": "mlr/field-updates/mlr-grammar-field-improver",
    "mlr-grammar-notes-generator": "mlr/field-updates/mlr-grammar-notes-generator",
    "mlr-japanese-notes-improver": "mlr/field-updates/mlr-japanese-notes-improver",
    "mlr-word-definition-optimizer": "mlr/field-updates/mlr-word-definition-optimizer",
}


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class FieldMapping:
    note_type: str
    output_fields: list[str]
    prompt_template: str | None = None
    system_prompt: str | None = None


@dataclass(frozen=True)
class SavedPrompt:
    prompt_id: str
    name: str
    prompt_text: str


@dataclass(frozen=True)
class SavedSystemPrompt:
    prompt_id: str
    name: str
    prompt_text: str


@dataclass(frozen=True)
class ProcessingPreset:
    preset_id: str
    name: str
    prompt_id: str
    description: str | None = None
    model: str | None = None
    temperature: float | None = None
    system_prompt_id: str | None = None
    target_field: str = ""
    mode: str = "overwrite"
    multiple_target_fields: bool = False
    convert_markdown_to_html: bool = True
    response_delimiter: str | None = None


@dataclass(frozen=True)
class WorkflowGroup:
    group_id: str
    name: str


@dataclass(frozen=True)
class Workflow:
    workflow_id: str
    name: str
    query: str
    prompt_id: str
    workflow_type: str = "field_update"
    enabled: bool = True
    target_field: str = ""
    mode: str = "overwrite"
    model: str | None = None
    temperature: float | None = None
    api_mode: str | None = None
    system_prompt_id: str | None = None
    multiple_target_fields: bool = False
    convert_markdown_to_html: bool = True
    response_delimiter: str | None = None
    schema_preset: str | None = None
    response_schema_json: str | None = None
    note_type_filter: str | None = None
    clear_status_tags: list[str] | None = None
    status_tag_map: dict[str, str] | None = None
    extra_status_tags: dict[str, list[str]] | None = None
    success_tags: list[str] | None = None
    failure_tags: list[str] | None = None
    metadata_field_map: dict[str, str] | None = None
    store_raw_output: bool = True
    trigger_on_startup: bool = False
    trigger_on_periodic: bool = False
    trigger_min_matches: int = 1
    group_id: str | None = None
    position: int = 0


@dataclass(frozen=True)
class PipelineNoteSelector:
    query: str
    limit: int | None = None


def _resolved_system_prompt_id(
    system_prompt_id: str | None,
    *,
    allowed_system_prompt_ids: set[str],
    workflow_type: str | None = None,
) -> str | None:
    if system_prompt_id is None:
        if workflow_type == "audit":
            return (
                DEFAULT_AUDIT_SYSTEM_PROMPT_ID
                if DEFAULT_AUDIT_SYSTEM_PROMPT_ID in allowed_system_prompt_ids
                else None
            )
        return (
            DEFAULT_SYSTEM_PROMPT_ID
            if DEFAULT_SYSTEM_PROMPT_ID in allowed_system_prompt_ids
            else None
        )
    if system_prompt_id in allowed_system_prompt_ids:
        return system_prompt_id
    if workflow_type == "audit":
        return (
            DEFAULT_AUDIT_SYSTEM_PROMPT_ID
            if DEFAULT_AUDIT_SYSTEM_PROMPT_ID in allowed_system_prompt_ids
            else None
        )
    return (
        DEFAULT_SYSTEM_PROMPT_ID
        if DEFAULT_SYSTEM_PROMPT_ID in allowed_system_prompt_ids
        else None
    )


def _resolved_prompt_id(
    prompt_id: str,
    *,
    allowed_prompt_ids: set[str],
) -> str | None:
    if prompt_id in allowed_prompt_ids:
        return prompt_id

    alias_target = LEGACY_DEFAULT_PROMPT_ID_ALIASES.get(prompt_id)
    if alias_target in allowed_prompt_ids:
        return alias_target

    legacy_basename = prompt_id.strip().split("/")[-1]
    if not legacy_basename:
        return None

    matching_ids = sorted(
        candidate_id
        for candidate_id in allowed_prompt_ids
        if candidate_id.split("/")[-1] == legacy_basename
    )
    if len(matching_ids) == 1:
        return matching_ids[0]
    return None


@dataclass(frozen=True)
class PipelineStep:
    step_id: str
    step_type: str
    workflow_id: str | None = None
    group_id: str | None = None
    add_tags: list[str] | None = None
    remove_tags: list[str] | None = None
    when: dict[str, Any] | None = None


@dataclass(frozen=True)
class Pipeline:
    pipeline_id: str
    name: str
    enabled: bool
    note_selector: PipelineNoteSelector
    steps: list[PipelineStep]


@dataclass(frozen=True)
class AddonConfig:
    enabled: bool
    show_tooltips: bool
    use_chat_completions_api: bool
    api_key: str
    model: str
    default_prompt_template: str
    system_prompt: str
    batch_size: int
    max_parallel_requests: int
    request_timeout_seconds: float
    max_retries: int
    retry_backoff_seconds: float
    temperature: float | None
    reasoning_effort: str | None
    show_estimate_before_sending: bool
    estimated_output_tokens_per_note: int
    usage_history_limit: int
    model_pricing: dict[str, ModelPricing]
    prompt_history: list[str]
    field_mappings: list[FieldMapping]
    saved_prompts: list[SavedPrompt]
    saved_system_prompts: list[SavedSystemPrompt]
    processing_presets: list[ProcessingPreset]
    workflow_groups: list[WorkflowGroup]
    workflows: list[Workflow]
    pipelines: list[Pipeline]


def load_config() -> AddonConfig:
    if mw is None:
        raise ConfigError("Anki main window is not available.")

    raw = mw.addonManager.getConfig(ADDON_NAME)
    if not isinstance(raw, dict):
        raise ConfigError("The add-on config could not be loaded.")

    enabled = bool(raw.get("enabled", True))
    show_tooltips = _read_bool(raw, "show_tooltips", default=True)
    use_chat_completions_api = _read_bool(raw, "use_chat_completions_api", default=True)
    api_key = _read_string(raw, "openai_api_key", allow_empty=True)
    model = _read_string(raw, "model", default="gpt-5-mini")
    default_prompt_template = _read_string(raw, "prompt_template")
    system_prompt = _read_string(raw, "system_prompt")
    batch_size = _read_int(raw, "batch_size", minimum=1, default=20)
    max_parallel_requests = _read_int(raw, "max_parallel_requests", minimum=1, default=4)
    request_timeout_seconds = _read_float(
        raw,
        "request_timeout_seconds",
        minimum=1.0,
        default=90.0,
    )
    max_retries = _read_int(raw, "max_retries", minimum=0, default=2)
    retry_backoff_seconds = _read_float(
        raw,
        "retry_backoff_seconds",
        minimum=0.0,
        default=2.0,
    )
    temperature = _read_optional_float(
        raw,
        "temperature",
        minimum=0.0,
        maximum=2.0,
    )
    show_estimate_before_sending = _read_bool(raw, "show_estimate_before_sending", default=True)
    estimated_output_tokens_per_note = _read_int(
        raw,
        "estimated_output_tokens_per_note",
        minimum=1,
        default=200,
    )
    usage_history_limit = _read_int(raw, "usage_history_limit", minimum=1, default=20)
    reasoning_effort = _read_optional_choice(
        raw,
        "reasoning_effort",
        allowed={"minimal", "low", "medium", "high"},
    )
    model_pricing = _read_model_pricing(raw.get("model_pricing", {}))
    prompt_history = _read_optional_string_list(raw.get("prompt_history", []), "prompt_history")

    field_mappings_raw = raw.get("field_mappings", [])
    if not isinstance(field_mappings_raw, list) or not field_mappings_raw:
        raise ConfigError("Config key 'field_mappings' must be a non-empty list.")

    field_mappings = [_parse_field_mapping(item, index=index) for index, item in enumerate(field_mappings_raw)]

    saved_prompts = _read_saved_prompts(
        raw,
        fallback_prompt_template=default_prompt_template,
    )
    saved_system_prompts = _read_saved_system_prompts(
        raw.get("saved_system_prompts", []),
        fallback_system_prompt=system_prompt,
    )
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
    pipelines = _read_pipelines(
        raw,
        workflows=workflows,
        workflow_groups=workflow_groups,
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
        pipelines=pipelines,
    )


def _parse_field_mapping(value: Any, *, index: int) -> FieldMapping:
    if not isinstance(value, dict):
        raise ConfigError(f"field_mappings[{index}] must be an object.")

    note_type = _read_string(value, "note_type", default="*")
    output_fields = _read_string_list(value, "output_fields")
    prompt_template = _read_optional_string(value, "prompt_template")
    system_prompt = _read_optional_string(value, "system_prompt")

    return FieldMapping(
        note_type=note_type,
        output_fields=output_fields,
        prompt_template=prompt_template,
        system_prompt=system_prompt,
    )


def _read_string(source: dict[str, Any], key: str, default: str | None = None, allow_empty: bool = False) -> str:
    value = source.get(key, default)
    if not isinstance(value, str):
        raise ConfigError(f"Config key '{key}' must be a string.")
    if not allow_empty and not value.strip():
        raise ConfigError(f"Config key '{key}' must not be empty.")
    return value


def _read_optional_string(source: dict[str, Any], key: str) -> str | None:
    value = source.get(key)
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ConfigError(f"Config key '{key}' must be a string or null.")
    return value


def _read_string_list(source: dict[str, Any], key: str) -> list[str]:
    value = source.get(key)
    if not isinstance(value, list) or not value:
        raise ConfigError(f"Config key '{key}' must be a non-empty list of strings.")

    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(f"Config key '{key}' must only contain non-empty strings.")
        items.append(item)

    return items


def _read_bool(source: dict[str, Any], key: str, *, default: bool) -> bool:
    value = source.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"Config key '{key}' must be a boolean.")
    return value


def _read_int(source: dict[str, Any], key: str, *, minimum: int, default: int) -> int:
    value = source.get(key, default)
    if not isinstance(value, int):
        raise ConfigError(f"Config key '{key}' must be an integer.")
    if value < minimum:
        raise ConfigError(f"Config key '{key}' must be >= {minimum}.")
    return value


def _read_optional_int(source: dict[str, Any], key: str, *, minimum: int) -> int | None:
    value = source.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        raise ConfigError(f"Config key '{key}' must be an integer or null.")
    if value < minimum:
        raise ConfigError(f"Config key '{key}' must be >= {minimum}.")
    return value


def _read_float(
    source: dict[str, Any],
    key: str,
    *,
    minimum: float,
    default: float,
) -> float:
    value = source.get(key, default)
    if not isinstance(value, (int, float)):
        raise ConfigError(f"Config key '{key}' must be a number.")
    number = float(value)
    if number < minimum:
        raise ConfigError(f"Config key '{key}' must be >= {minimum}.")
    return number


def _read_optional_float(
    source: dict[str, Any],
    key: str,
    *,
    minimum: float,
    maximum: float,
) -> float | None:
    value = source.get(key)
    if value is None:
        return None
    if not isinstance(value, (int, float)):
        raise ConfigError(f"Config key '{key}' must be a number or null.")
    number = float(value)
    if number < minimum or number > maximum:
        raise ConfigError(f"Config key '{key}' must be between {minimum} and {maximum}.")
    return number


def _read_optional_choice(source: dict[str, Any], key: str, *, allowed: set[str]) -> str | None:
    value = source.get(key)
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ConfigError(f"Config key '{key}' must be a string or null.")
    if value not in allowed:
        options = ", ".join(sorted(allowed))
        raise ConfigError(f"Config key '{key}' must be one of: {options}.")
    return value


def _read_legacy_compatible_string(
    source: dict[str, Any],
    key: str,
    *,
    aliases: tuple[str, ...] = (),
    default: str | None = None,
    allow_empty: bool = False,
) -> str:
    """Read a string config value while tolerating older key spellings.

    Older add-on versions used slightly different key names in persisted config.
    We keep the parser lenient here so saved presets/workflows do not block the UI
    from opening after schema refactors.
    """
    if key in source:
        return _read_string(source, key, default=default, allow_empty=allow_empty)
    for alias in aliases:
        if alias in source:
            return _read_string(source, alias, default=default, allow_empty=allow_empty)
    return _read_string(source, key, default=default, allow_empty=allow_empty)


def _read_optional_string_map(source: dict[str, Any], key: str) -> dict[str, str] | None:
    value = source.get(key)
    if value in (None, {}):
        return None
    if not isinstance(value, dict):
        raise ConfigError(f"Config key '{key}' must be an object.")
    parsed: dict[str, str] = {}
    for item_key, item_value in value.items():
        if not isinstance(item_key, str) or not item_key.strip():
            raise ConfigError(f"Config key '{key}' must only use non-empty string keys.")
        if not isinstance(item_value, str):
            raise ConfigError(f"Config key '{key}' must only contain string values.")
        parsed[item_key] = item_value
    return parsed


def _read_optional_string_list_map(source: dict[str, Any], key: str) -> dict[str, list[str]] | None:
    value = source.get(key)
    if value in (None, {}):
        return None
    if not isinstance(value, dict):
        raise ConfigError(f"Config key '{key}' must be an object.")
    parsed: dict[str, list[str]] = {}
    for item_key, item_value in value.items():
        if not isinstance(item_key, str) or not item_key.strip():
            raise ConfigError(f"Config key '{key}' must only use non-empty string keys.")
        parsed[item_key] = _read_optional_string_list(item_value, f"{key}.{item_key}")
    return parsed


def _read_saved_prompts(raw_config: dict[str, Any], *, fallback_prompt_template: str) -> list[SavedPrompt]:
    file_prompts, file_order = _load_prompt_files()
    config_scope = _prompt_config_scope(raw_config)
    legacy_entries = _read_legacy_saved_prompts(config_scope.get("saved_prompts", []))
    if legacy_entries:
        imported = _import_legacy_prompts_to_files(file_prompts, legacy_entries)
        if imported:
            file_prompts, file_order = _load_prompt_files()
        config_scope["saved_prompts"] = []
        save_raw_config(raw_config)

    if not file_prompts:
        return [
            SavedPrompt(
                prompt_id="default-prompt",
                name="Default prompt",
                prompt_text=fallback_prompt_template,
            )
        ]

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
        prompt = file_prompts[prompt_id]
        prompts.append(prompt)
        seen_ids.add(prompt_id)
    return prompts


def _read_workflow_groups(raw_config: dict[str, Any]) -> list[WorkflowGroup]:
    config_scope = _prompt_config_scope(raw_config)
    file_groups, file_order = load_automation_files(
        DEFAULT_GROUPS_DIR,
        USER_GROUPS_DIR,
        parser=_parse_workflow_group_entry,
        item_id_getter=lambda group: group.group_id,
    )
    legacy_groups = _read_legacy_workflow_groups(config_scope.get("workflow_groups", []))
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
                parser=_parse_workflow_group_entry,
                item_id_getter=lambda group: group.group_id,
            )
        config_scope["workflow_groups"] = []
        save_raw_config(raw_config)
    return ordered_automation_values(
        file_groups,
        config_scope.get(WORKFLOW_GROUP_ORDER_KEY),
        file_order,
    )


def _read_saved_system_prompts(value: Any, *, fallback_system_prompt: str) -> list[SavedSystemPrompt]:
    if value in (None, []):
        return [
            SavedSystemPrompt(
                prompt_id="default-system-prompt",
                name="Default system prompt",
                prompt_text=fallback_system_prompt,
            )
        ]

    if not isinstance(value, list):
        raise ConfigError("Config key 'saved_system_prompts' must be a list.")

    prompts: list[SavedSystemPrompt] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ConfigError(f"saved_system_prompts[{index}] must be an object.")

        prompt_id = _read_string(item, "id", default=f"system-prompt-{index + 1}")
        if prompt_id in seen_ids:
            raise ConfigError(f"saved_system_prompts[{index}] uses duplicate id '{prompt_id}'.")
        seen_ids.add(prompt_id)
        prompts.append(
            SavedSystemPrompt(
                prompt_id=prompt_id,
                name=_read_string(item, "name"),
                prompt_text=_read_string(item, "prompt"),
            )
        )

    return prompts


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

        preset_id = _read_string(item, "id", default=f"processing-preset-{index + 1}")
        if preset_id in seen_ids:
            raise ConfigError(
                f"saved_processing_presets[{index}] uses duplicate id '{preset_id}'."
            )
        seen_ids.add(preset_id)

        prompt_id = _read_string(item, "prompt_id")
        resolved_prompt_id = _resolved_prompt_id(
            prompt_id,
            allowed_prompt_ids=allowed_prompt_ids,
        )
        if resolved_prompt_id is None:
            raise ConfigError(
                f"saved_processing_presets[{index}] references unknown prompt_id '{prompt_id}'."
            )

        system_prompt_id = _resolved_system_prompt_id(
            _read_optional_string(item, "system_prompt_id"),
            allowed_system_prompt_ids=allowed_system_prompt_ids,
        )

        mode = _read_string(item, "mode", default="overwrite")
        if mode not in allowed_modes:
            raise ConfigError(
                "Processing preset mode must be 'append', 'overwrite', or 'skip_nonempty'."
            )

        multiple_target_fields = _read_bool(item, "multiple_target_fields", default=False)
        response_delimiter = _read_optional_string(item, "response_delimiter")
        if multiple_target_fields and not response_delimiter:
            raise ConfigError(
                f"saved_processing_presets[{index}] enables multiple_target_fields but has no response_delimiter."
            )

        presets.append(
            ProcessingPreset(
                preset_id=preset_id,
                name=_read_string(item, "name"),
                prompt_id=resolved_prompt_id,
                description=_read_optional_string(item, "description"),
                model=_read_optional_string(item, "model"),
                temperature=_read_optional_float(
                    item,
                    "temperature",
                    minimum=0.0,
                    maximum=2.0,
                ),
                system_prompt_id=system_prompt_id,
                target_field=_read_legacy_compatible_string(
                    item,
                    "target_field",
                    aliases=("targetfield", "targetField"),
                    default="",
                    allow_empty=multiple_target_fields,
                ),
                mode=mode,
                multiple_target_fields=multiple_target_fields,
                convert_markdown_to_html=_read_bool(item, "convert_markdown_to_html", default=True),
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
    config_scope = _prompt_config_scope(raw_config)
    allowed_prompt_ids = {prompt.prompt_id for prompt in saved_prompts}
    allowed_system_prompt_ids = {
        prompt.prompt_id for prompt in (saved_system_prompts or [])
    }
    allowed_group_ids = {group.group_id for group in workflow_groups}
    allowed_modes = {"append", "overwrite", "skip_nonempty"}
    allowed_workflow_types = {"field_update", "audit"}
    allowed_api_modes = {"global_default", "responses", "chat_completions"}
    parser = lambda item, index: _parse_workflow_entry(
        item,
        index=index,
        allowed_prompt_ids=allowed_prompt_ids,
        allowed_system_prompt_ids=allowed_system_prompt_ids,
        allowed_group_ids=allowed_group_ids,
        allowed_modes=allowed_modes,
        allowed_workflow_types=allowed_workflow_types,
        allowed_api_modes=allowed_api_modes,
    )
    file_workflows, file_order = load_automation_files(
        DEFAULT_WORKFLOWS_DIR,
        USER_WORKFLOWS_DIR,
        parser=parser,
        item_id_getter=lambda workflow: workflow.workflow_id,
    )
    legacy_workflows = _read_legacy_workflow_entries(config_scope.get("workflows", []))
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
    return ordered_automation_values(
        file_workflows,
        config_scope.get(WORKFLOW_ORDER_KEY),
        file_order,
    )


def _parse_workflow_entry(
    item: dict[str, Any],
    *,
    index: int,
    allowed_prompt_ids: set[str],
    allowed_system_prompt_ids: set[str],
    allowed_group_ids: set[str],
    allowed_modes: set[str],
    allowed_workflow_types: set[str],
    allowed_api_modes: set[str],
) -> Workflow:
    workflow_id = _read_string(item, "id", default=f"workflow-{index + 1}")

    prompt_id = _read_string(item, "prompt_id")
    resolved_prompt_id = _resolved_prompt_id(
        prompt_id,
        allowed_prompt_ids=allowed_prompt_ids,
    )
    if resolved_prompt_id is None:
        raise ConfigError(
            f"workflows[{index}] references unknown prompt_id '{prompt_id}'."
        )

    workflow_type = _read_string(item, "workflow_type", default="field_update")
    if workflow_type not in allowed_workflow_types:
        raise ConfigError(
            "Workflow type must be 'field_update' or 'audit'."
        )

    mode = _read_string(item, "mode", default="overwrite")
    if mode not in allowed_modes:
        raise ConfigError(
            "Workflow mode must be 'append', 'overwrite', or 'skip_nonempty'."
        )

    group_id = _read_workflow_group_id(item, allowed_group_ids=allowed_group_ids, index=index)
    model = _read_optional_string(item, "model")
    api_mode = _read_optional_choice(
        item,
        "api_mode",
        allowed=allowed_api_modes,
    ) or "global_default"
    temperature = _read_optional_float(
        item,
        "temperature",
        minimum=0.0,
        maximum=2.0,
    )
    system_prompt_id = _resolved_system_prompt_id(
        _read_optional_string(item, "system_prompt_id"),
        allowed_system_prompt_ids=allowed_system_prompt_ids,
        workflow_type=workflow_type,
    )
    multiple_target_fields = _read_bool(item, "multiple_target_fields", default=False)
    response_delimiter = _read_optional_string(item, "response_delimiter")
    if multiple_target_fields and not response_delimiter:
        raise ConfigError(
            f"workflows[{index}] enables multiple_target_fields but has no response_delimiter."
        )
    trigger_on_startup = _read_bool(item, "trigger_on_startup", default=False)
    trigger_on_periodic = _read_bool(item, "trigger_on_periodic", default=False)
    trigger_min_matches = _read_int(item, "trigger_min_matches", minimum=1, default=1)

    allow_empty_target_field = multiple_target_fields or workflow_type == "audit"
    target_field = _read_legacy_compatible_string(
        item,
        "target_field",
        aliases=("targetfield", "targetField"),
        default="",
        allow_empty=allow_empty_target_field,
    )
    schema_preset = _read_optional_string(item, "schema_preset")
    response_schema_json = _read_optional_string(item, "response_schema_json")
    if workflow_type == "audit" and schema_preset is None and response_schema_json is None:
        schema_preset = "mlr_audit"

    return Workflow(
        workflow_id=workflow_id,
        name=_read_string(item, "name"),
        query=_read_string(item, "query", allow_empty=True),
        prompt_id=resolved_prompt_id,
        workflow_type=workflow_type,
        enabled=_read_bool(item, "enabled", default=True),
        target_field=target_field,
        mode=mode,
        model=model,
        temperature=temperature,
        api_mode=api_mode,
        system_prompt_id=system_prompt_id,
        multiple_target_fields=multiple_target_fields,
        convert_markdown_to_html=_read_bool(item, "convert_markdown_to_html", default=True),
        response_delimiter=response_delimiter,
        schema_preset=schema_preset,
        response_schema_json=response_schema_json,
        note_type_filter=_read_optional_string(item, "note_type_filter"),
        clear_status_tags=_read_optional_string_list(item.get("clear_status_tags"), f"workflows[{index}].clear_status_tags") or None,
        status_tag_map=_read_optional_string_map(item, "status_tag_map"),
        extra_status_tags=_read_optional_string_list_map(item, "extra_status_tags"),
        success_tags=_read_optional_string_list(item.get("success_tags"), f"workflows[{index}].success_tags") or None,
        failure_tags=_read_optional_string_list(item.get("failure_tags"), f"workflows[{index}].failure_tags") or None,
        metadata_field_map=_read_optional_string_map(item, "metadata_field_map"),
        store_raw_output=_read_bool(item, "store_raw_output", default=True),
        trigger_on_startup=trigger_on_startup,
        trigger_on_periodic=trigger_on_periodic,
        trigger_min_matches=trigger_min_matches,
        group_id=group_id,
        position=_read_int(item, "position", minimum=0, default=index),
    )


def _read_workflow_group_id(
    item: dict[str, Any],
    *,
    allowed_group_ids: set[str],
    index: int,
) -> str | None:
    raw_group_ids = item.get("group_ids")
    if raw_group_ids in (None, []):
        legacy_group_id = _read_optional_string(item, "group_id")
        if legacy_group_id is None:
            return None
        if legacy_group_id not in allowed_group_ids:
            return None
        return legacy_group_id

    if not isinstance(raw_group_ids, list):
        raise ConfigError(f"workflows[{index}].group_ids must be a list.")

    for group_id in raw_group_ids:
        if not isinstance(group_id, str) or not group_id.strip():
            raise ConfigError(f"workflows[{index}].group_ids must only contain non-empty strings.")
        if group_id not in allowed_group_ids:
            continue
        return group_id
    return None


def _read_pipelines(
    raw_config: dict[str, Any],
    *,
    workflows: list[Workflow],
    workflow_groups: list[WorkflowGroup],
) -> list[Pipeline]:
    config_scope = _prompt_config_scope(raw_config)
    allowed_workflow_ids = {workflow.workflow_id for workflow in workflows}
    allowed_group_ids = {group.group_id for group in workflow_groups}
    parser = lambda item, index: _parse_pipeline_entry(
        item,
        index=index,
        allowed_workflow_ids=allowed_workflow_ids,
        allowed_group_ids=allowed_group_ids,
    )
    file_pipelines, file_order = load_automation_files(
        DEFAULT_PIPELINES_DIR,
        USER_PIPELINES_DIR,
        parser=parser,
        item_id_getter=lambda pipeline: pipeline.pipeline_id,
    )
    legacy_pipelines = _read_legacy_pipeline_entries(config_scope.get("pipelines", []))
    if legacy_pipelines:
        if import_legacy_automation_to_files(
            USER_PIPELINES_DIR,
            legacy_pipelines,
            item_id_getter=lambda pipeline: str(pipeline.get("id", "")),
            item_to_dict=_automation_item_to_dict,
            default_dir=DEFAULT_PIPELINES_DIR,
        ):
            file_pipelines, file_order = load_automation_files(
                DEFAULT_PIPELINES_DIR,
                USER_PIPELINES_DIR,
                parser=parser,
                item_id_getter=lambda pipeline: pipeline.pipeline_id,
            )
        config_scope["pipelines"] = []
        save_raw_config(raw_config)
    return ordered_automation_values(
        file_pipelines,
        config_scope.get(PIPELINE_ORDER_KEY),
        file_order,
    )


def _parse_pipeline_entry(
    item: dict[str, Any],
    *,
    index: int,
    allowed_workflow_ids: set[str],
    allowed_group_ids: set[str],
) -> Pipeline:
    allowed_step_types = {"run_workflow", "run_group", "tag", "stop", "suspend_cards", "run_mlr_audit"}
    pipeline_id = _read_string(item, "id", default=f"pipeline-{index + 1}")

    selector_raw = item.get("note_selector")
    if not isinstance(selector_raw, dict):
        raise ConfigError(f"pipelines[{index}].note_selector must be an object.")
    note_selector = PipelineNoteSelector(
        query=_read_string(selector_raw, "query"),
        limit=_read_optional_int(selector_raw, "limit", minimum=1),
    )

    steps_raw = item.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        raise ConfigError(f"pipelines[{index}].steps must be a non-empty list.")

    steps: list[PipelineStep] = []
    seen_step_ids: set[str] = set()
    for step_index, step_raw in enumerate(steps_raw):
        if not isinstance(step_raw, dict):
            raise ConfigError(f"pipelines[{index}].steps[{step_index}] must be an object.")

        step_id = _read_string(step_raw, "id", default=f"{pipeline_id}-step-{step_index + 1}")
        if step_id in seen_step_ids:
            raise ConfigError(
                f"pipelines[{index}].steps[{step_index}] uses duplicate id '{step_id}'."
            )
        seen_step_ids.add(step_id)

        step_type = _read_string(step_raw, "type")
        if step_type not in allowed_step_types:
            raise ConfigError(
                f"pipelines[{index}].steps[{step_index}].type must be one of: "
                + ", ".join(sorted(allowed_step_types))
                + "."
            )

        workflow_id = _read_optional_string(step_raw, "workflow_id")
        group_id = _read_optional_string(step_raw, "group_id")
        if step_type == "run_mlr_audit" and workflow_id is None:
            workflow_id = "mlr-audit"
            step_type = "run_workflow"

        # If users delete workflows or groups later, keep loading the pipeline
        # and just drop the stale orchestration step instead of failing startup.
        if workflow_id is not None and workflow_id not in allowed_workflow_ids:
            continue
        if group_id is not None and group_id not in allowed_group_ids:
            continue

        if step_type == "run_workflow" and workflow_id is None:
            raise ConfigError(
                f"pipelines[{index}].steps[{step_index}] must define workflow_id for run_workflow."
            )
        if step_type == "run_group" and group_id is None:
            raise ConfigError(
                f"pipelines[{index}].steps[{step_index}] must define group_id for run_group."
            )
        if step_type != "run_workflow" and workflow_id is not None:
            raise ConfigError(
                f"pipelines[{index}].steps[{step_index}] may only define workflow_id for run_workflow."
            )
        if step_type != "run_group" and group_id is not None:
            raise ConfigError(
                f"pipelines[{index}].steps[{step_index}] may only define group_id for run_group."
            )

        add_tags = _read_optional_string_list(step_raw.get("add_tags"), f"pipelines[{index}].steps[{step_index}].add_tags")
        remove_tags = _read_optional_string_list(
            step_raw.get("remove_tags"),
            f"pipelines[{index}].steps[{step_index}].remove_tags",
        )
        if step_type == "tag" and not add_tags and not remove_tags:
            raise ConfigError(
                f"pipelines[{index}].steps[{step_index}] must define add_tags and/or remove_tags for tag steps."
            )
        if step_type != "tag" and (add_tags or remove_tags):
            raise ConfigError(
                f"pipelines[{index}].steps[{step_index}] may only define add_tags/remove_tags for tag steps."
            )

        when_value = step_raw.get("when")
        if when_value is not None and not isinstance(when_value, dict):
            raise ConfigError(f"pipelines[{index}].steps[{step_index}].when must be an object.")

        steps.append(
            PipelineStep(
                step_id=step_id,
                step_type=step_type,
                workflow_id=workflow_id,
                group_id=group_id,
                add_tags=add_tags or None,
                remove_tags=remove_tags or None,
                when=when_value,
            )
        )

    if not steps:
        raise ConfigError(
            f"pipelines[{index}] has no runnable steps after removing references to missing workflows/groups."
        )

    return Pipeline(
        pipeline_id=pipeline_id,
        name=_read_string(item, "name"),
        enabled=_read_bool(item, "enabled", default=True),
        note_selector=note_selector,
        steps=steps,
    )


def _read_model_pricing(value: Any) -> dict[str, ModelPricing]:
    if value in (None, {}):
        return {}
    if not isinstance(value, dict):
        raise ConfigError("Config key 'model_pricing' must be an object.")

    parsed: dict[str, ModelPricing] = {}
    for model_name, pricing in value.items():
        if not isinstance(model_name, str) or not model_name.strip():
            raise ConfigError("Config key 'model_pricing' must use non-empty string model names.")
        if not isinstance(pricing, dict):
            raise ConfigError(f"Config key 'model_pricing.{model_name}' must be an object.")

        input_per_million_usd = _read_float(pricing, "input_per_million_usd", minimum=0.0, default=0.0)
        output_per_million_usd = _read_float(pricing, "output_per_million_usd", minimum=0.0, default=0.0)
        cached_input_per_million_usd = _read_optional_float(
            pricing,
            "cached_input_per_million_usd",
            minimum=0.0,
            maximum=1_000_000.0,
        )
        parsed[model_name] = ModelPricing(
            input_per_million_usd=input_per_million_usd,
            cached_input_per_million_usd=cached_input_per_million_usd,
            output_per_million_usd=output_per_million_usd,
        )

    return parsed


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

    mw.addonManager.writeConfig(ADDON_NAME, raw_config)


def save_saved_prompts(raw_config: dict[str, Any], prompts: list[Any]) -> None:
    config_scope = _prompt_config_scope(raw_config)
    ordered_ids: list[str] = []
    seen_ids: set[str] = set()
    for prompt in prompts:
        prompt_id = str(getattr(prompt, "prompt_id", "")).strip()
        name = str(getattr(prompt, "name", "")).strip()
        prompt_text = str(getattr(prompt, "prompt_text", "")).strip()
        if not prompt_id or not name or not prompt_text:
            continue
        write_prompt_markdown(_target_prompt_path(prompt_id), name, prompt_text)
        if prompt_id not in seen_ids:
            ordered_ids.append(prompt_id)
            seen_ids.add(prompt_id)

    _prune_removed_user_prompt_files(seen_ids)
    config_scope["saved_prompts"] = []
    config_scope[SAVED_PROMPT_ORDER_KEY] = ordered_ids
    save_raw_config(raw_config)


def save_workflow_state(
    raw_config: dict[str, Any],
    workflow_groups: list[WorkflowGroup],
    workflows: list[Workflow],
) -> None:
    config_scope = _prompt_config_scope(raw_config)
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


def new_object_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _read_optional_string_list(value: Any, key: str) -> list[str]:
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise ConfigError(f"Config key '{key}' must be a list of strings.")

    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ConfigError(f"Config key '{key}' must only contain strings.")
        stripped = item.strip()
        if stripped:
            items.append(stripped)
    return items


def _read_legacy_saved_prompts(value: Any) -> list[SavedPrompt]:
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise ConfigError("Config key 'saved_prompts' must be a list.")

    prompts: list[SavedPrompt] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ConfigError(f"saved_prompts[{index}] must be an object.")
        prompt_id = _read_string(item, "id", default=f"prompt-{index + 1}")
        if prompt_id in seen_ids:
            raise ConfigError(f"saved_prompts[{index}] uses duplicate id '{prompt_id}'.")
        seen_ids.add(prompt_id)
        prompts.append(
            SavedPrompt(
                prompt_id=prompt_id,
                name=_read_string(item, "name"),
                prompt_text=_read_string(item, "prompt"),
            )
        )
    return prompts


def _load_prompt_files() -> tuple[dict[str, SavedPrompt], list[str]]:
    merged: dict[str, SavedPrompt] = {}
    order: list[str] = []
    for directory in (DEFAULT_PROMPTS_DIR, USER_PROMPTS_DIR):
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*.md")):
            prompt_id = path.relative_to(directory).with_suffix("").as_posix()
            name, prompt_text = read_prompt_markdown(path)
            merged[prompt_id] = SavedPrompt(
                prompt_id=prompt_id,
                name=name,
                prompt_text=prompt_text,
            )
            if prompt_id in order:
                order.remove(prompt_id)
            order.append(prompt_id)
    return merged, order


def _import_legacy_prompts_to_files(
    file_prompts: dict[str, SavedPrompt],
    legacy_prompts: list[SavedPrompt],
) -> bool:
    imported = False
    for prompt in legacy_prompts:
        current = file_prompts.get(prompt.prompt_id)
        if current is not None and current.name == prompt.name and current.prompt_text == prompt.prompt_text:
            continue
        write_prompt_markdown(_prompt_path_for_id(USER_PROMPTS_DIR, prompt.prompt_id), prompt.name, prompt.prompt_text)
        imported = True
    return imported


def _target_prompt_path(prompt_id: str) -> Path:
    default_path = _prompt_path_for_id(DEFAULT_PROMPTS_DIR, prompt_id)
    if default_path.exists():
        return default_path
    return _prompt_path_for_id(USER_PROMPTS_DIR, prompt_id)


def _prune_removed_user_prompt_files(active_prompt_ids: set[str]) -> None:
    if not USER_PROMPTS_DIR.exists():
        return
    for path in USER_PROMPTS_DIR.rglob("*.md"):
        prompt_id = path.relative_to(USER_PROMPTS_DIR).with_suffix("").as_posix()
        if prompt_id not in active_prompt_ids:
            path.unlink()
    for directory in sorted(USER_PROMPTS_DIR.rglob("*"), reverse=True):
        if directory.is_dir():
            try:
                directory.rmdir()
            except OSError:
                pass


def _prompt_path_for_id(root: Path, prompt_id: str) -> Path:
    cleaned_id = prompt_id.strip().replace("\\", "/")
    if not cleaned_id:
        return root / "prompt.md"
    parts = [part for part in cleaned_id.split("/") if part and part not in {".", ".."}]
    return root.joinpath(*parts).with_suffix(".md")


def _prompt_config_scope(raw_config: dict[str, Any]) -> dict[str, Any]:
    nested = raw_config.get("config")
    if isinstance(nested, dict):
        return nested
    return raw_config


def _parse_workflow_group_entry(item: dict[str, Any], *, index: int) -> WorkflowGroup:
    return WorkflowGroup(
        group_id=_read_string(item, "id", default=f"group-{index + 1}"),
        name=_read_string(item, "name"),
    )


def _read_legacy_workflow_groups(value: Any) -> list[WorkflowGroup]:
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise ConfigError("Config key 'workflow_groups' must be a list.")
    groups: list[WorkflowGroup] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ConfigError(f"workflow_groups[{index}] must be an object.")
        group = _parse_workflow_group_entry(item, index=index)
        if group.group_id in seen_ids:
            raise ConfigError(f"workflow_groups[{index}] uses duplicate id '{group.group_id}'.")
        seen_ids.add(group.group_id)
        groups.append(group)
    return groups


def _read_legacy_workflow_entries(value: Any) -> list[dict[str, Any]]:
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise ConfigError("Config key 'workflows' must be a list.")
    entries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ConfigError(f"workflows[{index}] must be an object.")
        workflow_id = _read_string(item, "id", default=f"workflow-{index + 1}")
        if workflow_id in seen_ids:
            raise ConfigError(f"workflows[{index}] uses duplicate id '{workflow_id}'.")
        seen_ids.add(workflow_id)
        entries.append(dict(item))
    return entries


def _read_legacy_pipeline_entries(value: Any) -> list[dict[str, Any]]:
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise ConfigError("Config key 'pipelines' must be a list.")
    entries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ConfigError(f"pipelines[{index}] must be an object.")
        pipeline_id = _read_string(item, "id", default=f"pipeline-{index + 1}")
        if pipeline_id in seen_ids:
            raise ConfigError(f"pipelines[{index}] uses duplicate id '{pipeline_id}'.")
        seen_ids.add(pipeline_id)
        entries.append(dict(item))
    return entries


def _automation_item_id(item: Any) -> str:
    if isinstance(item, WorkflowGroup):
        return item.group_id
    if isinstance(item, Workflow):
        return item.workflow_id
    if isinstance(item, Pipeline):
        return item.pipeline_id
    raise TypeError(f"Unsupported automation item type: {type(item)!r}")


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
            "prompt_id": item.prompt_id,
            "target_field": item.target_field,
            "mode": item.mode,
            "model": item.model,
            "temperature": item.temperature,
            "api_mode": item.api_mode,
            "system_prompt_id": item.system_prompt_id,
            "multiple_target_fields": item.multiple_target_fields,
            "convert_markdown_to_html": item.convert_markdown_to_html,
            "response_delimiter": item.response_delimiter,
            "schema_preset": item.schema_preset,
            "response_schema_json": item.response_schema_json,
            "note_type_filter": item.note_type_filter,
            "clear_status_tags": item.clear_status_tags,
            "status_tag_map": item.status_tag_map,
            "extra_status_tags": item.extra_status_tags,
            "success_tags": item.success_tags,
            "failure_tags": item.failure_tags,
            "metadata_field_map": item.metadata_field_map,
            "store_raw_output": item.store_raw_output,
            "trigger_on_startup": item.trigger_on_startup,
            "trigger_on_periodic": item.trigger_on_periodic,
            "trigger_min_matches": item.trigger_min_matches,
            "group_ids": [item.group_id] if item.group_id else [],
            "group_id": item.group_id,
            "position": item.position,
        }
    if isinstance(item, Pipeline):
        return {
            "id": item.pipeline_id,
            "name": item.name,
            "enabled": item.enabled,
            "note_selector": {
                "query": item.note_selector.query,
                "limit": item.note_selector.limit,
            },
            "steps": [
                {
                    "id": step.step_id,
                    "type": step.step_type,
                    "workflow_id": step.workflow_id,
                    "group_id": step.group_id,
                    "add_tags": step.add_tags,
                    "remove_tags": step.remove_tags,
                    "when": step.when,
                }
                for step in item.steps
            ],
        }
    if isinstance(item, dict):
        return item
    raise TypeError(f"Unsupported automation item type: {type(item)!r}")
