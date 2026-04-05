from __future__ import annotations

from functools import lru_cache
import html
import re
from typing import Mapping


PLACEHOLDER_PATTERN = re.compile(r"{{\s*([^{}]+?)\s*}}")
CLOZE_LITERAL_PATTERN = re.compile(r"(?i)^c\d+::")
PROMPT_HTML_STRIP_FIELDS = frozenset({"Cloze", "Subtitle"})


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


def build_prompt_values(values: Mapping[str, str], *, note_type_name: str | None = None) -> dict[str, str]:
    """Prepare prompt placeholder values shared across all API-bound flows.

    `Cloze` and `Subtitle` are always stripped down to plain text before being
    sent to a model so HTML-heavy note content does not leak into prompts.
    """
    prompt_values = {
        key: strip_html_for_prompt(value) if key in PROMPT_HTML_STRIP_FIELDS else value
        for key, value in values.items()
    }
    if note_type_name is not None:
        prompt_values["NoteType"] = note_type_name
    return prompt_values


def strip_html_for_prompt(value: str) -> str:
    if not value:
        return ""
    text = re.sub(r"(?i)<br\s*/?>", "\n", value)
    text = re.sub(r"(?is)<style.*?>.*?</style>", "", text)
    text = re.sub(r"(?is)<script.*?>.*?</script>", "", text)
    text = re.sub(r"(?s)<[^>]+>", "", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


@lru_cache(maxsize=128)
def _compiled_template_parts(template: str) -> tuple[tuple[str, str], ...]:
    parts: list[tuple[str, str]] = []
    last_end = 0
    for match in PLACEHOLDER_PATTERN.finditer(template):
        start, end = match.span()
        if start > last_end:
            parts.append(("text", template[last_end:start]))
        key = match.group(1).strip()
        if _is_literal_cloze_placeholder(key):
            parts.append(("text", template[start:end]))
        else:
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
        if _is_literal_cloze_placeholder(key):
            continue
        if key and key not in seen:
            placeholders.append(key)
            seen.add(key)
    return tuple(placeholders)


def _is_literal_cloze_placeholder(key: str) -> bool:
    return bool(CLOZE_LITERAL_PATTERN.match(key))
