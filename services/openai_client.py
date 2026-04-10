from __future__ import annotations

from functools import lru_cache
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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


@dataclass(frozen=True)
class AITextResponseResult:
    output_text: str
    usage: TokenUsage


@dataclass(frozen=True)
class AIJSONTextResponseResult:
    output_text: str
    usage: TokenUsage


@dataclass(frozen=True)
class AITTSResponseResult:
    audio_bytes: bytes
    media_type: str
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
    use_chat_completions_api: bool,
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
    current_reasoning_effort = reasoning_effort
    for attempt in range(max_retries + 1):
        try:
            if use_chat_completions_api:
                response = client.chat.completions.create(
                    **_chat_completion_payload(
                        model=model,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        temperature=temperature if use_temperature else None,
                        response_format=_chat_json_schema_response_format(output_fields),
                    )
                )
                content = _chat_completion_text(response)
                parsed = json.loads(content)
                return AIFieldUpdateResult(
                    field_updates=_validate_output(parsed, output_fields),
                    usage=_parse_chat_usage(getattr(response, "usage", None)),
                )

            payload: dict[str, Any] = {
                "model": model,
                "input": _request_input(system_prompt=system_prompt, user_prompt=user_prompt),
                "text": {"format": response_format},
            }
            if use_temperature and temperature is not None:
                payload["temperature"] = temperature
            if current_reasoning_effort:
                payload["reasoning"] = {"effort": current_reasoning_effort}

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
            next_reasoning_effort = _fallback_reasoning_effort(error, current_reasoning_effort)
            if next_reasoning_effort != current_reasoning_effort:
                current_reasoning_effort = next_reasoning_effort
                last_error = error
                continue
            last_error = error
            if attempt >= max_retries:
                break
            time.sleep(retry_backoff_seconds * (attempt + 1))
        except json.JSONDecodeError as error:
            raise OpenAIClientError(f"OpenAI response was not valid JSON: {error}") from error

    raise OpenAIClientError(f"OpenAI request failed after retries: {last_error}")


def request_responses_json_text(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    schema_name: str,
    schema: dict[str, Any],
    timeout_seconds: float,
    max_retries: int,
    retry_backoff_seconds: float,
    temperature: float | None,
    reasoning_effort: str | None,
) -> AIJSONTextResponseResult:
    if OpenAI is None:
        raise OpenAIClientError(
            "The official OpenAI Python client is not installed. "
            "Install the 'openai' package into Anki's Python environment first."
        )
    if not api_key.strip():
        raise OpenAIClientError("Set 'openai_api_key' in the add-on config before running AI Automation.")

    client = _build_client(api_key=api_key, timeout_seconds=timeout_seconds)
    response_format = {
        "type": "json_schema",
        "name": schema_name,
        "strict": True,
        "schema": schema,
    }

    last_error: Exception | None = None
    use_temperature = temperature is not None
    current_reasoning_effort = reasoning_effort
    for attempt in range(max_retries + 1):
        try:
            payload: dict[str, Any] = {
                "model": model,
                "input": _request_input(system_prompt=system_prompt, user_prompt=user_prompt),
                "text": {"format": response_format},
            }
            if use_temperature and temperature is not None:
                payload["temperature"] = temperature
            if current_reasoning_effort:
                payload["reasoning"] = {"effort": current_reasoning_effort}

            response = client.responses.create(**payload)
            output_text = str(getattr(response, "output_text", "") or "").strip()
            if not output_text:
                raise OpenAIClientError("The model returned an empty response.")

            return AIJSONTextResponseResult(
                output_text=output_text,
                usage=_parse_usage(getattr(response, "usage", None)),
            )
        except (RateLimitError, APIConnectionError, APITimeoutError, APIError) as error:
            if use_temperature and _is_unsupported_parameter_error(error, "temperature"):
                use_temperature = False
                last_error = error
                continue
            next_reasoning_effort = _fallback_reasoning_effort(error, current_reasoning_effort)
            if next_reasoning_effort != current_reasoning_effort:
                current_reasoning_effort = next_reasoning_effort
                last_error = error
                continue
            last_error = error
            if attempt >= max_retries:
                break
            time.sleep(retry_backoff_seconds * (attempt + 1))

    raise OpenAIClientError(f"OpenAI request failed after retries: {last_error}")


