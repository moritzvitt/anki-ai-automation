# MLR Japanese Notes Improver

You are refining the "Japanese Notes" field for an intermediate learner.

Fields:
Cloze: {{Cloze}}
Lemma: {{Lemma}}
Japanese Notes: {{Japanese Notes}}
AI Audit Status: {{AI Audit Status}}
AI Audit Summary: {{AI Audit Summary}}
AI Fields To Update: {{AI Fields To Update}}

Task:
Rewrite Japanese Notes only if the audit indicates this field should be updated.

Requirements:
- concise
- focused on nuance and usage
- helpful at B1-B2 level

Include only if relevant:
- nuance vs similar words
- collocations
- register (casual, formal, written, etc.)
- restrictions / common mistakes

Avoid:
- basic explanations
- redundancy
- overlap with Notes or Grammar

Audit-specific rules:
- If `AI Audit Status` is not `FIXABLE_MINOR`, make no changes.
- Use `AI Audit Summary` and `AI Fields To Update` as the main guide.
- Keep the change minimal and targeted.

Output ONLY the updated "Japanese Notes" field content.
