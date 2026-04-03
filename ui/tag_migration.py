from __future__ import annotations

from aqt import mw
from aqt.operations import QueryOp
from aqt.qt import QAction
from aqt.utils import askUser, showCritical, showInfo

from ..core.tag_migration import LEGACY_AI_TAG_MAP, TagMigrationResult, migrate_legacy_ai_tags


def register_tag_migration_menu() -> None:
    if mw is None:
        return

    action = QAction("Migrate Legacy AI Tags", mw)
    action.triggered.connect(_migrate_legacy_tags)
    mw.form.menuTools.addAction(action)


def _migrate_legacy_tags() -> None:
    if mw is None:
        return

    sample_lines = "\n".join(
        f"- {old} -> {new}"
        for old, new in list(LEGACY_AI_TAG_MAP.items())[:8]
    )
    confirmed = askUser(
        "Migrate old AI tags to the new Anki tag-tree format?\n\n"
        "This renames existing tags like:\n"
        f"{sample_lines}\n"
        "\n"
        "The migration is safe to run more than once.",
        parent=mw,
    )
    if not confirmed:
        return

    op = QueryOp(
        parent=mw,
        op=lambda _col: migrate_legacy_ai_tags(),
        success=_on_migration_finished,
    )
    op.with_progress(label="Migrating legacy AI tags...")
    op.run_in_background()


def _on_migration_finished(result: TagMigrationResult) -> None:
    if mw is not None:
        mw.reset()
    showInfo(
        "\n".join(
            [
                "Migrate Legacy AI Tags",
                "",
                f"- Notes scanned: {result.scanned_notes}",
                f"- Notes updated: {result.updated_notes}",
                f"- Legacy tags replaced: {result.replaced_tags}",
            ]
        ),
        parent=mw,
    )
