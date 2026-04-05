from __future__ import annotations

from pathlib import Path

from .config_models import SavedPrompt, SavedSystemPrompt
from .prompt_files import read_prompt_markdown, write_prompt_markdown


def load_prompt_files(
    *,
    default_prompts_dir: Path,
    user_prompts_dir: Path,
) -> tuple[dict[str, SavedPrompt], list[str]]:
    merged: dict[str, SavedPrompt] = {}
    order: list[str] = []
    for directory in (default_prompts_dir, user_prompts_dir):
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*.md")):
            prompt_id = path.relative_to(directory).with_suffix("").as_posix()
            name, prompt_text = read_prompt_markdown(path)
            merged[prompt_id] = SavedPrompt(
                prompt_id=prompt_id,
                name=name,
                prompt_text=prompt_text,
            )
            if prompt_id in order:
                order.remove(prompt_id)
            order.append(prompt_id)
    return merged, order


def import_legacy_prompts_to_files(
    *,
    file_prompts: dict[str, SavedPrompt],
    legacy_prompts: list[SavedPrompt],
    user_prompts_dir: Path,
) -> bool:
    imported = False
    for prompt in legacy_prompts:
        current = file_prompts.get(prompt.prompt_id)
        if current is not None and current.name == prompt.name and current.prompt_text == prompt.prompt_text:
            continue
        write_prompt_markdown(prompt_path_for_id(user_prompts_dir, prompt.prompt_id), prompt.name, prompt.prompt_text)
        imported = True
    return imported


def target_prompt_path(prompt_id: str, *, default_prompts_dir: Path, user_prompts_dir: Path) -> Path:
    default_path = prompt_path_for_id(default_prompts_dir, prompt_id)
    if default_path.exists():
        return default_path
    return prompt_path_for_id(user_prompts_dir, prompt_id)


def prune_removed_user_prompt_files(active_prompt_ids: set[str], *, user_prompts_dir: Path) -> None:
    if not user_prompts_dir.exists():
        return
    for path in user_prompts_dir.rglob("*.md"):
        prompt_id = path.relative_to(user_prompts_dir).with_suffix("").as_posix()
        if prompt_id not in active_prompt_ids:
            path.unlink()
    for directory in sorted(user_prompts_dir.rglob("*"), reverse=True):
        if directory.is_dir():
            try:
                directory.rmdir()
            except OSError:
                pass


def prompt_path_for_id(root: Path, prompt_id: str) -> Path:
    cleaned_id = prompt_id.strip().replace("\\", "/")
    if not cleaned_id:
        return root / "prompt.md"
    parts = [part for part in cleaned_id.split("/") if part and part not in {".", ".."}]
    return root.joinpath(*parts).with_suffix(".md")


def load_system_prompt_files(
    *,
    system_prompts_dir: Path,
) -> tuple[dict[str, SavedSystemPrompt], list[str]]:
    merged: dict[str, SavedSystemPrompt] = {}
    order: list[str] = []
    if not system_prompts_dir.exists():
        return merged, order
    for path in sorted(system_prompts_dir.rglob("*.md")):
        prompt_id = path.relative_to(system_prompts_dir).with_suffix("").as_posix()
        name, prompt_text = read_prompt_markdown(path)
        merged[prompt_id] = SavedSystemPrompt(
            prompt_id=prompt_id,
            name=name,
            prompt_text=prompt_text,
        )
        if prompt_id in order:
            order.remove(prompt_id)
        order.append(prompt_id)
    return merged, order


def import_legacy_system_prompts_to_files(
    *,
    file_prompts: dict[str, SavedSystemPrompt],
    legacy_prompts: list[SavedSystemPrompt],
    system_prompts_dir: Path,
) -> bool:
    imported = False
    for prompt in legacy_prompts:
        current = file_prompts.get(prompt.prompt_id)
        if current is not None and current.name == prompt.name and current.prompt_text == prompt.prompt_text:
            continue
        write_prompt_markdown(prompt_path_for_id(system_prompts_dir, prompt.prompt_id), prompt.name, prompt.prompt_text)
        imported = True
    return imported


def prune_removed_system_prompt_files(active_prompt_ids: set[str], *, system_prompts_dir: Path) -> None:
    if not system_prompts_dir.exists():
        return
    for path in system_prompts_dir.rglob("*.md"):
        prompt_id = path.relative_to(system_prompts_dir).with_suffix("").as_posix()
        if prompt_id not in active_prompt_ids:
            path.unlink()
    for directory in sorted(system_prompts_dir.rglob("*"), reverse=True):
        if directory.is_dir():
            try:
                directory.rmdir()
            except OSError:
                pass


def prompt_config_scope(raw_config: dict[str, object]) -> dict[str, object]:
    nested = raw_config.get("config")
    if isinstance(nested, dict):
        return nested
    return raw_config
