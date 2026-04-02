# MLR Card Quality Check

You are evaluating an Anki card for efficient learning (intermediate Japanese learner).

Note Type: Moritz Language Reactor

Fields:
Cloze: {{Cloze}}
Lemma: {{Lemma}}
Subtitle: {{Subtitle}}
Japanese Notes: {{Japanese Notes}}
Word Definition: {{Word Definition}}
Notes: {{Notes}}

Tasks:
1. Classify the card:
   - GOOD -> ready to learn
   - FIX -> small improvements needed
   - BAD -> should not be learned

2. Check specifically:
   - Is the cloze deletion meaningful and unambiguous?
   - Is Lemma correct and useful?
   - Is the sentence (Subtitle) natural and informative?
   - Is there unnecessary or missing info?
   - Is the card testing ONE clear thing?

3. If FIX or BAD:
   - give short reason
   - suggest concrete fixes

4. If possible, provide an improved version of:
   - Cloze
   - Subtitle

Output format:
Quality: ...
Reason: ...
Suggestions:
- ...
Improved Cloze: ...
Improved Subtitle: ...
