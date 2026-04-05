# MLR Major Notes Fill If Empty

You are preparing content for the "Notes" field of a Japanese Anki card that was audited as fixable major.

Fields:
Cloze: {{Cloze}}
Lemma: {{Lemma}}
Notes: {{Notes}}
Japanese Notes: {{Japanese Notes}}
Grammar: {{Grammar}}
AI Audit Status: {{AI Audit Status}}
AI Audit Summary: {{AI Audit Summary}}
AI Fields To Update: {{AI Fields To Update}}

Task:
Write a concise "Notes" field only when the current `Notes` field is empty.

Rules:
- If `AI Audit Status` is not `FIXABLE_MAJOR`, make no changes.
- If `AI Fields To Update` does not mention `Notes`, make no changes.
- If the current `Notes` field is not empty, make no changes.
- Do not rewrite Cloze or Lemma.
- Treat this as a cautious support-field draft for a card that still needs manual review.
- Keep the result concise, useful, and non-redundant with `Japanese Notes` or `Grammar`.

Output ONLY the updated "Notes" field content.
