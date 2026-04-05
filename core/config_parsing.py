from __future__ import annotations

from typing import Any

from ..services.pricing import ModelPricing
from .config_models import (
    ConfigError,
    FieldMapping,
    ProcessingPreset,
    SavedPrompt,
    SavedSystemPrompt,
    Workflow,
    WorkflowGroup,
)


DEFAULT_SYSTEM_PROMPT_ID = "default-system-prompt"
LEGACY_DEFAULT_PROMPT_ID_ALIASES = {
    "default-prompt": "general/default-prompt",
    "card-quality-check": "review/card-quality-check",
    "full-card-optimization": "review/full-card-optimization",
    "update-grammar-notes": "field-updates/update-grammar-notes",
    "update-japanese-notes": "field-updates/update-japanese-notes",
    "mlr-card-quality-check": "mlr/review/mlr-card-quality-check",
    "mlr-cloze-optimization": "mlr/transform/mlr-cloze-optimization",
    "mlr-fix-only-whats-wrong": "mlr/transform/mlr-fix-only-whats-wrong",
    "mlr-full-field-refactor": "mlr/transform/mlr-full-field-refactor",
    "mlr-grammar-field-improver": "mlr/field-updates/mlr-grammar-field-improver",
    "mlr-grammar-notes-generator": "mlr/field-updates/mlr-grammar-notes-generator",
    "mlr-japanese-notes-improver": "mlr/field-updates/mlr-japanese-notes-improver",
    "mlr-word-definition-optimizer": "mlr/field-updates/mlr-word-definition-optimizer",
}


def resolved_system_prompt_id(
    system_prompt_id: str | None,
    *,
    allowed_system_prompt_ids: set[str],
    workflow_type: str | None = None,
) -> str | None:
    if system_prompt_id is None:
        return (
            DEFAULT_SYSTEM_PROMPT_ID
            if DEFAULT_SYSTEM_PROMPT_ID in allowed_system_prompt_ids
            else None
        )
    if system_prompt_id in allowed_system_prompt_ids:
        return system_prompt_id
    return (
        DEFAULT_SYSTEM_PROMPT_ID
        if DEFAULT_SYSTEM_PROMPT_ID in allowed_system_prompt_ids
        else None
    )


def resolved_prompt_id(
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


def parse_field_mapping(value: Any, *, index: int) -> FieldMapping:
    if not isinstance(value, dict):
        raise ConfigError(f"field_mappings[{index}] must be an object.")

    note_type = read_string(value, "note_type", default="*")
    output_fields = read_string_list(value, "output_fields")
    prompt_template = read_optional_string(value, "prompt_template")
    system_prompt = read_optional_string(value, "system_prompt")

    return FieldMapping(
        note_type=note_type,
        output_fields=output_fields,
        prompt_template=prompt_template,
        system_prompt=system_prompt,
    )


def read_string(source: dict[str, Any], key: str, default: str | None = None, allow_empty: bool = False) -> str:
    value = source.get(key, default)
    if not isinstance(value, str):
        raise ConfigError(f"Config key '{key}' must be a string.")
    if not allow_empty and not value.strip():
        raise ConfigError(f"Config key '{key}' must not be empty.")
    return value


def read_optional_string(source: dict[str, Any], key: str) -> str | None:
    value = source.get(key)
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ConfigError(f"Config key '{key}' must be a string or null.")
    return value


def read_string_list(source: dict[str, Any], key: str) -> list[str]:
    value = source.get(key)
    if not isinstance(value, list) or not value:
        raise ConfigError(f"Config key '{key}' must be a non-empty list of strings.")

    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(f"Config key '{key}' must only contain non-empty strings.")
        items.append(item)

    return items


def read_bool(source: dict[str, Any], key: str, *, default: bool) -> bool:
    value = source.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"Config key '{key}' must be a boolean.")
    return value


def read_int(source: dict[str, Any], key: str, *, minimum: int, default: int) -> int:
    value = source.get(key, default)
    if not isinstance(value, int):
        raise ConfigError(f"Config key '{key}' must be an integer.")
    if value < minimum:
        raise ConfigError(f"Config key '{key}' must be >= {minimum}.")
    return value


