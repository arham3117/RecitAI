"""Quiz generation pipeline (spec §11 task 7).

Sampler (Path A) → generator → validator → dedup → persist. Chunks are chosen by
`retrieval/sampler.py` and never by vector search (§3.1).
"""

import time
import uuid
from dataclasses import dataclass, field

import structlog
from sqlalchemy import select

from recitai.config import settings
from recitai.constants import GEN_MODEL
from recitai.db.models import Course, Flashcard, Question, Quiz
from recitai.db.session import session_scope
from recitai.generation.dedup import Deduplicator
from recitai.generation.generator import generate_flashcards, generate_question
from recitai.generation.schemas import Difficulty, GeneratedQuestion, ValidatorReport
from recitai.llm.base import LLMClient
from recitai.retrieval.resolver import Scope
from recitai.retrieval.sampler import increment_usage, sample_chunks

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class AcceptedQuestion:
    """A validated question plus the citations the pipeline attached to it (I1)."""

    question: GeneratedQuestion
    source_chunk_ids: list[str]
    page_refs: list[int]
    topic_id: uuid.UUID | None
    report: ValidatorReport | None


@dataclass
class GenerationRun:
    """Aggregate outcome, persisted to `quizzes.generation_meta` (§5.4)."""

    requested: int
    persisted: int = 0
    first_pass_failures: int = 0
    validator_rejections: int = 0
    duplicates_rejected: int = 0
    insufficient_passages: int = 0
    total_attempts: int = 0
    duration_ms: int = 0
    quiz_id: uuid.UUID | None = None
    failure_codes: dict[str, int] = field(default_factory=dict)
    sampler_shortfall: str | None = None
    #: The accepted questions, so --report can print them without a persisted quiz.
    accepted: list["AcceptedQuestion"] = field(default_factory=list)

    @property
    def validator_pass_rate(self) -> float:
        """The number §5.4 asks to be exposed."""
        attempted = self.persisted + self.validator_rejections
        return self.persisted / attempted if attempted else 0.0

    def as_meta(self, prompt_version: str) -> dict[str, object]:
        return {
            "model": GEN_MODEL,
            "question_prompt": settings.question_prompt,
            "judge_prompt": settings.judge_prompt,
            "prompt_version": prompt_version,
            "requested": self.requested,
            "persisted": self.persisted,
            "validator_rejections": self.validator_rejections,
            "validator_pass_rate": round(self.validator_pass_rate, 3),
            "duplicates_rejected": self.duplicates_rejected,
            "insufficient_passages": self.insufficient_passages,
            "failure_codes": self.failure_codes,
            "total_attempts": self.total_attempts,
            "duration_ms": self.duration_ms,
            "sampler_shortfall": self.sampler_shortfall,
        }


