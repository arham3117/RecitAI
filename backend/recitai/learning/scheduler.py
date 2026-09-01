"""Spaced repetition via FSRS (spec §13 task 1).

Full scheduler state is persisted to `reviews` so a card's schedule can be reconstructed
without replaying its history.

**The library is v6, not the v4 the spec assumed** (plan/ISSUES.md I-019). Two differences
that matter: the entry point is `Scheduler.review_card` rather than a `FSRS` class, and v6
has no `New` state — a card begins in `Learning`. The `reviews.state` check constraint
still permits `new` because §4.2 lists it; nothing writes it.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from fsrs import Card, Rating, Scheduler, State
from sqlalchemy import desc, select

from recitai.constants import FSRS_DESIRED_RETENTION
from recitai.db.models import Flashcard, Review
from recitai.db.session import session_scope

log = structlog.get_logger(__name__)

_scheduler = Scheduler(desired_retention=FSRS_DESIRED_RETENTION)

#: §13 task 5's deck buckets. "Mature" is the conventional threshold — a card whose
#: stability exceeds three weeks is one the student reliably knows.
MATURE_STABILITY_DAYS = 21


@dataclass(frozen=True)
class ScheduleResult:
    due: datetime
    stability: float
    difficulty: float
    state: str
    lapses: int
    interval_days: float


def _to_card(review: Review | None, now: datetime) -> Card:
    """Reconstruct the FSRS card from the last persisted review."""
    if review is None:
        return Card()
    state = {
        "learning": State.Learning,
        "review": State.Review,
        "relearning": State.Relearning,
        "new": State.Learning,
    }[review.state]
    return Card(
        state=state,
        stability=review.stability,
        difficulty=review.difficulty,
        due=review.due_date or now,
        last_review=review.reviewed_at,
    )


async def review_flashcard(
    flashcard_id: uuid.UUID, rating: int, now: datetime | None = None
) -> ScheduleResult:
    """Grade a card 1–4 and persist the resulting schedule (§13 task 2)."""
    if rating not in (1, 2, 3, 4):
        raise ValueError(f"rating must be 1-4, got {rating}")
    moment = now or datetime.now(UTC)

    async with session_scope() as session:
        card_row = await session.get(Flashcard, flashcard_id)
        if card_row is None:
            raise ValueError(f"no flashcard {flashcard_id}")
        previous = await session.scalar(
            select(Review)
            .where(Review.flashcard_id == flashcard_id)
            .order_by(desc(Review.reviewed_at))
            .limit(1)
        )
        card = _to_card(previous, moment)
        updated, _log = _scheduler.review_card(card, Rating(rating), moment)

        lapses = (previous.lapses if previous else 0) + (1 if rating == 1 else 0)
        state = updated.state.name.lower()
        assert updated.due is not None
        session.add(
            Review(
                flashcard_id=flashcard_id,
                rating=rating,
                reviewed_at=moment,
                stability=updated.stability,
                difficulty=updated.difficulty,
                due_date=updated.due,
                state=state,
                lapses=lapses,
            )
        )
        result = ScheduleResult(
            due=updated.due,
            stability=float(updated.stability or 0.0),
            difficulty=float(updated.difficulty or 0.0),
            state=state,
            lapses=lapses,
            interval_days=(updated.due - moment).total_seconds() / 86400,
        )
    log.info(
        "fsrs.reviewed",
        flashcard_id=str(flashcard_id),
        rating=rating,
        state=result.state,
        interval_days=round(result.interval_days, 3),
    )
    return result


async def due_flashcards(
    course_id: uuid.UUID, now: datetime | None = None, limit: int = 50
) -> list[Flashcard]:
    """Cards due for review, never-reviewed cards first (§13 task 2).

    A card with no review is due immediately: it has never been seen.
    """
    moment = now or datetime.now(UTC)
    async with session_scope() as session:
        cards = list(
            (await session.execute(select(Flashcard).where(Flashcard.course_id == course_id)))
            .scalars()
            .all()
        )
        latest: dict[uuid.UUID, Review] = {}
        for review in (
            await session.execute(
                select(Review).order_by(Review.flashcard_id, desc(Review.reviewed_at))
            )
        ).scalars():
            latest.setdefault(review.flashcard_id, review)

    unseen = [c for c in cards if c.id not in latest]
    ready: list[Flashcard] = []
    for card in cards:
        seen = latest.get(card.id)
        if seen is not None and seen.due_date is not None and seen.due_date <= moment:
            ready.append(card)
    return (unseen + ready)[:limit]


async def deck_stats(course_id: uuid.UUID, now: datetime | None = None) -> dict[str, int]:
    """§13 task 5: due today, new, learning, mature."""
    moment = now or datetime.now(UTC)
    async with session_scope() as session:
        cards = list(
            (await session.execute(select(Flashcard).where(Flashcard.course_id == course_id)))
            .scalars()
            .all()
        )
        latest: dict[uuid.UUID, Review] = {}
        for review in (
            await session.execute(
                select(Review).order_by(Review.flashcard_id, desc(Review.reviewed_at))
            )
        ).scalars():
            latest.setdefault(review.flashcard_id, review)

    stats = {"total": len(cards), "new": 0, "learning": 0, "review": 0, "mature": 0, "due": 0}
    for card in cards:
        seen = latest.get(card.id)
        if seen is None:
            stats["new"] += 1
            stats["due"] += 1
            continue
        if seen.state in ("learning", "relearning"):
            stats["learning"] += 1
        else:
            stats["review"] += 1
        if (seen.stability or 0) >= MATURE_STABILITY_DAYS:
            stats["mature"] += 1
        if seen.due_date is not None and seen.due_date <= moment:
            stats["due"] += 1
    return stats
