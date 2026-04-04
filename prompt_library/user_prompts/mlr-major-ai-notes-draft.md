# MLR Major AI Notes Draft

You are drafting candidate content for the "AI Notes" field of a Japanese Anki card that was audited as fixable major.

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
Write a concise replacement draft for `Notes` into the `AI Notes` field, but only when the current `Notes` field already contains content.

Rules:
- If `AI Audit Status` is not `FIXABLE_MAJOR`, make no changes.
- If `AI Fields To Update` does not mention `Notes`, make no changes.
- If the current `Notes` field is empty, make no changes.
- Do not rewrite Cloze or Lemma.
- Treat this as a cautious suggestion for manual review, not a final automatic repair.
- Keep the result concise, useful, and non-redundant with `Japanese Notes` or `Grammar`.

Output ONLY the content for the "AI Notes" field.
