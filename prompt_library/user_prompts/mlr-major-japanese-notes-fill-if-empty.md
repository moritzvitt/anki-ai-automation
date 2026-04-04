# MLR Major Japanese Notes Fill If Empty

You are preparing content for the "Japanese Notes" field of a Japanese Anki card that was audited as fixable major.

Fields:
Cloze: {{Cloze}}
Lemma: {{Lemma}}
Japanese Notes: {{Japanese Notes}}
Notes: {{Notes}}
Grammar: {{Grammar}}
AI Audit Status: {{AI Audit Status}}
AI Audit Summary: {{AI Audit Summary}}
AI Fields To Update: {{AI Fields To Update}}

Task:
Write a concise "Japanese Notes" field only when the current `Japanese Notes` field is empty.

Rules:
- If `AI Audit Status` is not `FIXABLE_MAJOR`, make no changes.
- If `AI Fields To Update` does not mention `Japanese Notes`, make no changes.
- If the current `Japanese Notes` field is not empty, make no changes.
- Do not rewrite Cloze or Lemma.
- Treat this as a cautious support-field draft for a card that still needs manual review.
- Focus on nuance, usage, or context that helps the learner despite the card's major issue.
- Keep the result concise and avoid duplicating `Notes` or `Grammar`.

Output ONLY the updated "Japanese Notes" field content.
