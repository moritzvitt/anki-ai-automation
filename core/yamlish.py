from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_yamlish_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    value, _ = parse_yamlish_block(yamlish_lines(text), 0, 0)
    if not isinstance(value, dict):
        raise ValueError(f"Automation file '{path}' must contain a top-level mapping.")
    return value


def write_yamlish_file(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yamlish(value), encoding="utf-8")


def yamlish_lines(text: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        lines.append((indent, raw_line[indent:]))
    return lines


def parse_yamlish_block(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[Any, int]:
    if index >= len(lines):
        return {}, index
    current_indent, current_text = lines[index]
    if current_indent != indent:
        raise ValueError(f"Unexpected indent at '{current_text}'.")
    if current_text.startswith("-"):
        return parse_yamlish_list(lines, index, indent)
    return parse_yamlish_mapping(lines, index, indent)


def parse_yamlish_list(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    while index < len(lines):
        current_indent, current_text = lines[index]
        if current_indent < indent:
            break
        if current_indent != indent or not current_text.startswith("-"):
            break
        remainder = current_text[1:].strip()
        if remainder:
            items.append(parse_yamlish_scalar(remainder))
            index += 1
            continue
        index += 1
        child, index = parse_yamlish_block(lines, index, indent + 2)
        items.append(child)
    return items, index


def parse_yamlish_mapping(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[dict[str, Any], int]:
    mapping: dict[str, Any] = {}
    while index < len(lines):
        current_indent, current_text = lines[index]
        if current_indent < indent:
            break
        if current_indent != indent:
            raise ValueError(f"Unexpected indent at '{current_text}'.")
        if ":" not in current_text:
            raise ValueError(f"Expected key/value pair at '{current_text}'.")
        key, remainder = current_text.split(":", 1)
        key = key.strip()
        remainder = remainder.strip()
        if not key:
            raise ValueError("Empty mapping key.")
        if remainder:
            mapping[key] = parse_yamlish_scalar(remainder)
            index += 1
            continue
        index += 1
        if index >= len(lines) or lines[index][0] <= indent:
            mapping[key] = {}
            continue
        child, index = parse_yamlish_block(lines, index, indent + 2)
        mapping[key] = child
    return mapping, index


def parse_yamlish_scalar(text: str) -> Any:
    lowered = text.lower()
    if lowered == "null":
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if text == "[]":
        return []
    if text == "{}":
        return {}

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def dump_yamlish(value: Any, indent: int = 0) -> str:
    return "\n".join(dump_yamlish_lines(value, indent)) + "\n"


def dump_yamlish_lines(value: Any, indent: int) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if item is None:
                lines.append(f"{prefix}{key}: null")
            elif isinstance(item, (dict, list)):
                if not item:
                    empty = "{}" if isinstance(item, dict) else "[]"
                    lines.append(f"{prefix}{key}: {empty}")
                else:
                    lines.append(f"{prefix}{key}:")
                    lines.extend(dump_yamlish_lines(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {format_yamlish_scalar(item)}")
        return lines
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                if not item:
                    empty = "{}" if isinstance(item, dict) else "[]"
                    lines.append(f"{prefix}- {empty}")
                else:
                    lines.append(f"{prefix}-")
                    lines.extend(dump_yamlish_lines(item, indent + 2))
            else:
                lines.append(f"{prefix}- {format_yamlish_scalar(item)}")
        return lines
    return [f"{prefix}{format_yamlish_scalar(value)}"]


def format_yamlish_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)