def request_text_response(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout_seconds: float,
    max_retries: int,
    retry_backoff_seconds: float,
    temperature: float | None,
    reasoning_effort: str | None,
    use_chat_completions_api: bool,
) -> AITextResponseResult:
    if OpenAI is None:
        raise OpenAIClientError(
            "The official OpenAI Python client is not installed. "
            "Install the 'openai' package into Anki's Python environment first."
        )
    if not api_key.strip():
        raise OpenAIClientError("Set 'openai_api_key' in the add-on config before running AI Automation.")

    client = _build_client(api_key=api_key, timeout_seconds=timeout_seconds)

    last_error: Exception | None = None
    use_temperature = temperature is not None
    current_reasoning_effort = reasoning_effort
    for attempt in range(max_retries + 1):
        try:
            if use_chat_completions_api:
                response = client.chat.completions.create(
                    **_chat_completion_payload(
                        model=model,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        temperature=temperature if use_temperature else None,
                    )
                )
                output_text = _chat_completion_text(response).strip()
                if not output_text:
                    raise OpenAIClientError("The model returned an empty response.")
                return AITextResponseResult(
                    output_text=output_text,
                    usage=_parse_chat_usage(getattr(response, "usage", None)),
                )

            payload: dict[str, Any] = {
                "model": model,
                "input": _request_input(system_prompt=system_prompt, user_prompt=user_prompt),
            }
            if use_temperature and temperature is not None:
                payload["temperature"] = temperature
            if current_reasoning_effort:
                payload["reasoning"] = {"effort": current_reasoning_effort}

            response = client.responses.create(**payload)
            output_text = str(getattr(response, "output_text", "") or "").strip()
            if not output_text:
                raise OpenAIClientError("The model returned an empty response.")

            return AITextResponseResult(
                output_text=output_text,
                usage=_parse_usage(getattr(response, "usage", None)),
            )
        except (RateLimitError, APIConnectionError, APITimeoutError, APIError) as error:
            if use_temperature and _is_unsupported_parameter_error(error, "temperature"):
                use_temperature = False
                last_error = error
                continue
            next_reasoning_effort = _fallback_reasoning_effort(error, current_reasoning_effort)
            if next_reasoning_effort != current_reasoning_effort:
                current_reasoning_effort = next_reasoning_effort
                last_error = error
                continue
            last_error = error
            if attempt >= max_retries:
                break
            time.sleep(retry_backoff_seconds * (attempt + 1))

    raise OpenAIClientError(f"OpenAI request failed after retries: {last_error}")


