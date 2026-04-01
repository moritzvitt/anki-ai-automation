from __future__ import annotations

import json
import time
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
) -> dict[str, str]:
    if OpenAI is None:
        raise OpenAIClientError(
            "The official OpenAI Python client is not installed. "
            "Install the 'openai' package into Anki's Python environment first."
        )
    if not api_key.strip():
        raise OpenAIClientError("Set 'openai_api_key' in the add-on config before running AI Automation.")

    client = OpenAI(api_key=api_key, timeout=timeout_seconds)
    response_format = {
        "type": "json_schema",
        "name": "anki_field_update",
        "strict": True,
        "schema": _output_schema(output_fields),
    }

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            payload: dict[str, Any] = {
                "model": model,
                "input": [
                    {
                        "role": "system",
                        "content": [{"type": "input_text", "text": system_prompt}],
                    },
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": user_prompt}],
                    },
                ],
                "text": {"format": response_format},
            }
            if temperature is not None:
                payload["temperature"] = temperature
            if reasoning_effort:
                payload["reasoning"] = {"effort": reasoning_effort}

            response = client.responses.create(**payload)
            if not getattr(response, "output_text", ""):
                raise OpenAIClientError("The model returned an empty response.")

            parsed = json.loads(response.output_text)
            return _validate_output(parsed, output_fields)
        except (RateLimitError, APIConnectionError, APITimeoutError, APIError) as error:
            last_error = error
            if attempt >= max_retries:
                break
            time.sleep(retry_backoff_seconds * (attempt + 1))
        except json.JSONDecodeError as error:
            raise OpenAIClientError(f"OpenAI response was not valid JSON: {error}") from error

    raise OpenAIClientError(f"OpenAI request failed after retries: {last_error}")


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
