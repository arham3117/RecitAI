"""Flashcards and spaced repetition (spec §13)."""

import uuid

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from recitai.api.deps import require_course
from recitai.api.jobs import registry
from recitai.db.models import Flashcard
from recitai.db.session import session_scope
from recitai.generation.pipeline import generate_flashcards_for_scope
from recitai.learning.mastery import weak_topics
from recitai.learning.scheduler import deck_stats, due_flashcards, review_flashcard
from recitai.llm.ollama import OllamaClient
from recitai.retrieval.resolver import Scope

log = structlog.get_logger(__name__)
router = APIRouter(tags=["flashcards"])


class FlashcardOut(BaseModel):
    id: uuid.UUID
    front: str
    back: str
    origin: str
    page_refs: list[int] = Field(default_factory=list)
    topic_id: uuid.UUID | None = None


def _out(card: Flashcard) -> FlashcardOut:
    return FlashcardOut(
        id=card.id,
        front=card.front,
        back=card.back,
        origin=card.origin,
        page_refs=list(card.page_refs),
        topic_id=card.topic_id,
    )


@router.get("/courses/{course_id}/flashcards/due", response_model=list[FlashcardOut])
async def get_due(course_id: uuid.UUID, limit: int = 50) -> list[FlashcardOut]:
    await require_course(course_id)
    return [_out(c) for c in await due_flashcards(course_id, limit=limit)]


@router.get("/courses/{course_id}/flashcards", response_model=list[FlashcardOut])
async def list_flashcards(course_id: uuid.UUID) -> list[FlashcardOut]:
    await require_course(course_id)
    async with session_scope() as session:
        cards = (
            await session.execute(
                select(Flashcard)
                .where(Flashcard.course_id == course_id)
                .order_by(Flashcard.created_at.desc())
            )
        ).scalars()
        return [_out(c) for c in cards]


@router.get("/courses/{course_id}/flashcards/stats")
async def stats(course_id: uuid.UUID) -> dict[str, int]:
    """§13 task 5: due today, new, learning, mature."""
    await require_course(course_id)
    return await deck_stats(course_id)


class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=4, description="1 again, 2 hard, 3 good, 4 easy")


@router.post("/flashcards/{flashcard_id}/review")
async def review(flashcard_id: uuid.UUID, payload: ReviewIn) -> dict[str, object]:
    try:
        result = await review_flashcard(flashcard_id, payload.rating)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {
        "due": result.due.isoformat(),
        "interval_days": round(result.interval_days, 4),
        "stability": round(result.stability, 3),
        "difficulty": round(result.difficulty, 3),
        "state": result.state,
        "lapses": result.lapses,
    }


class GenerateCardsIn(BaseModel):
    course_id: uuid.UUID
    chunks: int = Field(default=5, ge=1, le=20)
    max_cards: int = Field(default=3, ge=1, le=5)
    weak_only: bool = Field(
        default=False, description="Only topics with mastery accuracy below 0.6 (§13 task 3)"
    )


async def _generate(payload: GenerateCardsIn, job_id: uuid.UUID) -> None:
    job = registry.get(job_id)
    assert job is not None
    topics = await weak_topics(payload.course_id) if payload.weak_only else []
    if payload.weak_only and not topics:
        job.detail = "no weak topics — nothing to generate"
        return
    client = OllamaClient()
    try:
        written = await generate_flashcards_for_scope(
            Scope(course_id=payload.course_id, topic_ids=topics),
            payload.chunks,
            client,
            max_cards=payload.max_cards,
        )
        job.progress = written
        job.detail = f"{written} cards written"
    finally:
        await client.aclose()


@router.post("/flashcards/generate", status_code=202)
async def generate_cards(payload: GenerateCardsIn) -> dict[str, object]:
    job = registry.create(total=payload.chunks * payload.max_cards)
    registry.spawn(job, _generate(payload, job.id))
    return job.as_dict()
