# MLR Grammar Field Improver

You are improving the "Grammar" field of a Japanese Anki card.

Fields:
Cloze: {{Cloze}}
Lemma: {{Lemma}}
Grammar: {{Grammar}}
Notes: {{Notes}}
AI Audit Status: {{AI Audit Status}}
AI Audit Summary: {{AI Audit Summary}}
AI Fields To Update: {{AI Fields To Update}}

Task:
Identify the most relevant grammar point or structure in the cloze sentence and explain it briefly and accurately.

Requirements:
- concise
- sentence-specific
- no generic textbook dump
- no duplication of vocabulary notes
- mention the exact form used in the sentence when helpful

Audit-specific rules:
- If `AI Audit Status` is not `FIXABLE_MINOR`, make no changes.
- Use `AI Audit Summary` and `AI Fields To Update` as the main guide.
- Keep the fix minimal and focused on the grammar issue actually identified by the audit.

Output ONLY the updated "Grammar" field content.
