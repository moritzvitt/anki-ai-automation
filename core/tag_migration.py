from __future__ import annotations

from dataclasses import dataclass

from aqt import mw


LEGACY_AI_TAG_MAP: dict[str, str] = {
    "ai_good": "ai::audit::good",
    "ai_fix_minor": "ai::audit::fix_minor",
    "ai_fix_major": "ai::audit::fix_major",
    "ai_reject": "ai::audit::reject",
    "ai_skip": "ai::audit::skip",
    "ai_checked": "ai::audit::checked",
    "ai_manual_review": "ai::review::manual",
    "ai_done_today": "ai::audit::processed",
    "ai::audit::done_today": "ai::audit::processed",
    "ai_audit_failed": "ai::audit::failed",
    "ai_fixed_minor": "ai::fix::minor",
    "ai_fixed_japanese_notes": "ai::fix::japanese_notes",
    "ai_fixed_notes": "ai::fix::notes",
    "ai_fixed_word_definition": "ai::fix::word_definition",
    "ai_fixed_grammar": "ai::fix::grammar",
    "ai_fixed_combined": "ai::fix::combined",
    "ai_fix_failed": "ai::fix::failed",
    "ai_fix_failed_japanese_notes": "ai::fix::failed::japanese_notes",
    "ai_fix_failed_notes": "ai::fix::failed::notes",
    "ai_fix_failed_word_definition": "ai::fix::failed::word_definition",
    "ai_fix_failed_grammar": "ai::fix::failed::grammar",
    "ai_fix_failed_combined": "ai::fix::failed::combined",
    "mark": "ai::review::mark",
}


@dataclass(frozen=True)
class TagMigrationResult:
    scanned_notes: int
    updated_notes: int
    replaced_tags: int


def migrate_legacy_ai_tags() -> TagMigrationResult:
    if mw is None or mw.col is None:
        raise RuntimeError("Anki collection is not available.")

    note_ids: set[int] = set()
    for legacy_tag in LEGACY_AI_TAG_MAP:
        note_ids.update(int(note_id) for note_id in mw.col.find_notes(f"tag:{legacy_tag}"))

    changed_notes = []
    replaced_tags = 0
    for note_id in sorted(note_ids):
        note = mw.col.get_note(note_id)
        if note is None:
            continue
        changed = False
        for legacy_tag, new_tag in LEGACY_AI_TAG_MAP.items():
            if not note.has_tag(legacy_tag):
                continue
            if not note.has_tag(new_tag):
                note.add_tag(new_tag)
            note.remove_tag(legacy_tag)
            replaced_tags += 1
            changed = True
        if changed:
            changed_notes.append(note)

    if changed_notes:
        if hasattr(mw.col, "update_notes"):
            mw.col.update_notes(changed_notes)
        else:
            for note in changed_notes:
                mw.col.update_note(note)

    return TagMigrationResult(
        scanned_notes=len(note_ids),
        updated_notes=len(changed_notes),
        replaced_tags=replaced_tags,
    )
