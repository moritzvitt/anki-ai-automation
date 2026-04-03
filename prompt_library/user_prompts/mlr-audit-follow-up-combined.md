# MLR Audit Follow-up Combined

# MLR Audit Follow-up Combined

You are improving the support fields of a Japanese Anki card after an audit marked it as fixable with minor changes.

Fields:
Cloze: {{Cloze}}
Lemma: {{Lemma}}
Subtitle: {{Subtitle}}
Word Definition: {{Word Definition}}
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
- Word Definition
- Grammar

Rules:
- Use `AI Fields To Update` as the primary guide for which fields to touch.
- Do not rewrite Cloze, Lemma, or Subtitle.
- Do not include fields that do not need a change.
- Keep each updated field concise and useful.
- Avoid duplicating the same explanation across fields.

Output format:
--{Japanese Notes}--
...

--{Notes}--
...

--{Word Definition}--
...

--{Grammar}--
...

Only include field blocks for fields you are actually changing.
