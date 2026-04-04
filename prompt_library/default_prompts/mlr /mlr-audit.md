# MLR Audit

Review this Japanese Anki card for study quality.

Your task is strictly diagnostic and routing-only.
Do NOT rewrite, suggest rewrites, or generate field content.

Classify the card into exactly one category:
- GOOD
- FIXABLE_MINOR
- FIXABLE_MAJOR
- REJECT
- SKIP

Evaluation criteria:
1. Clear and testable learning focus (single word/structure/point)
2. Natural, correct, and comprehensible Japanese
3. Effective cloze design: Sentence with a hidden japanese words and a hint in german or english (unambiguous, not trivial, not overly broad)
4. Accurate and useful meaning/explanations
5. Appropriate information density (no overload or missing essentials)
6. No critical errors or misleading content

Decision rules:
- GOOD:
  Fully study-ready. No meaningful issues.

- FIXABLE_MINOR:
  Core card (Cloze) is valid.
  Only supporting fields (Japanese Notes, Notes, Grammar) need small corrections, clarifications, or additions.

- FIXABLE_MAJOR:
  Issues affect core learning quality (e.g. unclear cloze, awkward/unreliable sentence, missing key context).
  Card may be repairable, but not safely through limited or automated support-field edits.

- REJECT:
  Fundamentally unsuitable for study (e.g. incorrect Japanese, misleading meaning, broken cloze, no clear learning target).

- SKIP:
  Cannot be reliably evaluated (e.g. missing critical data, ambiguous structure, or outside scope).

Field update constraints:
- Only include fields in `fields_to_update` if classification is FIXABLE_MINOR.
- Allowed fields: Japanese Notes, Notes, Grammar.
- Do NOT include Cloze, Lemma, or Subtitle.
- Prefer minimal intervention.

Card fields:
Cloze: {{Cloze}}
Lemma: {{Lemma}}
Subtitle: {{Subtitle}}
Japanese Notes: {{Japanese Notes}}
Notes: {{Notes}}
Grammar: {{Grammar}}
