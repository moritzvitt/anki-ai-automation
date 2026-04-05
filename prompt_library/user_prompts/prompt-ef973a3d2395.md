# audit moritz

Review this Japanese Anki card for study quality.

Your task is diagnostic and routing-first.  
Only generate field content if explicitly allowed below.

Classify the card into exactly one category:
- GOOD
- FIXABLE_MINOR
- FIXABLE_MAJOR
- REJECT
- SKIP

---

## Cloze format definition

- The Cloze field uses standard Anki cloze syntax:  
  `{{c1::expression::hint}}`
- "expression" is the hidden Japanese word or phrase being tested.
- "hint" is optional, typically a short meaning in English or German.
- Example:  
  `{{c1::屋根::Dach, Hausdach}}`
- The cloze should appear inside a Japanese sentence.
- The tested element should represent a clear, single learning target.

---

## Evaluation criteria

1. Clear and testable learning focus  
2. Correct and sufficiently comprehensible Japanese sentence (minor unnaturalness is acceptable)  
3. Effective cloze design  
4. Accurate and useful meaning/explanations  
5. Appropriate information density  
6. No critical errors or misleading content  

---

## Note on sentence naturalness

- The sentence may sound slightly unnatural or context-reduced.  
- This is acceptable as long as the meaning is still clear and understandable without excessive guessing.  
- Do NOT penalize minor awkwardness or lack of broader context.  
- Only treat it as an issue if the sentence is confusing, misleading, or hard to interpret.  

---

## Decision rules

- **GOOD**  
  Fully study-ready. No meaningful issues.

- **FIXABLE_MINOR**  
  Core card (Cloze) is valid.  
  Only supporting fields need small corrections, clarifications, or additions.

- **FIXABLE_MAJOR**  
  Issues affect core learning quality, but the card may still be repairable.

- **REJECT**  
  Fundamentally unsuitable for study.

- **SKIP**  
  Cannot be reliably evaluated.

---

## Field update constraints

- Only list fields in **"AI Fields To Update"** if classification is **FIXABLE_MINOR**.  
- Allowed fields: **Japanese Notes, Notes, Grammar**  
- Do NOT include Cloze, Lemma, or Subtitle.  
- Prefer minimal intervention.  
- If no supporting fields should be changed, output `NONE`.  

---

## Generation rules

- ONLY if classification is **FIXABLE_MINOR** or **FIXABLE_MAJOR**:
  - You may provide improved full content for the fields listed in **"AI Fields To Update"**.

- Otherwise (**GOOD, REJECT, SKIP**):
  - Do NOT generate any field content.
  - Leave all improvement fields EMPTY.

- If classification is **FIXABLE_MINOR**:
  - Allowed fields: Japanese Notes, Notes, Grammar

- If classification is **FIXABLE_MAJOR**:
  - Allowed fields: Cloze, Japanese Notes, Notes, Grammar

- If a field is listed in **"AI Fields To Update"**, its corresponding output field MUST be filled.  
- If a field is NOT listed, its output field MUST be empty.  

- If classification is NOT **FIXABLE_MINOR** or **FIXABLE_MAJOR**:
  - "AI Fields To Update" MUST be `NONE`

---

## Cloze modification formatting rule

- This rule applies ONLY if:
  - classification is **FIXABLE_MAJOR**, AND
  - "Cloze" is included in **AI Fields To Update**

- The output in **--AI Cloze--** must contain the FULL corrected cloze sentence.

- ONLY the parts that were changed compared to the original Cloze must be wrapped in italics using single asterisks:
  *example*

- Do NOT italicize unchanged parts.

- Do NOT rewrite the entire sentence unless necessary.

- If the cloze structure itself is changed (e.g. different expression or hint), only the modified segment inside the cloze should be italicized.

Example:

Original:
今日は{{c1::屋根::Dach}}に登った。

Corrected:
今日は{{c1::*屋上*::Dach}}に登った。

- If no Cloze changes are required, the **--AI Cloze--** field must be empty.

---

## Cloze modification principles

- When modifying the Cloze, preserve the original sentence structure as much as possible.
- Prefer minimal edits:
  - First try to fix only the cloze expression or hint.
  - Avoid rewriting the full sentence unless absolutely necessary.
- Do NOT change word order, grammar, or surrounding context unless required to make the sentence correct or understandable.
- The goal is to repair the card, not to improve style.

- If a valid fix is possible with a small local change, do NOT perform a larger rewrite.

---

## Output format rules

- Output exactly and only the following field blocks.  
- Do not add any extra text.  
- Do not use markdown or code fences in the output.  
- Use the field labels exactly as written.  

---

## Required output format

--AI Audit Status--  
[GOOD | FIXABLE_MINOR | FIXABLE_MAJOR | REJECT | SKIP]

--AI Audit Summary--  
[1–3 concise sentences explaining the classification]

--AI Fields To Update--  
[NONE or a newline-separated list using only: Japanese Notes, Notes, Grammar]

--AI Cloze--

--AI Japanese Notes--

--AI Grammar--

---

## Card fields

Cloze: {{Cloze}}  
Lemma: {{Lemma}}  
Japanese Notes: {{Japanese Notes}}  
Notes: {{Notes}}  
Grammar: {{Grammar}}