"""Spaced repetition and the missed-question bridge (spec §13 VERIFY)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from recitai.db.models import Chunk, Course, Document, Flashcard, Question, Quiz
from recitai.db.session import session_scope
from recitai.learning.mastery import promote_missed_question
from recitai.learning.scheduler import deck_stats, due_flashcards, review_flashcard

FROZEN = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


async def _services_or_skip() -> None:
    import asyncpg

    from recitai.db.session import engine

    try:
        async with engine.connect():
            return
    except (asyncpg.CannotConnectNowError, ConnectionRefusedError, OSError) as exc:
        pytest.skip(f"postgres not reachable: {exc}")


async def _course_with_card() -> tuple[uuid.UUID, uuid.UUID]:
    async with session_scope() as session:
        course = Course(name=f"fsrs-probe-{uuid.uuid4()}")
        session.add(course)
        await session.flush()
        card = Flashcard(
            course_id=course.id,
            front="What is horizontal fragmentation?",
            back="Splitting a relation by rows using a predicate.",
            source_chunk_ids=[str(uuid.uuid4())],
            page_refs=[9],
            origin="generated",
        )
        session.add(card)
        await session.flush()
        return course.id, card.id


async def _cleanup(course_id: uuid.UUID) -> None:
    async with session_scope() as session:
        course = await session.get(Course, course_id)
        if course is not None:
            await session.delete(course)


@pytest.mark.asyncio
async def test_interval_grows_with_the_rating() -> None:
    """§13 VERIFY: review at each rating 1-4 and assert the scheduled interval changes
    correctly. A harder rating must not schedule a card further out than an easier one."""
    await _services_or_skip()
    intervals: list[float] = []
    course_ids: list[uuid.UUID] = []
    try:
        for rating in (1, 2, 3, 4):
            course_id, card_id = await _course_with_card()
            course_ids.append(course_id)
            result = await review_flashcard(card_id, rating, now=FROZEN)
            intervals.append(result.interval_days)
        assert intervals == sorted(intervals), f"intervals must not decrease: {intervals}"
        assert intervals[0] < intervals[-1], "Again must schedule far sooner than Easy"
    finally:
        for course_id in course_ids:
            await _cleanup(course_id)


@pytest.mark.asyncio
async def test_again_marks_a_lapse_and_easy_does_not() -> None:
    await _services_or_skip()
    course_id, card_id = await _course_with_card()
    try:
        assert (await review_flashcard(card_id, 1, now=FROZEN)).lapses == 1
        assert (await review_flashcard(card_id, 4, now=FROZEN)).lapses == 1
    finally:
        await _cleanup(course_id)


@pytest.mark.asyncio
async def test_due_counts_respect_a_day_boundary() -> None:
    """§13 VERIFY: assert due counts are correct across a day boundary, with time frozen
    rather than slept through."""
    await _services_or_skip()
    course_id, card_id = await _course_with_card()
    try:
        assert (await deck_stats(course_id, now=FROZEN))["new"] == 1
        # "Easy" on a new card schedules it well beyond tomorrow.
        result = await review_flashcard(card_id, 4, now=FROZEN)
        assert result.interval_days > 1

        same_day = await deck_stats(course_id, now=FROZEN + timedelta(hours=6))
        assert same_day["due"] == 0, "a card just answered Easy is not due again today"
        assert same_day["new"] == 0

        later = await deck_stats(course_id, now=result.due + timedelta(minutes=1))
        assert later["due"] == 1, "the card must come due once its interval elapses"
    finally:
        await _cleanup(course_id)


@pytest.mark.asyncio
async def test_unseen_cards_are_due_immediately() -> None:
    await _services_or_skip()
    course_id, card_id = await _course_with_card()
    try:
        due = await due_flashcards(course_id, now=FROZEN)
        assert [c.id for c in due] == [card_id]
    finally:
        await _cleanup(course_id)


@pytest.mark.asyncio
async def test_a_missed_question_becomes_a_flashcard() -> None:
    """§13 task 4 — the bridge between the two halves of the product, and the mechanic the
    spec singles out. The card must carry the question's citations so I1 survives the
    promotion."""
    await _services_or_skip()
    async with session_scope() as session:
        course = Course(name=f"promote-probe-{uuid.uuid4()}")
        session.add(course)
        await session.flush()
        document = Document(
            course_id=course.id, filename="d.pptx", sha256="c" * 64, ingest_status="complete"
        )
        session.add(document)
        await session.flush()
        chunk = Chunk(
            document_id=document.id,
            course_id=course.id,
            text="Horizontal fragmentation splits a relation by rows.",
            page_start=9,
            page_end=9,
            section_path=["u", "t"],
            token_count=200,
        )
        session.add(chunk)
        quiz = Quiz(course_id=course.id, scope={}, question_count=1, generation_meta={})
        session.add(quiz)
        await session.flush()
        question = Question(
            quiz_id=quiz.id,
            stem="What is horizontal fragmentation?",
            options=[
                {"id": "A", "text": "Splitting by rows", "is_correct": True},
                {"id": "B", "text": "Splitting by columns", "is_correct": False, "why_wrong": "w"},
                {"id": "C", "text": "Replication", "is_correct": False, "why_wrong": "w"},
                {"id": "D", "text": "Allocation", "is_correct": False, "why_wrong": "w"},
            ],
            explanation="e",
            source_chunk_ids=[str(chunk.id)],
            page_refs=[9],
        )
        session.add(question)
        await session.flush()
        course_id, question_id = course.id, question.id

    try:
        async with session_scope() as session:
            q = await session.get(Question, question_id)
            assert q is not None
            card_id = await promote_missed_question(q)
        assert card_id is not None

        async with session_scope() as session:
            card = await session.get(Flashcard, card_id)
            assert card is not None
            assert card.origin == "missed_question"
            assert card.back == "Splitting by rows", "the card's back is the correct answer"
            assert card.page_refs == [9], "I1 must survive the promotion"
            assert card.source_chunk_ids

        # Missing the same question twice must not produce two cards.
        async with session_scope() as session:
            q = await session.get(Question, question_id)
            assert q is not None
            again = await promote_missed_question(q)
        assert again == card_id
    finally:
        await _cleanup(course_id)
