from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .pricing import BUILTIN_MODEL_PRICING, ModelPricing, resolve_model_pricing


class ModelCatalogError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelOption:
    model_id: str
    label: str
    owned_by: str | None


def fetch_model_options(*, api_key: str, pricing_overrides: dict[str, ModelPricing]) -> list[ModelOption]:
    if not api_key.strip():
        raise ModelCatalogError("Enter an API key to load the current OpenAI model list.")

    request = Request(
        url="https://api.openai.com/v1/models",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8")
    except HTTPError as error:
        raise ModelCatalogError(f"Could not load models from OpenAI: {_extract_error_message(error)}") from error
    except URLError as error:
        raise ModelCatalogError(f"Could not reach OpenAI model list: {error}") from error
    except OSError as error:
        raise ModelCatalogError(f"Could not read OpenAI model list: {error}") from error

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ModelCatalogError(f"OpenAI model list response was not valid JSON: {error}") from error

    models = data.get("data", [])
    if not isinstance(models, list):
        raise ModelCatalogError("OpenAI model list response was missing the expected data array.")

    options: list[ModelOption] = []
    seen: set[str] = set()
    for item in models:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        if not _is_relevant_text_model(model_id):
            continue
        if model_id in seen:
            continue
        seen.add(model_id)
        owned_by = item.get("owned_by")
        owner_text = owned_by if isinstance(owned_by, str) else None
        options.append(
            ModelOption(
                model_id=model_id,
                label=f"{model_id} ({_cost_badge(model_id, pricing_overrides)})",
                owned_by=owner_text,
            )
        )

    options.sort(key=_model_sort_key)
    return options


def fallback_model_options(*, current_model: str, pricing_overrides: dict[str, ModelPricing]) -> list[ModelOption]:
    candidates = {
        model_id
        for model_id in BUILTIN_MODEL_PRICING.keys()
        if _is_relevant_text_model(model_id)
    }
    if current_model:
        candidates.add(current_model)
    options = [
        ModelOption(
            model_id=model_id,
            label=f"{model_id} ({_cost_badge(model_id, pricing_overrides)})",
            owned_by="fallback",
        )
        for model_id in candidates
        if model_id
    ]
    options.sort(key=_model_sort_key)
    return options


def _cost_badge(model_id: str, pricing_overrides: dict[str, ModelPricing]) -> str:
    pricing = resolve_model_pricing(model_id, pricing_overrides)
    if pricing is None:
        return "Cost unknown"

    score = max(pricing.input_per_million_usd, pricing.output_per_million_usd)
    if score <= 0.4:
        return "Very cheap"
    if score <= 2.0:
        return "Cheap"
    if score <= 10.0:
        return "Moderate"
    if score <= 40.0:
        return "Expensive"
    return "Very expensive"


def _model_sort_key(option: ModelOption) -> tuple[int, str]:
    priority = 1 if option.owned_by == "openai" else 2
    return (priority, option.model_id.lower())


def _extract_error_message(error: HTTPError) -> str:
    try:
        payload = error.read().decode("utf-8")
        data = json.loads(payload)
        if isinstance(data, dict):
            body_error = data.get("error")
            if isinstance(body_error, dict):
                message = body_error.get("message")
                if isinstance(message, str) and message.strip():
                    return message
        return payload
    except Exception:
        return str(error)


def _is_relevant_text_model(model_id: str) -> bool:
    blocked_prefixes = (
        "whisper",
        "tts",
        "dall-e",
        "gpt-image",
        "gpt-audio",
        "gpt-realtime",
        "gpt-4o-realtime",
        "omni-moderation",
        "text-embedding",
        "computer-use",
        "codex",
        "babbage",
        "davinci",
    )
    blocked_fragments = (
        "audio",
        "realtime",
        "transcribe",
        "tts",
        "embedding",
        "image",
        "search",
        "moderation",
        "vision",
        "deep-research",
        "mini-transcribe",
        "preview",
    )
    allowed_prefixes = (
        "gpt-5",
        "gpt-4.1",
        "gpt-4o",
        "o3",
        "o4-mini",
    )

    lowered = model_id.lower()
    if lowered.startswith(blocked_prefixes):
        return False
    if any(fragment in lowered for fragment in blocked_fragments):
        return False
    if lowered.startswith(allowed_prefixes):
        return True
    return False
