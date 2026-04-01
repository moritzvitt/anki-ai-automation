from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aqt import mw

from .pricing import ModelPricing


ADDON_NAME = __name__.split(".")[0]


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class FieldMapping:
    note_type: str
    input_fields: list[str]
    output_fields: list[str]
    prompt_template: str | None = None
    system_prompt: str | None = None


@dataclass(frozen=True)
class AddonConfig:
    enabled: bool
    api_key: str
    model: str
    default_prompt_template: str
    system_prompt: str
    batch_size: int
    request_timeout_seconds: float
    max_retries: int
    retry_backoff_seconds: float
    temperature: float | None
    reasoning_effort: str | None
    show_estimate_before_sending: bool
    estimated_output_tokens_per_note: int
    usage_history_limit: int
    model_pricing: dict[str, ModelPricing]
    field_mappings: list[FieldMapping]


def load_config() -> AddonConfig:
    if mw is None:
        raise ConfigError("Anki main window is not available.")

    raw = mw.addonManager.getConfig(ADDON_NAME)
    if not isinstance(raw, dict):
        raise ConfigError("The add-on config could not be loaded.")

    enabled = bool(raw.get("enabled", True))
    api_key = _read_string(raw, "openai_api_key", allow_empty=True)
    model = _read_string(raw, "model", default="gpt-5-mini")
    default_prompt_template = _read_string(raw, "prompt_template")
    system_prompt = _read_string(raw, "system_prompt")
    batch_size = _read_int(raw, "batch_size", minimum=1, default=5)
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

    field_mappings_raw = raw.get("field_mappings", [])
    if not isinstance(field_mappings_raw, list) or not field_mappings_raw:
        raise ConfigError("Config key 'field_mappings' must be a non-empty list.")

    field_mappings = [_parse_field_mapping(item, index=index) for index, item in enumerate(field_mappings_raw)]

    return AddonConfig(
        enabled=enabled,
        api_key=api_key,
        model=model,
        default_prompt_template=default_prompt_template,
        system_prompt=system_prompt,
        batch_size=batch_size,
        request_timeout_seconds=request_timeout_seconds,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
        show_estimate_before_sending=show_estimate_before_sending,
        estimated_output_tokens_per_note=estimated_output_tokens_per_note,
        usage_history_limit=usage_history_limit,
        model_pricing=model_pricing,
        field_mappings=field_mappings,
    )


def _parse_field_mapping(value: Any, *, index: int) -> FieldMapping:
    if not isinstance(value, dict):
        raise ConfigError(f"field_mappings[{index}] must be an object.")

    note_type = _read_string(value, "note_type", default="*")
    input_fields = _read_string_list(value, "input_fields")
    output_fields = _read_string_list(value, "output_fields")
    prompt_template = _read_optional_string(value, "prompt_template")
    system_prompt = _read_optional_string(value, "system_prompt")

    return FieldMapping(
        note_type=note_type,
        input_fields=input_fields,
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
