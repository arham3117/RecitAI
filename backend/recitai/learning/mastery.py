"""Topic mastery and the missed-question bridge (spec §13 tasks 3–4)."""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recitai.db.models import Flashcard, Question, Quiz, TopicMastery
from recitai.db.session import session_scope

log = structlog.get_logger(__name__)

#: §13 task 3: below this accuracy a topic gets extra cards generated for it.
WEAK_TOPIC_ACCURACY = 0.6


async def update_mastery(session: AsyncSession, question: Question, is_correct: bool) -> None:
    """Denormalised rollup, updated on every answer (§4.2).

    Feeds the sampler's `weakness` term, so a topic the student is failing gets up to
    double allocation next time. Never recomputed from `answers` at query time.
    """
    if question.topic_id is None:
        return
    quiz = await session.get(Quiz, question.quiz_id)
    if quiz is None:
        return
    mastery = await session.scalar(
        select(TopicMastery).where(
            TopicMastery.course_id == quiz.course_id,
            TopicMastery.topic_id == question.topic_id,
        )
    )
    if mastery is None:
        # Column defaults apply at flush, so a freshly constructed row has None here.
        mastery = TopicMastery(
            course_id=quiz.course_id,
            topic_id=question.topic_id,
            attempts_count=0,
            correct_count=0,
        )
        session.add(mastery)
    mastery.attempts_count = (mastery.attempts_count or 0) + 1
    mastery.correct_count = (mastery.correct_count or 0) + (1 if is_correct else 0)
    mastery.accuracy = mastery.correct_count / mastery.attempts_count
    mastery.last_practiced_at = datetime.now(UTC)


async def promote_missed_question(question: Question) -> uuid.UUID | None:
    """Turn a missed question into a flashcard (§13 task 4).

    This is the bridge between the two halves of the product and §13 calls it the
    strongest learning mechanic in it — so it is built deliberately rather than as an
    afterthought.

    The card carries the question's own citations, so invariant I1 survives the promotion:
    a card promoted from a question can still be traced to the slide it came from.

    Idempotent: answering the same question wrongly twice does not create two cards.
    """
    async with session_scope() as session:
        quiz = await session.get(Quiz, question.quiz_id)
        if quiz is None:
            return None
        existing = await session.scalar(
            select(Flashcard).where(
                Flashcard.course_id == quiz.course_id,
                Flashcard.front == question.stem,
                Flashcard.origin == "missed_question",
            )
        )
        if existing is not None:
            return existing.id

        correct = next((o for o in question.options if o.get("is_correct")), None)
        if correct is None or not question.source_chunk_ids:
            # I1: a card that cannot cite its source is not persisted.
            return None

        card = Flashcard(
            course_id=quiz.course_id,
            topic_id=question.topic_id,
            front=question.stem,
            back=str(correct["text"]),
            source_chunk_ids=list(question.source_chunk_ids),
            page_refs=list(question.page_refs),
            origin="missed_question",
        )
        session.add(card)
        await session.flush()
        log.info("mastery.promoted_missed_question", flashcard_id=str(card.id))
        return card.id


async def weak_topics(course_id: uuid.UUID) -> list[uuid.UUID]:
    """Topics the student is failing (§13 task 3)."""
    async with session_scope() as session:
        rows = (
            await session.execute(select(TopicMastery).where(TopicMastery.course_id == course_id))
        ).scalars()
        return [
            m.topic_id for m in rows if m.accuracy is not None and m.accuracy < WEAK_TOPIC_ACCURACY
        ]
