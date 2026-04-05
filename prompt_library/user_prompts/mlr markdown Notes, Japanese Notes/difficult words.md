# difficult words

„Analysiere den Text „{{Cloze}}“ und extrahiere alle schwierigen oder potenziell unbekannten Wörter. Antworte auf Deutsch.“

**Ausgabeformat (streng einhalten):**
- **Keine Überschrift**
- Genau eine Markdown-Liste
- Jeder Listenpunkt beginnt mit `- ` (Bindestrich + Leerzeichen)
- Kein anderer Text vor oder nach der Liste

**Format pro Eintrag:**
- `Wort[ふりがな]: Bedeutung`
- Furigana in **Hiragana** und in `[]` direkt nach dem jeweiligen Kanji
- Wenn ein Wort Kanji und Okurigana enthält, gib Furigana **nur für die Kanji** an  
  (z. B. 激しい → 激[はげ]しい)
- Wenn Kanji und Okurigana gemischt sind, setze Furigana **nach jedes einzelne Kanji**  
  (z. B. 向き合う → 向[む]き合[あ]う)
- Bei Wörtern mit mehreren Kanji ohne Okurigana: Furigana pro Kanji oder als Block, je nach Lesung  
  (z. B. 情[じょう]報[ほう] oder 情報[じょうほう])
- Falls kein Kanji vorhanden ist, **keine Furigana**

**Zusätzliche Regeln:**
- Keine vollständigen Sätze
- Nur Stichpunkte
- Nur relevante, eher schwierige Wörter (keine sehr einfachen Wörter)
- Kurze, präzise Bedeutungen
- Maximal 5 Einträge
