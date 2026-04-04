# MLR Major Grammar Fill If Empty

You are preparing content for the "Grammar" field of a Japanese Anki card that was audited as fixable major.

Fields:
Cloze: {{Cloze}}
Lemma: {{Lemma}}
Grammar: {{Grammar}}
Notes: {{Notes}}
Japanese Notes: {{Japanese Notes}}
AI Audit Status: {{AI Audit Status}}
AI Audit Summary: {{AI Audit Summary}}
AI Fields To Update: {{AI Fields To Update}}

Task:
Write a concise "Grammar" field only when the current `Grammar` field is empty.

Rules:
- If `AI Audit Status` is not `FIXABLE_MAJOR`, make no changes.
- If `AI Fields To Update` does not mention `Grammar`, make no changes.
- If the current `Grammar` field is not empty, make no changes.
- Do not rewrite Cloze or Lemma.
- Treat this as a cautious support-field draft for a card that still needs manual review.
- Focus on the most relevant sentence-specific grammar point only.
- Keep the result concise and avoid generic grammar dumps.

Output ONLY the updated "Grammar" field content.
