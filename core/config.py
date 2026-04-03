from __future__ import annotations

from dataclasses import dataclass
import uuid
from typing import Any

from aqt import mw

from ..services.pricing import ModelPricing


ADDON_NAME = __name__.split(".")[0]


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
    group_ids: list[str] | None = None
    position: int = 0


@dataclass(frozen=True)
class PipelineNoteSelector:
    query: str
    limit: int | None = None


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
        raw.get("saved_prompts", []),
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
    workflow_groups = _read_workflow_groups(raw.get("workflow_groups", []))
    workflows = _read_workflows(
        raw.get("workflows", []),
        saved_prompts=saved_prompts,
        workflow_groups=workflow_groups,
        saved_system_prompts=saved_system_prompts,
    )
    pipelines = _read_pipelines(
        raw.get("pipelines", []),
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


def _read_saved_prompts(value: Any, *, fallback_prompt_template: str) -> list[SavedPrompt]:
    if value in (None, []):
        return [
            SavedPrompt(
                prompt_id="default-prompt",
                name="Default prompt",
                prompt_text=fallback_prompt_template,
            )
        ]

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


def _read_workflow_groups(value: Any) -> list[WorkflowGroup]:
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise ConfigError("Config key 'workflow_groups' must be a list.")

    groups: list[WorkflowGroup] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ConfigError(f"workflow_groups[{index}] must be an object.")

        group_id = _read_string(item, "id", default=f"group-{index + 1}")
        if group_id in seen_ids:
            raise ConfigError(f"workflow_groups[{index}] uses duplicate id '{group_id}'.")
        seen_ids.add(group_id)
        groups.append(
            WorkflowGroup(
                group_id=group_id,
                name=_read_string(item, "name"),
            )
        )
    return groups


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
        if prompt_id not in allowed_prompt_ids:
            raise ConfigError(
                f"saved_processing_presets[{index}] references unknown prompt_id '{prompt_id}'."
            )

        system_prompt_id = _read_optional_string(item, "system_prompt_id")
        if system_prompt_id is not None and system_prompt_id not in allowed_system_prompt_ids:
            raise ConfigError(
                f"saved_processing_presets[{index}] references unknown system_prompt_id '{system_prompt_id}'."
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
                prompt_id=prompt_id,
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
    value: Any,
    *,
    saved_prompts: list[SavedPrompt],
    workflow_groups: list[WorkflowGroup],
    saved_system_prompts: list[SavedSystemPrompt] | None = None,
) -> list[Workflow]:
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise ConfigError("Config key 'workflows' must be a list.")

    allowed_prompt_ids = {prompt.prompt_id for prompt in saved_prompts}
    allowed_system_prompt_ids = {
        prompt.prompt_id for prompt in (saved_system_prompts or [])
    }
    allowed_group_ids = {group.group_id for group in workflow_groups}
    allowed_modes = {"append", "overwrite", "skip_nonempty"}
    allowed_workflow_types = {"field_update", "audit"}
    allowed_api_modes = {"global_default", "responses", "chat_completions"}
    workflows: list[Workflow] = []
    seen_ids: set[str] = set()

    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ConfigError(f"workflows[{index}] must be an object.")

        workflow_id = _read_string(item, "id", default=f"workflow-{index + 1}")
        if workflow_id in seen_ids:
            raise ConfigError(f"workflows[{index}] uses duplicate id '{workflow_id}'.")
        seen_ids.add(workflow_id)

        prompt_id = _read_string(item, "prompt_id")
        if prompt_id not in allowed_prompt_ids:
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

        group_ids = _read_workflow_group_ids(item, allowed_group_ids=allowed_group_ids, index=index)
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
        system_prompt_id = _read_optional_string(item, "system_prompt_id")
        if system_prompt_id is not None and system_prompt_id not in allowed_system_prompt_ids:
            raise ConfigError(
                f"workflows[{index}] references unknown system_prompt_id '{system_prompt_id}'."
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

        workflows.append(
            Workflow(
                workflow_id=workflow_id,
                name=_read_string(item, "name"),
                query=_read_string(item, "query"),
                prompt_id=prompt_id,
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
                group_ids=group_ids,
                position=_read_int(item, "position", minimum=0, default=index),
            )
        )

    return workflows


def _read_workflow_group_ids(
    item: dict[str, Any],
    *,
    allowed_group_ids: set[str],
    index: int,
) -> list[str]:
    raw_group_ids = item.get("group_ids")
    if raw_group_ids in (None, []):
        legacy_group_id = _read_optional_string(item, "group_id")
        if legacy_group_id is None:
            return []
        if legacy_group_id not in allowed_group_ids:
            raise ConfigError(f"workflows[{index}] references unknown group_id '{legacy_group_id}'.")
        return [legacy_group_id]

    if not isinstance(raw_group_ids, list):
        raise ConfigError(f"workflows[{index}].group_ids must be a list.")

    parsed_group_ids: list[str] = []
    seen_group_ids: set[str] = set()
    for group_id in raw_group_ids:
        if not isinstance(group_id, str) or not group_id.strip():
            raise ConfigError(f"workflows[{index}].group_ids must only contain non-empty strings.")
        if group_id not in allowed_group_ids:
            raise ConfigError(f"workflows[{index}] references unknown group_id '{group_id}'.")
        if group_id not in seen_group_ids:
            parsed_group_ids.append(group_id)
            seen_group_ids.add(group_id)
    return parsed_group_ids


def _read_pipelines(
    value: Any,
    *,
    workflows: list[Workflow],
    workflow_groups: list[WorkflowGroup],
) -> list[Pipeline]:
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise ConfigError("Config key 'pipelines' must be a list.")

    allowed_workflow_ids = {workflow.workflow_id for workflow in workflows}
    allowed_group_ids = {group.group_id for group in workflow_groups}
    allowed_step_types = {"run_workflow", "run_group", "tag", "stop", "suspend_cards", "run_mlr_audit"}
    parsed_pipelines: list[Pipeline] = []
    seen_pipeline_ids: set[str] = set()

    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ConfigError(f"pipelines[{index}] must be an object.")

        pipeline_id = _read_string(item, "id", default=f"pipeline-{index + 1}")
        if pipeline_id in seen_pipeline_ids:
            raise ConfigError(f"pipelines[{index}] uses duplicate id '{pipeline_id}'.")
        seen_pipeline_ids.add(pipeline_id)

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
            if workflow_id is not None and workflow_id not in allowed_workflow_ids:
                raise ConfigError(
                    f"pipelines[{index}].steps[{step_index}] references unknown workflow_id '{workflow_id}'."
                )
            if group_id is not None and group_id not in allowed_group_ids:
                raise ConfigError(
                    f"pipelines[{index}].steps[{step_index}] references unknown group_id '{group_id}'."
                )

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

        parsed_pipelines.append(
            Pipeline(
                pipeline_id=pipeline_id,
                name=_read_string(item, "name"),
                enabled=_read_bool(item, "enabled", default=True),
                note_selector=note_selector,
                steps=steps,
            )
        )

    return parsed_pipelines


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
