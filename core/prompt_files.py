from __future__ import annotations

from pathlib import Path
from typing import Any


def read_prompt_markdown(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8").strip()
    lines = text.splitlines()
    if not lines or not lines[0].startswith("# "):
        raise ValueError(f"Prompt file '{path}' must start with a '# Name' heading.")
    name = lines[0][2:].strip()
    body_lines = lines[1:]
    while body_lines and not body_lines[0].strip():
        body_lines = body_lines[1:]
    prompt_text = "\n".join(body_lines).strip()
    if not prompt_text:
        raise ValueError(f"Prompt file '{path}' has no prompt body.")
    return name, prompt_text


def write_prompt_markdown(path: Path, name: str, prompt_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"# {name.strip()}\n\n{prompt_text.strip()}\n"
    path.write_text(content, encoding="utf-8")


def read_prompt_order(value: Any) -> list[str]:
    if value in (None, []):
        return []
    if not isinstance(value, list):
        return []
    order: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        prompt_id = item.strip()
        if prompt_id and prompt_id not in seen:
            order.append(prompt_id)
            seen.add(prompt_id)
    return order
