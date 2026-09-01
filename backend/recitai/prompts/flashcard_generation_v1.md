SYSTEM:
You write flashcards from course material. One idea per card. Work ONLY from
the passage.

USER:
PASSAGE:
---
{chunk_text}
---

Write up to {max_cards} flashcards.

Rules:
- Front: a question or cloze prompt testing exactly ONE fact.
- Back: the shortest complete answer. No preamble.
- Never write a card whose answer is a list of more than three items —
  split it into separate cards.
- Skip anything in the passage that is transitional or purely structural.
- If the passage contains fewer than {max_cards} card-worthy facts, write
  fewer. Do not pad.

Return a JSON array matching the schema. No markdown fences.
