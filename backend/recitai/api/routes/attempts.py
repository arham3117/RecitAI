"""Attempts, grading, and the explanation loop (spec §12).

**The answer-submission response is the product's core moment** (§12). It returns
everything needed to render the explanation with zero further round trips: what the
student chose, why that specific choice was wrong, why the right answer is right, and the
source passage with its page. Anything missing here becomes a spinner at exactly the
moment the student is most likely to give up.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sse_starlette.sse import EventSourceResponse

from recitai.db.models import Answer, Attempt, Chunk, Document, Question, TopicMastery
from recitai.db.session import session_scope
from recitai.generation.prompts import load
from recitai.learning.mastery import promote_missed_question, update_mastery
from recitai.llm.ollama import OllamaClient

log = structlog.get_logger(__name__)
router = APIRouter(tags=["attempts"])


class AttemptIn(BaseModel):
    quiz_id: uuid.UUID


class AttemptOut(BaseModel):
    id: uuid.UUID
    quiz_id: uuid.UUID
    started_at: datetime


@router.post("/attempts", response_model=AttemptOut, status_code=201)
async def start_attempt(payload: AttemptIn) -> AttemptOut:
    async with session_scope() as session:
        attempt = Attempt(quiz_id=payload.quiz_id)
        session.add(attempt)
        await session.flush()
        return AttemptOut(id=attempt.id, quiz_id=attempt.quiz_id, started_at=attempt.started_at)


class AnswerIn(BaseModel):
    question_id: uuid.UUID
    selected_option_id: str | None = None
    time_taken_ms: int | None = None


class SourceOut(BaseModel):
    text: str
    page: int
    section_path: list[str]
    document_name: str


class AnswerOut(BaseModel):
    """§12's payload, verbatim in shape. Everything the explanation panel needs."""

    is_correct: bool
    correct_option_id: str
    selected_option_id: str | None
    why_wrong: str | None
    explanation: str
    source: SourceOut | None


@router.post("/attempts/{attempt_id}/answers", response_model=AnswerOut)
async def submit_answer(attempt_id: uuid.UUID, payload: AnswerIn) -> AnswerOut:
    async with session_scope() as session:
        attempt = await session.get(Attempt, attempt_id)
        if attempt is None:
            raise HTTPException(404, f"no attempt {attempt_id}")
        question = await session.get(Question, payload.question_id)
        if question is None:
            raise HTTPException(404, f"no question {payload.question_id}")

        options = question.options
        correct = next((o for o in options if o.get("is_correct")), None)
        if correct is None:
            # Every persisted question passed the validator's schema check, so this means
            # the row was corrupted after the fact — surface it rather than guess.
            raise HTTPException(500, f"question {question.id} has no correct option")
        chosen = next((o for o in options if o["id"] == payload.selected_option_id), None)
        is_correct = bool(chosen and chosen.get("is_correct"))

        session.add(
            Answer(
                attempt_id=attempt_id,
                question_id=question.id,
                selected_option_id=payload.selected_option_id,
                is_correct=is_correct,
                time_taken_ms=payload.time_taken_ms,
            )
        )
        await update_mastery(session, question, is_correct)

        # §13 task 4: a missed question becomes a flashcard. Done after the answer is
        # recorded so a promotion failure cannot lose the answer itself.
        promoted = None
        if not is_correct:
            promoted = question

        # The source passage, resolved from the question's own citation (§17: always
        # prefer the question's source_chunk_ids over a fresh search).
        source: SourceOut | None = None
        if question.source_chunk_ids:
            chunk = await session.get(Chunk, uuid.UUID(question.source_chunk_ids[0]))
            if chunk is not None:
                document = await session.get(Document, chunk.document_id)
                source = SourceOut(
                    text=chunk.text[:1200],
                    page=question.page_refs[0] if question.page_refs else chunk.page_start,
                    section_path=list(chunk.section_path),
                    document_name=document.filename if document else "unknown",
                )

        response = AnswerOut(
            is_correct=is_correct,
            correct_option_id=str(correct["id"]),
            selected_option_id=payload.selected_option_id,
            why_wrong=None if is_correct else (chosen or {}).get("why_wrong"),
            explanation=question.explanation,
            source=source,
        )

    # Promoted after the answer transaction commits, so a promotion failure can never
    # lose the answer itself (§13 task 4).
    if promoted is not None:
        await promote_missed_question(promoted)
    return response


