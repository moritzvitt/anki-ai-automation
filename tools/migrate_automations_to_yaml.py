from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
CONFIG_JSON = ROOT / "config.json"
META_JSON = ROOT / "meta.json"

AUTOMATION_LIBRARY_ROOT = ROOT / "automation_library"
DEFAULT_GROUPS_DIR = AUTOMATION_LIBRARY_ROOT / "groups"
DEFAULT_WORKFLOWS_DIR = AUTOMATION_LIBRARY_ROOT / "workflows"

USER_DATA_ROOT = ROOT / "user_data"
USER_GROUPS_DIR = USER_DATA_ROOT / "groups"
USER_WORKFLOWS_DIR = USER_DATA_ROOT / "workflows"

WORKFLOW_GROUP_ORDER_KEY = "workflow_group_order"
WORKFLOW_ORDER_KEY = "workflow_order"


def main() -> None:
    migrate_file(
        CONFIG_JSON,
        groups_dir=DEFAULT_GROUPS_DIR,
        workflows_dir=DEFAULT_WORKFLOWS_DIR,
        default_groups_dir=None,
        default_workflows_dir=None,
        wrapped=False,
    )
    migrate_file(
        META_JSON,
        groups_dir=USER_GROUPS_DIR,
        workflows_dir=USER_WORKFLOWS_DIR,
        default_groups_dir=DEFAULT_GROUPS_DIR,
        default_workflows_dir=DEFAULT_WORKFLOWS_DIR,
        wrapped=True,
    )


def migrate_file(
    path: Path,
    *,
    groups_dir: Path,
    workflows_dir: Path,
    default_groups_dir: Path | None,
    default_workflows_dir: Path | None,
    wrapped: bool,
) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    scope = data.get("config") if wrapped else data
    if not isinstance(scope, dict):
        raise SystemExit(f"{path} does not contain the expected config object.")

    group_ids = export_items(
        scope.get("workflow_groups", []),
        groups_dir,
        default_dir=default_groups_dir,
    ) or read_existing_order(scope.get(WORKFLOW_GROUP_ORDER_KEY), groups_dir)
    workflow_ids = export_items(
        scope.get("workflows", []),
        workflows_dir,
        default_dir=default_workflows_dir,
    ) or read_existing_order(scope.get(WORKFLOW_ORDER_KEY), workflows_dir)

    scope["workflow_groups"] = []
    scope["workflows"] = []
    scope[WORKFLOW_GROUP_ORDER_KEY] = group_ids
    scope[WORKFLOW_ORDER_KEY] = workflow_ids
    scope.pop("pipelines", None)
    scope.pop("pipeline_order", None)

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def export_items(items: Any, directory: Path, *, default_dir: Path | None) -> list[str]:
    if items in (None, []):
        directory.mkdir(parents=True, exist_ok=True)
        return []
    if not isinstance(items, list):
        raise SystemExit(f"Expected a list of automation items for {directory}.")

    directory.mkdir(parents=True, exist_ok=True)
    ordered_ids: list[str] = []
    active_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise SystemExit(f"Expected dict entries in {directory}.")
        item_id = str(item.get("id", "")).strip()
        if not item_id:
            raise SystemExit(f"Automation item in {directory} is missing an id.")
        ordered_ids.append(item_id)
        active_ids.add(item_id)
        target_path = directory / f"{item_id}.yaml"
        if default_dir is not None:
            default_path = default_dir / f"{item_id}.yaml"
            if default_path.exists() and read_yamlish_file(default_path) == item:
                if target_path.exists():
                    target_path.unlink()
                continue
        write_yamlish_file(target_path, item)

    for existing in directory.glob("*.yaml"):
        if existing.stem not in active_ids:
            existing.unlink()

    return ordered_ids


def read_existing_order(value: Any, directory: Path) -> list[str]:
    if isinstance(value, list):
        order = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        if order:
            return order
    if not directory.exists():
        return []
    return [path.stem for path in sorted(directory.glob("*.yaml"))]


def write_yamlish_file(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yamlish(value), encoding="utf-8")


def read_yamlish_file(path: Path) -> dict[str, Any]:
    value, _ = parse_yamlish_block(yamlish_lines(path.read_text(encoding="utf-8")), 0, 0)
    if not isinstance(value, dict):
        raise SystemExit(f"{path} must contain a top-level mapping.")
    return value


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
                lines.append(f"{prefix}{key}: {format_scalar(item)}")
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
                lines.append(f"{prefix}- {format_scalar(item)}")
        return lines
    return [f"{prefix}{format_scalar(value)}"]


def format_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


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


if __name__ == "__main__":
    main()
