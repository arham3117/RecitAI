"""API response schemas (spec §12).

**The answer-leak boundary.** Spec §4.2 stores options as a JSON blob on `questions`,
with correctness carried by `is_correct` inside it and the rationale by `why_wrong`.
There is no separate column, so `GET /quizzes/{id}` must strip both before serving —
and if it ever fails to, every answer is visible in the network tab while the UI looks
perfectly normal. The failure is invisible and total (plan/ISSUES.md I-010).

So the public shape is a type, not a convention: `PublicOption` has no field capable of
carrying `is_correct` or `why_wrong`. Serving a leaked option is a type error rather than
a review miss, and `model_config = ConfigDict(extra="forbid")` means an extra key raises
instead of passing through.
"""

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PublicOption(BaseModel):
    """An option as the student sees it before answering. No correctness, no rationale."""

    model_config = ConfigDict(extra="forbid")

    id: Literal["A", "B", "C", "D"]
    text: str


class PublicQuestion(BaseModel):
    """A question as served by `GET /quizzes/{id}` — deliberately missing the answer."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    stem: str
    options: list[PublicOption]
    difficulty: str | None = None
    page_refs: list[int] = Field(default_factory=list)
    section_path: list[str] = Field(default_factory=list)


class PublicQuiz(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    course_id: uuid.UUID
    question_count: int
    difficulty: str | None = None
    questions: list[PublicQuestion] = Field(default_factory=list)


def to_public_question(
    question_id: uuid.UUID,
    stem: str,
    options: list[dict[str, Any]],
    *,
    difficulty: str | None = None,
    page_refs: list[int] | None = None,
    section_path: list[str] | None = None,
) -> PublicQuestion:
    """Project a stored question into its public shape.

    Only `id` and `text` are read from each stored option. Anything else — including a
    field added to the stored blob later — is dropped here rather than forwarded.
    """
    return PublicQuestion(
        id=question_id,
        stem=stem,
        options=[PublicOption(id=o["id"], text=o["text"]) for o in options],
        difficulty=difficulty,
        page_refs=list(page_refs or []),
        section_path=list(section_path or []),
    )
