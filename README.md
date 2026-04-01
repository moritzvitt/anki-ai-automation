# Anki Add-on Starter Repo

A clean starter template for building future Anki add-ons.

This repository is designed to give you the repeatable pieces you usually want at the beginning of an add-on project:

- a minimal runnable add-on skeleton
- manifest and config files
- changelog and release-description docs
- VS Code tasks for validation and packaging
- a lightweight documentation structure

## Included Files

```text
starter-repo/
├── __init__.py
├── addon.py
├── manifest.json
├── config.json
├── config.md
├── CHANGELOG.md
├── LICENSE
├── .gitignore
├── .editorconfig
├── .vscode/
└── docs/
```

## How To Use This Template

1. Rename the folder to your add-on package name.
2. Update [`manifest.json`](./manifest.json) with your package and display name.
3. Replace the sample menu action in [`addon.py`](./addon.py) with your real hooks and behavior.
4. Adjust [`config.json`](./config.json) and [`config.md`](./config.md) to match your add-on settings.
5. Update [`docs/release-description.md`](./docs/release-description.md) before publishing.

## Development Notes

- Anki loads the add-on from the folder root and executes [`__init__.py`](./__init__.py).
- Keep add-on code in small focused modules as the project grows.
- Use the VS Code tasks to validate Python files and package a `.ankiaddon` archive.

## Packaging

The provided VS Code task creates a `.ankiaddon` zip archive named after the repository folder.

If you package manually:

```bash
zip -r starter-repo.ankiaddon . -x './.git/*' './.vscode/*' './__pycache__/*' './.DS_Store'
```

## Docs

- Overview: [`docs/README.md`](./docs/README.md)
- Architecture notes: [`docs/architecture/overview.md`](./docs/architecture/overview.md)
- Release text draft: [`docs/release-description.md`](./docs/release-description.md)

## License

This template includes the MIT License in [`LICENSE`](./LICENSE). Update the copyright line if needed.
