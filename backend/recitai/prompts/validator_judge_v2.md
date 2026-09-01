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
2. unique    — Take each of the three distractors in turn and ask: could a
               careful student defend this option using the passage alone?
               If ANY distractor is also supported by the passage, answer
               false — even if the marked answer is the better of the two.
               Pay particular attention to questions asking for a "primary",
               "main" or "most important" reason when the passage lists
               several without ranking them: those usually have more than one
               defensible answer.
               Also answer false if the marked answer is a number, count or
               quantity that the passage does not state outright.
3. plausible — Would a student who misunderstood the passage plausibly choose
               each distractor? If any distractor is obviously absurd, false.

Return: {"grounded": bool, "unique": bool, "plausible": bool, "reason": string}