@router.get("/attempts/{attempt_id}/results")
async def attempt_results(attempt_id: uuid.UUID) -> dict[str, object]:
    async with session_scope() as session:
        attempt = await session.get(Attempt, attempt_id)
        if attempt is None:
            raise HTTPException(404, f"no attempt {attempt_id}")
        answers = list(
            (await session.execute(select(Answer).where(Answer.attempt_id == attempt_id)))
            .scalars()
            .all()
        )
        correct = sum(1 for a in answers if a.is_correct)
        score = correct / len(answers) if answers else 0.0

        attempt.completed_at = datetime.now(UTC)
        attempt.score = score

        # Per-topic breakdown (§12), from the questions actually answered.
        by_topic: dict[str, dict[str, int]] = {}
        for answer in answers:
            question = await session.get(Question, answer.question_id)
            if question is None or question.topic_id is None:
                continue
            key = str(question.topic_id)
            bucket = by_topic.setdefault(key, {"answered": 0, "correct": 0})
            bucket["answered"] += 1
            bucket["correct"] += 1 if answer.is_correct else 0

        return {
            "attempt_id": str(attempt_id),
            "answered": len(answers),
            "correct": correct,
            "score": round(score, 3),
            "per_topic": by_topic,
        }


class FollowUpIn(BaseModel):
    followup: str


@router.post("/questions/{question_id}/explain")
async def explain(question_id: uuid.UUID, payload: FollowUpIn) -> EventSourceResponse:
    """Streamed follow-up (§12, §6.3).

    The student's specific misconception is passed into the prompt — that is what makes
    this better than a generic re-explanation (§6.3).
    """
    async with session_scope() as session:
        question = await session.get(Question, question_id)
        if question is None:
            raise HTTPException(404, f"no question {question_id}")
        options = question.options
        correct = next((o for o in options if o.get("is_correct")), {})
        wrong = next((o for o in options if not o.get("is_correct")), {})
        chunk = (
            await session.get(Chunk, uuid.UUID(question.source_chunk_ids[0]))
            if question.source_chunk_ids
            else None
        )
        stem, explanation = question.stem, question.explanation
        pages = question.page_refs

    prompt = load("explanation_followup_v1")
    rendered = prompt.render(
        section_path=" > ".join(chunk.section_path) if chunk else "",
        page=pages[0] if pages else "?",
        chunk_text=chunk.text if chunk else explanation,
        stem=stem,
        chosen_option_text=wrong.get("text", ""),
        why_wrong=wrong.get("why_wrong", ""),
        correct_option_text=correct.get("text", ""),
        followup=payload.followup,
    )

    async def stream() -> AsyncIterator[dict[str, str]]:
        client = OllamaClient()
        try:
            async for piece in client.stream(rendered, system=prompt.system):
                yield {"data": piece}
            yield {"event": "done", "data": ""}
        finally:
            await client.aclose()

    return EventSourceResponse(stream())


@router.get("/courses/{course_id}/mastery")
async def course_mastery(course_id: uuid.UUID) -> list[dict[str, object]]:
    async with session_scope() as session:
        rows = (
            await session.execute(select(TopicMastery).where(TopicMastery.course_id == course_id))
        ).scalars()
        return [
            {
                "topic_id": str(m.topic_id),
                "attempts": m.attempts_count,
                "correct": m.correct_count,
                "accuracy": m.accuracy,
            }
            for m in rows
        ]


@router.get("/health")
async def health() -> dict[str, object]:
    async with session_scope() as session:
        chunks = await session.scalar(select(func.count()).select_from(Chunk))
    return {"status": "ok", "chunks": int(chunks or 0)}
