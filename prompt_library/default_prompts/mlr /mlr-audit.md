# MLR Audit Moritz  03.04 (04699f4ac6f2)

Review this Japanese Anki card for study quality.

Your task is strictly diagnostic and routing-only.
Do NOT rewrite, suggest rewrites, or generate field content.

Classify the card into exactly one category:
- GOOD
- FIXABLE_MINOR
- FIXABLE_MAJOR
- REJECT
- SKIP

Cloze format definition:
- The Cloze field uses standard Anki cloze syntax:
  {{c1::expression::hint}}
- "expression" is the hidden Japanese word or phrase being tested.
- "hint" is optional, typically a short meaning (e.g. German or English), e.g.:
  {{c1::屋根::Dach, Hausdach}}
- The cloze should appear inside a Japanese sentence.
- The tested element should represent a clear, single learning target.

Evaluation criteria:
1. Clear and testable learning focus (single word/structure/point)
2. Correct and sufficiently comprehensible Japanese sentence (minor unnaturalness is acceptable)
3. Effective cloze design:
   - correct cloze syntax
   - exactly one meaningful target (avoid multiple competing clozes)
   - hint is helpful but not overly revealing
   - not trivial or overly broad
4. Accurate and useful meaning/explanations
5. Appropriate information density (no overload or missing essentials)
6. No critical errors or misleading content

Note on sentence naturalness:
- The sentence may sound slightly unnatural or context-reduced.
- This is acceptable as long as the meaning is still clear and understandable without excessive guessing.
- Do NOT penalize minor awkwardness or lack of broader context.
- Only treat it as an issue if the sentence is confusing, misleading, or hard to interpret.

Decision rules:
- GOOD:
  Fully study-ready. No meaningful issues.

- FIXABLE_MINOR:
  Core card (Cloze) is valid.
  Only supporting fields (Japanese Notes, Notes, Grammar) need small corrections, clarifications, or additions.

- FIXABLE_MAJOR:
  Issues affect core learning quality (e.g. broken/invalid cloze syntax, unclear target, confusing sentence).
  Card may be repairable, but not safely through limited or automated support-field edits.

- REJECT:
  Fundamentally unsuitable for study (e.g. incorrect Japanese, misleading meaning, invalid cloze, no clear learning target).

- SKIP:
  Cannot be reliably evaluated (e.g. missing critical data, ambiguous structure, or outside scope).

- If the sentence is slightly unnatural but still clearly understandable, do NOT escalate to FIXABLE_MAJOR or REJECT.

Field update constraints:
- Only include fields in `fields_to_update` if classification is FIXABLE_MINOR.
- Allowed fields: Japanese Notes, Notes, Grammar.
- Do NOT include Cloze, Lemma, or Subtitle.
- Prefer minimal intervention.

Output requirements:
- Return JSON only (no prose outside JSON).
- Be deterministic and consistent across similar inputs.
- When uncertain between two categories, choose the more conservative (worse) classification.

Card fields:
Cloze: {{Cloze}}
Lemma: {{Lemma}}
Japanese Notes: {{Japanese Notes}}
Notes: {{Notes}}
Grammar: {{Grammar}}
