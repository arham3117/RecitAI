"""Generated content schemas (spec §4.5).

`source_chunk_ids` and `page_refs` are deliberately absent: they are attached by the
pipeline from the sampler's records, never produced by the model. Asked for its own
citations, a model invents page numbers (§4.5).
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Difficulty = Literal["recall", "application", "analysis"]


class GeneratedOption(BaseModel):
    id: Literal["A", "B", "C", "D"]
    text: str
    is_correct: bool
    why_wrong: str | None = None  # required when is_correct is False


class GeneratedQuestion(BaseModel):
    stem: str
    options: list[GeneratedOption] = Field(min_length=4, max_length=4)
    explanation: str
    difficulty: Difficulty

    @field_validator("stem", "explanation")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty or whitespace-only")
        return value

    @model_validator(mode="after")
    def _exactly_one_correct(self) -> "GeneratedQuestion":
        correct = [o for o in self.options if o.is_correct]
        if len(correct) != 1:
            raise ValueError(f"exactly one option must be correct, got {len(correct)}")
        if len({o.id for o in self.options}) != 4:
            raise ValueError("option ids must be A, B, C, D with no duplicates")
        return self

    @property
    def correct(self) -> GeneratedOption:
        return next(o for o in self.options if o.is_correct)

    @property
    def distractors(self) -> list[GeneratedOption]:
        return [o for o in self.options if not o.is_correct]


class InsufficientPassage(BaseModel):
    """The model's escape hatch when a passage is too thin (§6.1).

    Generating nothing is the correct outcome for a passage that cannot support a
    question (invariant I2). This is a signal to move to another chunk, not a failure.
    """

    insufficient: Literal[True]


class JudgeVerdict(BaseModel):
    """§5.2 — all three judgments in one response."""

    grounded: bool
    unique: bool
    plausible: bool
    reason: str = ""

    @property
    def passed(self) -> bool:
        return self.grounded and self.unique and self.plausible


class ValidatorReport(BaseModel):
    """§5.4 — persisted to questions.validator_report."""

    passed: bool
    attempts: int
    deterministic_failures: list[str] = Field(default_factory=list)
    judge_results: dict[str, bool] = Field(default_factory=dict)
    duration_ms: int = 0


class GeneratedFlashcard(BaseModel):
    front: str
    back: str

    @field_validator("front", "back")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty or whitespace-only")
        return value


class FlashcardBatch(BaseModel):
    """Ollama's structured output needs an object at the top level, not a bare array."""

    cards: list[GeneratedFlashcard] = Field(default_factory=list)