async def generate_quiz(
    scope: Scope,
    n: int,
    client: LLMClient,
    *,
    difficulty: Difficulty = "recall",
    seed: int | None = None,
    persist: bool = True,
    run_judge_checks: bool = True,
) -> GenerationRun:
    started = time.perf_counter()
    run = GenerationRun(requested=n)

    async with session_scope() as session:
        course = await session.get(Course, scope.course_id)
        if course is None:
            raise ValueError(f"no course {scope.course_id}")
        course_name = course.name

    # Path A. Oversample so rejected chunks have replacements (§5.3).
    chunks, sampling = await sample_chunks(scope, n, seed=seed)
    run.sampler_shortfall = sampling.shortfall_reason
    if not chunks:
        run.duration_ms = int((time.perf_counter() - started) * 1000)
        return run

    dedup = Deduplicator(client)
    await dedup.prime(scope.course_id)

    accepted: list[AcceptedQuestion] = []
    prompt_version = "v1"

    for chunk in chunks:
        if len(accepted) >= n:
            break
        outcome = await generate_question(
            chunk,
            course_name,
            client,
            difficulty=difficulty,
            run_judge_checks=run_judge_checks,
        )
        run.total_attempts += outcome.attempts
        prompt_version = outcome.prompt_version or prompt_version

        if outcome.report and not outcome.report.passed:
            run.validator_rejections += 1
            for code in outcome.report.deterministic_failures:
                run.failure_codes[code] = run.failure_codes.get(code, 0) + 1
        if outcome.attempts > 1:
            run.first_pass_failures += 1

        if not outcome.ok or outcome.question is None:
            if outcome.skip_reason and "too thin" in outcome.skip_reason:
                run.insufficient_passages += 1
            continue

        is_duplicate, matched = await dedup.check(outcome.question.stem)
        if is_duplicate:
            run.duplicates_rejected += 1
            log.info("pipeline.duplicate", stem=outcome.question.stem[:70], matched=matched)
            continue

        # I1 — never persist content that cannot cite its source.
        if not outcome.source_chunk_ids or not outcome.page_refs:
            raise RuntimeError(
                f"chunk {chunk.chunk_id}: question passed validation without citations — "
                f"invariant I1 violated"
            )
        accepted.append(
            AcceptedQuestion(
                question=outcome.question,
                source_chunk_ids=outcome.source_chunk_ids,
                page_refs=outcome.page_refs,
                topic_id=chunk.topic_id,
                report=outcome.report,
            )
        )

    run.persisted = len(accepted)
    run.accepted = accepted
    run.duration_ms = int((time.perf_counter() - started) * 1000)

    if persist and accepted:
        async with session_scope() as session:
            quiz = Quiz(
                course_id=scope.course_id,
                scope={"topic_ids": [str(t) for t in scope.topic_ids]},
                question_count=len(accepted),
                difficulty=difficulty,
                generation_meta=run.as_meta(prompt_version),
            )
            session.add(quiz)
            await session.flush()
            run.quiz_id = quiz.id
            for index, item in enumerate(accepted):
                session.add(
                    Question(
                        quiz_id=quiz.id,
                        topic_id=item.topic_id,
                        stem=item.question.stem,
                        options=[o.model_dump() for o in item.question.options],
                        explanation=item.question.explanation,
                        source_chunk_ids=item.source_chunk_ids,
                        page_refs=item.page_refs,
                        difficulty=item.question.difficulty,
                        validator_report=item.report.model_dump() if item.report else {},
                        order_index=index,
                    )
                )
        # §3.3 step 4 — only after generation succeeds.
        await increment_usage([c.chunk_id for c in chunks[: len(accepted)]])

    log.info(
        "pipeline.generated",
        requested=n,
        persisted=run.persisted,
        rejected=run.validator_rejections,
        duplicates=run.duplicates_rejected,
        pass_rate=round(run.validator_pass_rate, 3),
        duration_ms=run.duration_ms,
    )
    return run


async def generate_flashcards_for_scope(
    scope: Scope, n_chunks: int, client: LLMClient, *, max_cards: int = 3, seed: int | None = None
) -> int:
    """Flashcards over sampled chunks, same citation guarantee (§11 task 8)."""
    chunks, _ = await sample_chunks(scope, n_chunks, seed=seed)
    written = 0
    for chunk in chunks:
        cards, chunk_ids, pages = await generate_flashcards(chunk, client, max_cards=max_cards)
        if not cards:
            continue
        async with session_scope() as session:
            for card in cards:
                session.add(
                    Flashcard(
                        course_id=scope.course_id,
                        topic_id=chunk.topic_id,
                        front=card.front,
                        back=card.back,
                        source_chunk_ids=chunk_ids,
                        page_refs=pages,
                        origin="generated",
                    )
                )
                written += 1
    return written


async def quiz_questions(quiz_id: uuid.UUID) -> list[Question]:
    async with session_scope() as session:
        return list(
            (
                await session.execute(
                    select(Question)
                    .where(Question.quiz_id == quiz_id)
                    .order_by(Question.order_index)
                )
            )
            .scalars()
            .all()
        )
