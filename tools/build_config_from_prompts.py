from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
PROMPT_LIBRARY = ROOT / "prompt_library"

USER_PROMPT_ORDER = [
    "default-prompt",
    "card-quality-check",
    "update-japanese-notes",
    "update-grammar-notes",
    "full-card-optimization",
    "mlr-card-quality-check",
    "mlr-full-field-refactor",
    "mlr-japanese-notes-improver",
    "mlr-word-definition-optimizer",
    "mlr-grammar-notes-generator",
    "mlr-cloze-optimization",
    "mlr-fix-only-whats-wrong",
]

SYSTEM_PROMPT_ORDER = [
    "default-system-prompt",
    "delimited-field-sections",
]


def read_prompt_markdown(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8").strip()
    lines = text.splitlines()
    if not lines or not lines[0].startswith("# "):
        raise SystemExit(f"{path} must start with a '# Name' heading.")
    name = lines[0][2:].strip()
    body_lines = lines[1:]
    while body_lines and not body_lines[0].strip():
        body_lines = body_lines[1:]
    prompt_text = "\n".join(body_lines).strip()
    if not prompt_text:
        raise SystemExit(f"{path} has no prompt body.")
    return name, prompt_text


def build_prompt_entry(prompt_id: str, directory: str) -> dict[str, str]:
    name, prompt_text = read_prompt_markdown(PROMPT_LIBRARY / directory / f"{prompt_id}.md")
    return {"id": prompt_id, "name": name, "prompt": prompt_text}


def main() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config["saved_prompts"] = [build_prompt_entry(prompt_id, "default_prompts") for prompt_id in USER_PROMPT_ORDER]
    config["saved_system_prompts"] = [
        build_prompt_entry(prompt_id, "system_prompts") for prompt_id in SYSTEM_PROMPT_ORDER
    ]

    default_prompt = next(item for item in config["saved_prompts"] if item["id"] == "default-prompt")
    default_system_prompt = next(
        item for item in config["saved_system_prompts"] if item["id"] == "default-system-prompt"
    )
    config["prompt_template"] = default_prompt["prompt"]
    config["system_prompt"] = default_system_prompt["prompt"]

    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
