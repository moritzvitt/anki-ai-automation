from __future__ import annotations

from functools import lru_cache
import re
from typing import Mapping


PLACEHOLDER_PATTERN = re.compile(r"{{\s*([^{}]+?)\s*}}")


def render_prompt(template: str, values: Mapping[str, str]) -> str:
    parts = _compiled_template_parts(template)
    rendered: list[str] = []
    for part_type, value in parts:
        if part_type == "text":
            rendered.append(value)
        else:
            rendered.append(values.get(value, ""))
    return "".join(rendered)


def extract_placeholders(template: str) -> list[str]:
    return list(_extract_placeholders_cached(template))


@lru_cache(maxsize=128)
def _compiled_template_parts(template: str) -> tuple[tuple[str, str], ...]:
    parts: list[tuple[str, str]] = []
    last_end = 0
    for match in PLACEHOLDER_PATTERN.finditer(template):
        start, end = match.span()
        if start > last_end:
            parts.append(("text", template[last_end:start]))
        key = match.group(1).strip()
        parts.append(("placeholder", key))
        last_end = end
    if last_end < len(template):
        parts.append(("text", template[last_end:]))
    return tuple(parts)


@lru_cache(maxsize=128)
def _extract_placeholders_cached(template: str) -> tuple[str, ...]:
    placeholders: list[str] = []
    seen: set[str] = set()
    for match in PLACEHOLDER_PATTERN.finditer(template):
        key = match.group(1).strip()
        if key and key not in seen:
            placeholders.append(key)
            seen.add(key)
    return tuple(placeholders)
