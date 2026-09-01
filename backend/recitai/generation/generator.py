"""Question generation with the regeneration loop (spec §11, §5.3).

The pipeline attaches `source_chunk_ids` and `page_refs` from the sampler's records —
never from model output (§4.5, invariant I1). A question that cannot cite its source is
not persisted.
"""

import time
import uuid
from dataclasses import dataclass, field

import structlog
from pydantic import ValidationError

from recitai.constants import GEN_TEMPERATURE, MAX_REGEN_ATTEMPTS
from recitai.generation.prompts import load
from recitai.generation.schemas import (
    Difficulty,
    FlashcardBatch,
    GeneratedFlashcard,
    GeneratedQuestion,
    ValidatorReport,
)
from recitai.generation.validator import validate
from recitai.llm.base import LLMClient
from recitai.retrieval.sampler import ChunkRef

log = structlog.get_logger(__name__)

QUESTION_PROMPT = "question_generation_v1"
FLASHCARD_PROMPT = "flashcard_generation_v1"


@dataclass
class GenerationOutcome:
    """One chunk's result. `question` is None when nothing usable was produced."""

    chunk: ChunkRef
    question: GeneratedQuestion | None
    report: ValidatorReport | None
    source_chunk_ids: list[str] = field(default_factory=list)
    page_refs: list[int] = field(default_factory=list)
    attempts: int = 0
    duration_ms: int = 0
    skip_reason: str | None = None
    prompt_version: str = ""

    @property
    def ok(self) -> bool:
        return self.question is not None


def _is_insufficient(raw: str) -> bool:
    """§6.1's escape hatch: a passage too thin to support a question.

    Generating nothing is the correct outcome here (I2), so this is a signal to move on,
    not an error.
    """
    stripped = raw.strip().lower()
    return '"insufficient"' in stripped and "true" in stripped


async def generate_question(
    chunk: ChunkRef,
    course_name: str,
    client: LLMClient,
    *,
    difficulty: Difficulty = "recall",
    max_attempts: int = MAX_REGEN_ATTEMPTS,
    run_judge_checks: bool = True,
) -> GenerationOutcome:
    """Generate one validated question from one chunk, retrying per §5.3."""
    prompt = load(QUESTION_PROMPT)
    started = time.perf_counter()
    outcome = GenerationOutcome(
        chunk=chunk, question=None, report=None, prompt_version=prompt.version
    )

    base = prompt.render(
        course_name=course_name,
        section_path=" > ".join(chunk.section_path),
        difficulty=difficulty,
        chunk_text=chunk.text,
    )
    feedback = ""

    for attempt in range(1, max_attempts + 1):
        outcome.attempts = attempt
        raw = await client.complete(
            base + feedback,
            system=prompt.system,
            temperature=GEN_TEMPERATURE,
            schema=GeneratedQuestion.model_json_schema(),
        )

        if _is_insufficient(raw):
            outcome.skip_reason = "model reported the passage is too thin for a question"
            break

        try:
            question = GeneratedQuestion.model_validate_json(raw)
        except ValidationError as exc:
            # §4.4: retry once with the error text appended, then fail the chunk.
            feedback = f"\n\nYour previous output was invalid: {exc}\nReturn valid JSON."
            outcome.skip_reason = f"schema validation failed: {exc}"
            continue

        report = await validate(
            question, chunk.text, client, attempt=attempt, run_judge_checks=run_judge_checks
        )
        outcome.report = report

        if report.passed:
            outcome.question = question
            outcome.skip_reason = None
            # I1: citations come from the sampler's record of where the text came from.
            outcome.source_chunk_ids = [str(chunk.chunk_id)]
            outcome.page_refs = list(range(chunk.page_start, chunk.page_end + 1))
            break

        outcome.skip_reason = f"validator rejected: {', '.join(report.deterministic_failures)}"
        feedback = (
            "\n\nYour previous attempt was rejected for: "
            f"{', '.join(report.deterministic_failures)}. Fix these specific problems."
        )

    outcome.duration_ms = int((time.perf_counter() - started) * 1000)
    log.info(
        "generator.question",
        chunk_id=str(chunk.chunk_id),
        ok=outcome.ok,
        attempts=outcome.attempts,
        duration_ms=outcome.duration_ms,
        prompt_version=outcome.prompt_version,
        skip_reason=outcome.skip_reason,
    )
    return outcome


async def generate_flashcards(
    chunk: ChunkRef, client: LLMClient, *, max_cards: int = 3
) -> tuple[list[GeneratedFlashcard], list[str], list[int]]:
    """Flashcards from one chunk, with the same citation guarantee (§11 task 8)."""
    prompt = load(FLASHCARD_PROMPT)
    raw = await client.complete(
        prompt.render(chunk_text=chunk.text, max_cards=max_cards),
        system=prompt.system,
        temperature=GEN_TEMPERATURE,
        schema=FlashcardBatch.model_json_schema(),
    )
    try:
        batch = FlashcardBatch.model_validate_json(raw)
    except ValidationError as exc:
        log.warning("generator.flashcards_invalid", chunk_id=str(chunk.chunk_id), error=str(exc))
        return [], [], []

    cards = batch.cards[:max_cards]
    return (
        cards,
        [str(chunk.chunk_id)],
        list(range(chunk.page_start, chunk.page_end + 1)),
    )


def question_uuid() -> uuid.UUID:
    return uuid.uuid4()
