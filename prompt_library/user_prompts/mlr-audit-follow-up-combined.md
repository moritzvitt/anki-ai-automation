# MLR Audit Follow-up Combined

You are improving the support fields of a Japanese Anki card after an audit marked it as fixable with minor changes.

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
Update only the support fields that actually need improvement.

Possible fields to update:
- Japanese Notes
- Notes
- Grammar

Rules:
- Use `AI Fields To Update` as the primary guide for which fields to touch.
- If `AI Audit Status` is not `FIXABLE_MINOR`, make no changes.
- Do not rewrite Cloze or Lemma.
- Do not include fields that do not need a change.
- Keep each updated field concise and useful.
- Avoid duplicating the same explanation across fields.

Output format:
--{Japanese Notes}--
...

--{Notes}--
...

--{Grammar}--
...

Only include field blocks for fields you are actually changing.
