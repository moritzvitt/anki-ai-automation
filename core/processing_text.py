from __future__ import annotations

import html
import re

from ..services.openai_client import OpenAIClientError


def markdown_to_html(value: str) -> str:
    lines = value.strip().splitlines()
    if not lines:
        return ""

    blocks: list[str] = []
    paragraph_lines: list[str] = []
    list_items: list[str] = []
    ordered_list_items: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        if paragraph_lines:
            blocks.append("<p>" + "<br>".join(format_inline_markdown(line) for line in paragraph_lines) + "</p>")
            paragraph_lines = []

    def flush_list() -> None:
        nonlocal list_items
        if list_items:
            blocks.append("<ul>" + "".join(f"<li>{item}</li>" for item in list_items) + "</ul>")
            list_items = []

    def flush_ordered_list() -> None:
        nonlocal ordered_list_items
        if ordered_list_items:
            blocks.append("<ol>" + "".join(f"<li>{item}</li>" for item in ordered_list_items) + "</ol>")
            ordered_list_items = []

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            flush_list()
            flush_ordered_list()
            continue
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading_match:
            flush_paragraph()
            flush_list()
            flush_ordered_list()
            level = len(heading_match.group(1))
            heading_text = format_inline_markdown(heading_match.group(2).strip())
            blocks.append(f"<h{level}>{heading_text}</h{level}>")
            continue
        if stripped.startswith(("- ", "* ")):
            flush_paragraph()
            flush_ordered_list()
            list_items.append(format_inline_markdown(stripped[2:].strip()))
            continue
        ordered_list_match = re.match(r"^\d+\.\s+(.+)$", stripped)
        if ordered_list_match:
            flush_paragraph()
            flush_list()
            ordered_list_items.append(format_inline_markdown(ordered_list_match.group(1).strip()))
            continue
        flush_list()
        flush_ordered_list()
        paragraph_lines.append(stripped)

    flush_paragraph()
    flush_list()
    flush_ordered_list()
    return "\n".join(blocks)


def format_inline_markdown(value: str) -> str:
    escaped = html.escape(value)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", escaped)
    escaped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', escaped)
    return escaped


def parse_delimited_field_updates(
    *,
    response_text: str,
    response_delimiter: str,
    available_fields: list[str],
) -> tuple[dict[str, str], list[str]]:
    prefix, suffix = split_field_delimiter(response_delimiter)
    field_lookup = {field_name.casefold(): field_name for field_name in available_fields}
    marker_pattern = re.compile(
        rf"(?m)^{re.escape(prefix)}\s*(?P<field>.+?)\s*{re.escape(suffix)}\s*$"
    )
    matches = list(marker_pattern.finditer(response_text))
    if not matches:
        raise OpenAIClientError(
            "The response did not contain any field markers that matched the configured delimiter."
        )

    parsed_updates: dict[str, str] = {}
    warnings: list[str] = []
    unknown_fields: list[str] = []

    for index, match in enumerate(matches):
        raw_field_name = match.group("field").strip()
        normalized_field_name = normalize_delimited_field_name(raw_field_name)
        section_start = match.end()
        section_end = matches[index + 1].start() if index + 1 < len(matches) else len(response_text)
        section_value = response_text[section_start:section_end].strip()
        canonical_name = field_lookup.get(normalized_field_name.casefold())
        if canonical_name is None:
            unknown_fields.append(raw_field_name)
            continue
        if canonical_name in parsed_updates and section_value:
            parsed_updates[canonical_name] = parsed_updates[canonical_name].rstrip() + "\n\n" + section_value
            warnings.append(f"Field '{canonical_name}' appeared multiple times and its sections were merged.")
            continue
        parsed_updates[canonical_name] = section_value

    if unknown_fields:
        warnings.append("Ignored unknown field section(s): " + ", ".join(sorted(set(unknown_fields))) + ".")
    return parsed_updates, warnings


def normalize_delimited_field_name(value: str) -> str:
    normalized = value.strip()
    if normalized.startswith("{") and normalized.endswith("}") and len(normalized) >= 2:
        return normalized[1:-1].strip()
    return normalized


def split_field_delimiter(delimiter: str) -> tuple[str, str]:
    normalized = delimiter.strip().replace("{field-name}", "{field}")
    if not normalized:
        raise OpenAIClientError("Multiple target field mode requires a response delimiter.")
    if "{field}" in normalized:
        prefix, suffix = normalized.split("{field}", 1)
        if not prefix and not suffix:
            raise OpenAIClientError("The response delimiter must include text around '{field}'.")
        return prefix, suffix

    match = re.match(r"^(?P<prefix>[^A-Za-z0-9]*).+?(?P<suffix>[^A-Za-z0-9]*)$", normalized)
    if match is None:
        raise OpenAIClientError(
            "The response delimiter must look like '--Notes--' or include a '{field}' placeholder."
        )
    prefix = match.group("prefix")
    suffix = match.group("suffix")
    if not prefix and not suffix:
        raise OpenAIClientError(
            "The response delimiter must look like '--Notes--' or include a '{field}' placeholder."
        )
    return prefix, suffix