def request_tts_audio(
    *,
    api_key: str,
    model: str,
    voice: str,
    input_text: str,
    timeout_seconds: float,
    max_retries: int,
    retry_backoff_seconds: float,
    audio_format: str = "mp3",
) -> AITTSResponseResult:
    if not api_key.strip():
        raise OpenAIClientError("Set 'openai_api_key' in the add-on config before running AI Automation.")
    if not input_text.strip():
        raise OpenAIClientError("The selected TTS source field is empty.")

    payload = json.dumps(
        {
            "model": model,
            "voice": voice,
            "input": input_text,
            "format": audio_format,
        }
    ).encode("utf-8")

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        request = Request(
            url="https://api.openai.com/v1/audio/speech",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            data=payload,
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                audio_bytes = response.read()
                if not audio_bytes:
                    raise OpenAIClientError("The TTS model returned an empty audio file.")
                return AITTSResponseResult(
                    audio_bytes=audio_bytes,
                    media_type=str(response.headers.get_content_type() or _media_type_for_audio_format(audio_format)),
                    usage=TokenUsage(
                        input_tokens=0,
                        cached_input_tokens=0,
                        output_tokens=0,
                        reasoning_tokens=0,
                        total_tokens=0,
                    ),
                )
        except HTTPError as error:
            last_error = OpenAIClientError(f"OpenAI TTS request failed: {_http_error_message(error)}")
        except (URLError, OSError) as error:
            last_error = OpenAIClientError(f"OpenAI TTS request failed: {error}")
        if attempt >= max_retries:
            break
        time.sleep(retry_backoff_seconds * (attempt + 1))

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
    current_reasoning_effort = reasoning_effort
    try:
        payload: dict[str, Any] = {
            "model": model,
            "input": _request_input(system_prompt=system_prompt, user_prompt=user_prompt),
            "text": {"format": _response_format(output_fields)},
        }
        while True:
            request_payload = dict(payload)
            if current_reasoning_effort:
                request_payload["reasoning"] = {"effort": current_reasoning_effort}
            result = client.responses.input_tokens.count(**request_payload)
            return int(result.input_tokens)
    except (RateLimitError, APIConnectionError, APITimeoutError, APIError) as error:
        next_reasoning_effort = _fallback_reasoning_effort(error, current_reasoning_effort)
        if next_reasoning_effort != current_reasoning_effort:
            try:
                retry_payload: dict[str, Any] = {
                    "model": model,
                    "input": _request_input(system_prompt=system_prompt, user_prompt=user_prompt),
                    "text": {"format": _response_format(output_fields)},
                }
                if next_reasoning_effort:
                    retry_payload["reasoning"] = {"effort": next_reasoning_effort}
                result = client.responses.input_tokens.count(**retry_payload)
                return int(result.input_tokens)
            except (RateLimitError, APIConnectionError, APITimeoutError, APIError) as retry_error:
                raise OpenAIClientError(f"Failed to count input tokens: {retry_error}") from retry_error
        raise OpenAIClientError(f"Failed to count input tokens: {error}") from error


def count_request_input_tokens_for_text(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
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
    current_reasoning_effort = reasoning_effort
    try:
        payload: dict[str, Any] = {
            "model": model,
            "input": _request_input(system_prompt=system_prompt, user_prompt=user_prompt),
        }
        while True:
            request_payload = dict(payload)
            if current_reasoning_effort:
                request_payload["reasoning"] = {"effort": current_reasoning_effort}
            result = client.responses.input_tokens.count(**request_payload)
            return int(result.input_tokens)
    except (RateLimitError, APIConnectionError, APITimeoutError, APIError) as error:
        next_reasoning_effort = _fallback_reasoning_effort(error, current_reasoning_effort)
        if next_reasoning_effort != current_reasoning_effort:
            try:
                retry_payload: dict[str, Any] = {
                    "model": model,
                    "input": _request_input(system_prompt=system_prompt, user_prompt=user_prompt),
                }
                if next_reasoning_effort:
                    retry_payload["reasoning"] = {"effort": next_reasoning_effort}
                result = client.responses.input_tokens.count(**retry_payload)
                return int(result.input_tokens)
            except (RateLimitError, APIConnectionError, APITimeoutError, APIError) as retry_error:
                raise OpenAIClientError(f"Failed to count input tokens: {retry_error}") from retry_error
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
    return _cached_client(api_key, timeout_seconds)


@lru_cache(maxsize=8)
def _cached_client(api_key: str, timeout_seconds: float) -> Any:
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


def _chat_completion_payload(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float | None,
    response_format: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if response_format is not None:
        payload["response_format"] = response_format
    return payload


def _chat_json_schema_response_format(output_fields: list[str]) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "anki_field_update",
            "strict": True,
            "schema": _output_schema(output_fields),
        },
    }


def _chat_completion_text(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise OpenAIClientError("The model returned no choices.")
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                parts.append(text)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    raise OpenAIClientError("The model returned an unexpected chat completion format.")


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


def _parse_chat_usage(usage: Any) -> TokenUsage:
    if usage is None:
        return TokenUsage(
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            reasoning_tokens=0,
            total_tokens=0,
        )
    prompt_tokens_details = getattr(usage, "prompt_tokens_details", None)
    completion_tokens_details = getattr(usage, "completion_tokens_details", None)
    return TokenUsage(
        input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        cached_input_tokens=int(getattr(prompt_tokens_details, "cached_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        reasoning_tokens=int(getattr(completion_tokens_details, "reasoning_tokens", 0) or 0),
        total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
    )


def _is_unsupported_parameter_error(error: Exception, parameter_name: str) -> bool:
    message = str(error).lower()
    return (
        (
            "unsupported parameter" in message
            or "unsupported value" in message
            or "does not support" in message
        )
        and parameter_name.lower() in message
    )


def _fallback_reasoning_effort(error: Exception, current_reasoning_effort: str | None) -> str | None:
    if not current_reasoning_effort:
        return current_reasoning_effort
    if not _is_unsupported_parameter_error(error, "reasoning.effort"):
        return current_reasoning_effort
    if current_reasoning_effort != "medium":
        return "medium"
    return None


def _http_error_message(error: HTTPError) -> str:
    try:
        payload = error.read().decode("utf-8")
    except Exception:
        return str(error)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return payload
    if isinstance(data, dict):
        body_error = data.get("error")
        if isinstance(body_error, dict):
            message = body_error.get("message")
            if isinstance(message, str) and message.strip():
                return message
    return payload


def _media_type_for_audio_format(audio_format: str) -> str:
    normalized = audio_format.lower().strip()
    if normalized == "wav":
        return "audio/wav"
    if normalized == "opus":
        return "audio/ogg"
    if normalized == "flac":
        return "audio/flac"
    return "audio/mpeg"