def read_optional_float(
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


def read_float(
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


def read_optional_choice(source: dict[str, Any], key: str, *, allowed: set[str]) -> str | None:
    value = source.get(key)
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ConfigError(f"Config key '{key}' must be a string or null.")
    if value not in allowed:
        options = ", ".join(sorted(allowed))
        raise ConfigError(f"Config key '{key}' must be one of: {options}.")
    return value


def read_legacy_compatible_string(
    source: dict[str, Any],
    key: str,
    *,
    aliases: tuple[str, ...] = (),
    default: str | None = None,
    allow_empty: bool = False,
) -> str:
    if key in source:
        return read_string(source, key, default=default, allow_empty=allow_empty)
    for alias in aliases:
        if alias in source:
            return read_string(source, alias, default=default, allow_empty=allow_empty)
    return read_string(source, key, default=default, allow_empty=allow_empty)


def read_optional_string_map(source: dict[str, Any], key: str) -> dict[str, str] | None:
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


def read_optional_string_list_map(source: dict[str, Any], key: str) -> dict[str, list[str]] | None:
    value = source.get(key)
    if value in (None, {}):
        return None
    if not isinstance(value, dict):
        raise ConfigError(f"Config key '{key}' must be an object.")
    parsed: dict[str, list[str]] = {}
    for item_key, item_value in value.items():
        if not isinstance(item_key, str) or not item_key.strip():
            raise ConfigError(f"Config key '{key}' must only use non-empty string keys.")
        parsed[item_key] = read_optional_string_list(item_value, f"{key}.{item_key}")
    return parsed


def read_optional_string_list(value: Any, key: str) -> list[str]:
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


def parse_workflow_group_entry(item: dict[str, Any], *, index: int) -> WorkflowGroup:
    return WorkflowGroup(
        group_id=read_string(item, "id", default=f"group-{index + 1}"),
        name=read_string(item, "name"),
    )


def read_workflow_group_id(
    item: dict[str, Any],
    *,
    allowed_group_ids: set[str],
    index: int,
) -> str | None:
    raw_group_ids = item.get("group_ids")
    if raw_group_ids in (None, []):
        legacy_group_id = read_optional_string(item, "group_id")
        if legacy_group_id is None or legacy_group_id not in allowed_group_ids:
            return None
        return legacy_group_id

    if not isinstance(raw_group_ids, list):
        raise ConfigError(f"workflows[{index}].group_ids must be a list.")

    for group_id in raw_group_ids:
        if not isinstance(group_id, str) or not group_id.strip():
            raise ConfigError(f"workflows[{index}].group_ids must only contain non-empty strings.")
        if group_id in allowed_group_ids:
            return group_id
    return None


def parse_workflow_entry(
    item: dict[str, Any],
    *,
    index: int,
    allowed_prompt_ids: set[str],
    allowed_system_prompt_ids: set[str],
    allowed_group_ids: set[str],
    allowed_modes: set[str],
    allowed_workflow_types: set[str],
    allowed_api_modes: set[str],
) -> Workflow | None:
    workflow_id = read_string(item, "id", default=f"workflow-{index + 1}")

    workflow_type = read_string(item, "workflow_type", default="field_update")
    if workflow_type not in allowed_workflow_types:
        raise ConfigError("Workflow type must be 'field_update' or 'script'.")
    if workflow_type == "script":
        script_command = read_string(item, "script_command")
        resolved_workflow_prompt_id = ""
        invalid_reason = None
    else:
        prompt_id = read_string(item, "prompt_id")
        resolved_workflow_prompt_id = resolved_prompt_id(
            prompt_id,
            allowed_prompt_ids=allowed_prompt_ids,
        )
        invalid_reason = None
        if resolved_workflow_prompt_id is None:
            resolved_workflow_prompt_id = prompt_id
            invalid_reason = f"Missing saved prompt: '{prompt_id}'."
        script_command = None

    mode = read_string(item, "mode", default="overwrite")
    if mode not in allowed_modes:
        raise ConfigError("Workflow mode must be 'append', 'overwrite', or 'skip_nonempty'.")

    group_id = read_workflow_group_id(item, allowed_group_ids=allowed_group_ids, index=index)
    model = read_optional_string(item, "model")
    api_mode = read_optional_choice(item, "api_mode", allowed=allowed_api_modes) or "global_default"
    temperature = read_optional_float(item, "temperature", minimum=0.0, maximum=2.0)
    system_prompt_id = resolved_system_prompt_id(
        read_optional_string(item, "system_prompt_id"),
        allowed_system_prompt_ids=allowed_system_prompt_ids,
        workflow_type=workflow_type,
    )
    multiple_target_fields = read_bool(item, "multiple_target_fields", default=False)
    response_delimiter = read_optional_string(item, "response_delimiter")
    if multiple_target_fields and not response_delimiter:
        raise ConfigError(
            f"workflows[{index}] enables multiple_target_fields but has no response_delimiter."
        )
    trigger_on_startup = read_bool(item, "trigger_on_startup", default=False)
    trigger_on_periodic = read_bool(item, "trigger_on_periodic", default=False)
    trigger_min_matches = read_int(item, "trigger_min_matches", minimum=1, default=1)

    target_field = read_legacy_compatible_string(
        item,
        "target_field",
        aliases=("targetfield", "targetField"),
        default="",
        allow_empty=multiple_target_fields or workflow_type == "script",
    )
    return Workflow(
        workflow_id=workflow_id,
        name=read_string(item, "name"),
        query=read_string(item, "query", allow_empty=True),
        prompt_id=resolved_workflow_prompt_id,
        invalid_reason=invalid_reason,
        workflow_type=workflow_type,
        enabled=read_bool(item, "enabled", default=True),
        script_command=script_command,
        target_field=target_field,
        mode=mode,
        model=model,
        temperature=temperature,
        api_mode=api_mode,
        system_prompt_id=system_prompt_id,
        multiple_target_fields=multiple_target_fields,
        convert_markdown_to_html=read_bool(item, "convert_markdown_to_html", default=True),
        convert_field_html_to_markdown=read_bool(item, "convert_field_html_to_markdown", default=False),
        response_delimiter=response_delimiter,
        success_tags=read_optional_string_list(item.get("success_tags"), f"workflows[{index}].success_tags") or None,
        failure_tags=read_optional_string_list(item.get("failure_tags"), f"workflows[{index}].failure_tags") or None,
        trigger_on_startup=trigger_on_startup,
        trigger_on_periodic=trigger_on_periodic,
        trigger_min_matches=trigger_min_matches,
        group_id=group_id,
        position=read_int(item, "position", minimum=0, default=index),
    )


def read_model_pricing(value: Any) -> dict[str, ModelPricing]:
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
        parsed[model_name] = ModelPricing(
            input_per_million_usd=read_float(pricing, "input_per_million_usd", minimum=0.0, default=0.0),
            cached_input_per_million_usd=read_optional_float(
                pricing,
                "cached_input_per_million_usd",
                minimum=0.0,
                maximum=1_000_000.0,
            ),
            output_per_million_usd=read_float(pricing, "output_per_million_usd", minimum=0.0, default=0.0),
        )
    return parsed


def read_legacy_saved_prompts(value: Any) -> list[SavedPrompt]:
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise ConfigError("Config key 'saved_prompts' must be a list.")

    prompts: list[SavedPrompt] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ConfigError(f"saved_prompts[{index}] must be an object.")
        prompt_id = read_string(item, "id", default=f"prompt-{index + 1}")
        if prompt_id in seen_ids:
            raise ConfigError(f"saved_prompts[{index}] uses duplicate id '{prompt_id}'.")
        seen_ids.add(prompt_id)
        prompts.append(
            SavedPrompt(
                prompt_id=prompt_id,
                name=read_string(item, "name"),
                prompt_text=read_string(item, "prompt"),
            )
        )
    return prompts


def read_legacy_workflow_groups(value: Any) -> list[WorkflowGroup]:
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise ConfigError("Config key 'workflow_groups' must be a list.")
    groups: list[WorkflowGroup] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ConfigError(f"workflow_groups[{index}] must be an object.")
        group = parse_workflow_group_entry(item, index=index)
        if group.group_id in seen_ids:
            raise ConfigError(f"workflow_groups[{index}] uses duplicate id '{group.group_id}'.")
        seen_ids.add(group.group_id)
        groups.append(group)
    return groups


def read_legacy_workflow_entries(value: Any) -> list[dict[str, Any]]:
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise ConfigError("Config key 'workflows' must be a list.")
    entries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ConfigError(f"workflows[{index}] must be an object.")
        workflow_id = read_string(item, "id", default=f"workflow-{index + 1}")
        if workflow_id in seen_ids:
            raise ConfigError(f"workflows[{index}] uses duplicate id '{workflow_id}'.")
        seen_ids.add(workflow_id)
        entries.append(dict(item))
    return entries
