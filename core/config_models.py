from __future__ import annotations

from dataclasses import dataclass
import uuid

from ..services.pricing import ModelPricing


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
    invalid_reason: str | None = None
    description: str | None = None
    model: str | None = None
    temperature: float | None = None
    system_prompt_id: str | None = None
    target_field: str = ""
    mode: str = "overwrite"
    multiple_target_fields: bool = False
    convert_markdown_to_html: bool = True
    convert_field_html_to_markdown: bool = False
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
    prompt_id: str = ""
    invalid_reason: str | None = None
    workflow_type: str = "field_update"
    enabled: bool = True
    script_command: str | None = None
    target_field: str = ""
    mode: str = "overwrite"
    model: str | None = None
    temperature: float | None = None
    api_mode: str | None = None
    system_prompt_id: str | None = None
    multiple_target_fields: bool = False
    convert_markdown_to_html: bool = True
    convert_field_html_to_markdown: bool = False
    response_delimiter: str | None = None
    success_tags: list[str] | None = None
    failure_tags: list[str] | None = None
    trigger_on_startup: bool = False
    trigger_on_periodic: bool = False
    trigger_min_matches: int = 1
    group_id: str | None = None
    position: int = 0


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


def new_object_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"
