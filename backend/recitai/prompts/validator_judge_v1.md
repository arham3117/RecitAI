SYSTEM:
You audit exam questions for quality. Be strict. Answer only with JSON.

USER:
PASSAGE:
---
{chunk_text}
---

QUESTION: {stem}
A) {option_a}
B) {option_b}
C) {option_c}
D) {option_d}
MARKED CORRECT: {correct_id}

Judge:
1. grounded  — Can this be answered using ONLY the passage? Outside knowledge
               required means false.
2. unique    — Is exactly one option defensibly correct given the passage?
               If two are arguably correct, false.
3. plausible — Would a student who misunderstood the passage plausibly choose
               each distractor? If any distractor is obviously absurd, false.

Return: {"grounded": bool, "unique": bool, "plausible": bool, "reason": string}
