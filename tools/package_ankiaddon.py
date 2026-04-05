from __future__ import annotations

from pathlib import Path
import zipfile


REPO_ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_PATH = REPO_ROOT / f"{REPO_ROOT.name}.ankiaddon"
EMPTY_DIR_ENTRIES = ("prompt_library/user_prompts/",)
SKIP_EXACT = {
    ".DS_Store",
    "meta.json",
}
SKIP_TOP_LEVEL_DIRS = {
    ".git",
    ".vscode",
    "__pycache__",
    "user_data",
}
SKIP_DIR_NAMES = {
    "__pycache__",
}
SKIP_SUFFIXES = {
    ".ankiaddon",
    ".pyc",
    ".pyo",
    ".pyd",
}


def should_include(relative_path: Path) -> bool:
    parts = relative_path.parts
    if not parts:
        return False
    if relative_path.as_posix() in SKIP_EXACT:
        return False
    if parts[0] in SKIP_TOP_LEVEL_DIRS:
        return False
    if any(part in SKIP_DIR_NAMES for part in parts):
        return False
    if relative_path.suffix in SKIP_SUFFIXES:
        return False
    if relative_path.as_posix().startswith("prompt_library/user_prompts/"):
        return False
    return True


def iter_files() -> list[Path]:
    files: list[Path] = []
    for path in sorted(REPO_ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative_path = path.relative_to(REPO_ROOT)
        if should_include(relative_path):
            files.append(relative_path)
    return files


def main() -> None:
    if ARCHIVE_PATH.exists():
        ARCHIVE_PATH.unlink()

    with zipfile.ZipFile(ARCHIVE_PATH, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative_path in iter_files():
            archive.write(REPO_ROOT / relative_path, arcname=relative_path.as_posix())
        for entry in EMPTY_DIR_ENTRIES:
            archive.writestr(entry, "")

    print(f"Created {ARCHIVE_PATH.name}")


if __name__ == "__main__":
    main()
