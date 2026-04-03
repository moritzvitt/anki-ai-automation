from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .yamlish import read_yamlish_file, write_yamlish_file


def ordered_automation_values(
    items_by_id: dict[str, Any],
    configured_order: Any,
    file_order: list[str],
) -> list[Any]:
    ordered_ids = configured_order if isinstance(configured_order, list) else []
    ordered_ids = [item for item in ordered_ids if isinstance(item, str) and item] or file_order
    items: list[Any] = []
    seen_ids: set[str] = set()
    for item_id in ordered_ids:
        item = items_by_id.get(item_id)
        if item is None or item_id in seen_ids:
            continue
        items.append(item)
        seen_ids.add(item_id)
    for item_id in file_order:
        if item_id in seen_ids:
            continue
        item = items_by_id[item_id]
        items.append(item)
        seen_ids.add(item_id)
    return items


def load_automation_files(
    default_dir: Path,
    user_dir: Path,
    *,
    parser: Callable[[dict[str, Any], int], Any],
    item_id_getter: Callable[[Any], str],
) -> tuple[dict[str, Any], list[str]]:
    merged: dict[str, Any] = {}
    order: list[str] = []
    index = 0
    for directory in (default_dir, user_dir):
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.yaml")):
            item = parser(read_yamlish_file(path), index=index)
            index += 1
            item_id = item_id_getter(item)
            merged[item_id] = item
            if item_id in order:
                order.remove(item_id)
            order.append(item_id)
    return merged, order


def import_legacy_automation_to_files(
    target_dir: Path,
    legacy_items: list[Any],
    *,
    item_id_getter: Callable[[Any], str],
    item_to_dict: Callable[[Any], dict[str, Any]],
    default_dir: Path | None = None,
) -> bool:
    imported = False
    target_dir.mkdir(parents=True, exist_ok=True)
    for item in legacy_items:
        item_id = item_id_getter(item).strip()
        if not item_id:
            continue
        item_dict = item_to_dict(item)
        path = target_dir / f"{item_id}.yaml"
        if default_dir is not None:
            default_path = default_dir / f"{item_id}.yaml"
            if default_path.exists() and read_yamlish_file(default_path) == item_dict:
                if path.exists():
                    path.unlink()
                continue
        write_yamlish_file(path, item_dict)
        imported = True
    return imported


def save_automation_items(
    items: list[Any],
    *,
    default_dir: Path,
    user_dir: Path,
    item_id_getter: Callable[[Any], str],
    item_to_dict: Callable[[Any], dict[str, Any]],
) -> list[str]:
    ordered_ids: list[str] = []
    seen_ids: set[str] = set()
    user_dir.mkdir(parents=True, exist_ok=True)
    for item in items:
        item_id = item_id_getter(item).strip()
        if not item_id:
            continue
        item_dict = item_to_dict(item)
        default_path = default_dir / f"{item_id}.yaml"
        user_path = user_dir / f"{item_id}.yaml"
        if default_path.exists() and read_yamlish_file(default_path) == item_dict:
            if user_path.exists():
                user_path.unlink()
        else:
            write_yamlish_file(user_path, item_dict)
        if item_id not in seen_ids:
            ordered_ids.append(item_id)
            seen_ids.add(item_id)
    prune_removed_user_automation_files(user_dir, active_ids=seen_ids)
    return ordered_ids


def prune_removed_user_automation_files(user_dir: Path, *, active_ids: set[str]) -> None:
    if not user_dir.exists():
        return
    for path in user_dir.glob("*.yaml"):
        if path.stem not in active_ids:
            path.unlink()
