from __future__ import annotations

from aqt import mw
from aqt.qt import QAction
from aqt.utils import askUser, showCritical, showInfo

from ..core.audit_flow import sync_audit_fields_from_log
from ..core.config import ConfigError, load_config


def register_audit_sync_menu() -> None:
    if mw is None:
        return

    action = QAction("Backfill AI Audit Fields", mw)
    action.triggered.connect(_backfill_audit_fields)
    mw.form.menuTools.addAction(action)


def _backfill_audit_fields() -> None:
    if mw is None:
        return
    try:
        config = load_config()
    except ConfigError as error:
        showCritical(str(error), parent=mw)
        return

    if not askUser(
        "Backfill the optional AI Audit note fields from the stored audit log?\n\n"
        "This updates only the metadata-style audit fields on notes that already have audit results.",
        parent=mw,
    ):
        return

    result = sync_audit_fields_from_log(config)
    showInfo(
        "\n".join(
            [
                "Backfill AI Audit Fields",
                "",
                f"- Updated notes: {result.updated_notes}",
                f"- Skipped/no field changes: {result.skipped_notes}",
                f"- Missing notes: {result.missing_notes}",
            ]
        ),
        parent=mw,
    )
