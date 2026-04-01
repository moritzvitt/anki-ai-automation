from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

try:
    from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError
except ImportError:  # pragma: no cover - depends on Anki environment
    OpenAI = None
    APIError = Exception
    APIConnectionError = Exception
    APITimeoutError = Exception
    RateLimitError = Exception


class OpenAIClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class AIFieldUpdateResult:
    field_updates: dict[str, str]
    usage: TokenUsage


def request_field_updates(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    output_fields: list[str],
    timeout_seconds: float,
    max_retries: int,
    retry_backoff_seconds: float,
    temperature: float | None,
    reasoning_effort: str | None,
) -> AIFieldUpdateResult:
    if OpenAI is None:
        raise OpenAIClientError(
            "The official OpenAI Python client is not installed. "
            "Install the 'openai' package into Anki's Python environment first."
        )
    if not api_key.strip():
        raise OpenAIClientError("Set 'openai_api_key' in the add-on config before running AI Automation.")

    client = _build_client(api_key=api_key, timeout_seconds=timeout_seconds)
    response_format = _response_format(output_fields)

    last_error: Exception | None = None
    use_temperature = temperature is not None
    for attempt in range(max_retries + 1):
        try:
            payload: dict[str, Any] = {
                "model": model,
                "input": _request_input(system_prompt=system_prompt, user_prompt=user_prompt),
                "text": {"format": response_format},
            }
            if use_temperature and temperature is not None:
                payload["temperature"] = temperature
            if reasoning_effort:
                payload["reasoning"] = {"effort": reasoning_effort}

            response = client.responses.create(**payload)
            if not getattr(response, "output_text", ""):
                raise OpenAIClientError("The model returned an empty response.")

            parsed = json.loads(response.output_text)
            return AIFieldUpdateResult(
                field_updates=_validate_output(parsed, output_fields),
                usage=_parse_usage(getattr(response, "usage", None)),
            )
        except (RateLimitError, APIConnectionError, APITimeoutError, APIError) as error:
            if use_temperature and _is_unsupported_parameter_error(error, "temperature"):
                use_temperature = False
                last_error = error
                continue
            last_error = error
            if attempt >= max_retries:
                break
            time.sleep(retry_backoff_seconds * (attempt + 1))
        except json.JSONDecodeError as error:
            raise OpenAIClientError(f"OpenAI response was not valid JSON: {error}") from error

    raise OpenAIClientError(f"OpenAI request failed after retries: {last_error}")


def count_request_input_tokens(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    output_fields: list[str],
    timeout_seconds: float,
    reasoning_effort: str | None,
) -> int:
    if OpenAI is None:
        raise OpenAIClientError(
            "The official OpenAI Python client is not installed. "
            "Install the 'openai' package into Anki's Python environment first."
        )
    if not api_key.strip():
        raise OpenAIClientError("Set 'openai_api_key' in the add-on config before running AI Automation.")

    client = _build_client(api_key=api_key, timeout_seconds=timeout_seconds)
    try:
        payload: dict[str, Any] = {
            "model": model,
            "input": _request_input(system_prompt=system_prompt, user_prompt=user_prompt),
            "text": {"format": _response_format(output_fields)},
        }
        if reasoning_effort:
            payload["reasoning"] = {"effort": reasoning_effort}

        result = client.responses.input_tokens.count(**payload)
        return int(result.input_tokens)
    except (RateLimitError, APIConnectionError, APITimeoutError, APIError) as error:
        raise OpenAIClientError(f"Failed to count input tokens: {error}") from error


def _output_schema(output_fields: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {field_name: {"type": "string"} for field_name in output_fields},
        "required": output_fields,
    }


def _validate_output(value: Any, output_fields: list[str]) -> dict[str, str]:
    if not isinstance(value, dict):
        raise OpenAIClientError("OpenAI response must be a JSON object.")

    updates: dict[str, str] = {}
    for field_name in output_fields:
        field_value = value.get(field_name)
        if not isinstance(field_value, str):
            raise OpenAIClientError(f"OpenAI response field '{field_name}' must be a string.")
        updates[field_name] = field_value

    return updates


def _build_client(*, api_key: str, timeout_seconds: float) -> Any:
    return OpenAI(api_key=api_key, timeout=timeout_seconds)


def _request_input(*, system_prompt: str, user_prompt: str) -> list[dict[str, Any]]:
    return [
        {
            "role": "system",
            "content": [{"type": "input_text", "text": system_prompt}],
        },
        {
            "role": "user",
            "content": [{"type": "input_text", "text": user_prompt}],
        },
    ]


def _response_format(output_fields: list[str]) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": "anki_field_update",
        "strict": True,
        "schema": _output_schema(output_fields),
    }


def _parse_usage(usage: Any) -> TokenUsage:
    if usage is None:
        return TokenUsage(
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            reasoning_tokens=0,
            total_tokens=0,
        )

    input_tokens_details = getattr(usage, "input_tokens_details", None)
    output_tokens_details = getattr(usage, "output_tokens_details", None)
    return TokenUsage(
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        cached_input_tokens=int(getattr(input_tokens_details, "cached_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        reasoning_tokens=int(getattr(output_tokens_details, "reasoning_tokens", 0) or 0),
        total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
    )


def _is_unsupported_parameter_error(error: Exception, parameter_name: str) -> bool:
    message = str(error).lower()
    return (
        "unsupported parameter" in message
        and f"'{parameter_name.lower()}'" in message
    )
