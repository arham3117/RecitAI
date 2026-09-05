"""Path A — the coverage sampler (spec §3.3).

This is the single most important module in the system (§0.2). Quiz and flashcard
generation select chunks here and never through vector search: a similarity contest
against a chapter name returns the chunks that *say* the chapter name most, which is the
introduction, so the student is quizzed on four pages of thirty and nothing says so.

Deterministic under a fixed seed (invariant I6).
"""

import random
import uuid
from dataclasses import dataclass, field

import structlog
from sqlalchemy import select

from recitai.constants import MIN_CHUNK_TOKENS_FOR_GENERATION, WEAKNESS_MAX_MULTIPLIER
from recitai.db.models import Chunk, TopicMastery
from recitai.db.session import session_scope
from recitai.retrieval.resolver import Scope

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ChunkRef:
    """A chunk chosen for generation, carrying what I1 requires to cite it."""

    chunk_id: uuid.UUID
    topic_id: uuid.UUID | None
    text: str
    page_start: int
    page_end: int
    section_path: list[str]
    token_count: int
    quiz_usage_count: int


@dataclass
class TopicStats:
    topic_id: uuid.UUID
    chunk_count: int
    mean_usage: float
    accuracy: float | None


@dataclass
class SamplingReport:
    """What the sampler did, so a shortfall is visible rather than silent (I-006)."""

    requested: int
    delivered: int
    topics_in_scope: int
    topics_covered: int
    allocation: dict[str, int] = field(default_factory=dict)
    shortfall_reason: str | None = None

    @property
    def coverage(self) -> float:
        if not self.topics_in_scope:
            return 0.0
        return self.topics_covered / self.topics_in_scope


def compute_weights(stats: list[TopicStats]) -> dict[uuid.UUID, float]:
    """§3.3 step 1: weight = size × freshness × weakness."""
    total_chunks = sum(s.chunk_count for s in stats)
    if not total_chunks:
        return {}

    weights: dict[uuid.UUID, float] = {}
    for s in stats:
        size = s.chunk_count / total_chunks
        freshness = 1.0 / (1.0 + s.mean_usage)
        # weakness ranges 1.0–2.0, so a topic the student is failing gets up to double.
        weakness = 1.0 if s.accuracy is None else 1.0 + (1.0 - s.accuracy)
        weakness = min(weakness, WEAKNESS_MAX_MULTIPLIER)
        weights[s.topic_id] = size * freshness * weakness
    return weights


def allocate(
    weights: dict[uuid.UUID, float], n: int, capacity: dict[uuid.UUID, int] | None = None
) -> dict[uuid.UUID, int]:
    """§3.3 step 2: largest-remainder allocation over normalised weights.

    When `n >= topic_count`, every topic is guaranteed at least one question — coverage
    (I3) is the point of this module, and a topic allocated zero is a topic the student is
    never asked about.

    `capacity` caps a topic at the number of chunks it can actually supply, and the
    remainder is redistributed by descending weight to topics that still have room. The
    spec is silent here (I-006); dropping the remainder silently would concentrate the
    shortfall in exactly the topics with the sparsest material.
    """
    if n <= 0 or not weights:
        return {}

    caps = capacity or {}
    topics = [t for t in weights if caps.get(t, 1) > 0]
    if not topics:
        return {}

    total = sum(weights[t] for t in topics)
    if total <= 0:
        return {}

    allocation = {t: 0 for t in topics}
    guaranteed = 0
    if n >= len(topics):
        for t in topics:
            allocation[t] = 1
            guaranteed += 1

    remaining = n - guaranteed
    if remaining > 0:
        exact = {t: remaining * weights[t] / total for t in topics}
        floors = {t: int(v) for t, v in exact.items()}
        for t, v in floors.items():
            allocation[t] += v
        leftover = remaining - sum(floors.values())
        # Largest remainder, with the weight and topic id as deterministic tie-breaks.
        order = sorted(topics, key=lambda t: (-(exact[t] - floors[t]), -weights[t], str(t)))
        for t in order[:leftover]:
            allocation[t] += 1

    # Cap at capacity, then redistribute what could not be placed.
    surplus = 0
    for t in topics:
        cap = caps.get(t)
        if cap is not None and allocation[t] > cap:
            surplus += allocation[t] - cap
            allocation[t] = cap

    while surplus > 0:
        takers = [
            t
            for t in sorted(topics, key=lambda t: (-weights[t], str(t)))
            if caps.get(t) is None or allocation[t] < caps[t]
        ]
        if not takers:
            break
        for t in takers:
            if surplus == 0:
                break
            allocation[t] += 1
            surplus -= 1

    return {t: c for t, c in allocation.items() if c > 0}


async def _load_stats(scope: Scope) -> tuple[list[TopicStats], dict[uuid.UUID, list[Chunk]]]:
    async with session_scope() as session:
        query = select(Chunk).where(
            Chunk.course_id == scope.course_id,
            Chunk.token_count >= MIN_CHUNK_TOKENS_FOR_GENERATION,
            Chunk.topic_id.is_not(None),
        )
        if scope.topic_ids:
            query = query.where(Chunk.topic_id.in_(scope.topic_ids))
        if scope.document_ids:
            query = query.where(Chunk.document_id.in_(scope.document_ids))
        chunks = list((await session.execute(query)).scalars().all())

        mastery = {
            m.topic_id: m
            for m in (
                await session.execute(
                    select(TopicMastery).where(TopicMastery.course_id == scope.course_id)
                )
            ).scalars()
        }

    by_topic: dict[uuid.UUID, list[Chunk]] = {}
    for chunk in chunks:
        assert chunk.topic_id is not None
        by_topic.setdefault(chunk.topic_id, []).append(chunk)

    stats = [
        TopicStats(
            topic_id=tid,
            chunk_count=len(rows),
            mean_usage=sum(c.quiz_usage_count for c in rows) / len(rows),
            accuracy=mastery[tid].accuracy if tid in mastery else None,
        )
        for tid, rows in by_topic.items()
    ]
    return stats, by_topic


async def sample_chunks(
    scope: Scope, n: int | None = None, seed: int | None = None
) -> tuple[list[ChunkRef], SamplingReport]:
    """§3.3. Returns the selected chunks and a report of how they were chosen.

    `n = None` means **cover the scope**: one passage per concept in it, so the length of a
    quiz is a property of the material rather than a number the student had to guess. This
    is the natural reading of Path A — §3.1 exists to guarantee full coverage of a scope,
    and asking for "20 questions" was always an arbitrary cap on top of that.

    A passage *is* a concept here: chunking merges consecutive slides into coherent units
    of roughly `TARGET_CHUNK_TOKENS`, so the units already are the ideas the material
    covers. Passages too thin to support a question are filtered twice over — by
    `MIN_CHUNK_TOKENS_FOR_GENERATION` here, and by the model's own `{"insufficient": true}`
    response during generation (§6.1).
    """
    stats, by_topic = await _load_stats(scope)
    total_eligible = sum(s.chunk_count for s in stats)
    requested = n if n is not None else total_eligible
    report = SamplingReport(
        requested=requested, delivered=0, topics_in_scope=len(stats), topics_covered=0
    )

    if not stats:
        report.shortfall_reason = (
            "no chunks in scope clear MIN_CHUNK_TOKENS_FOR_GENERATION "
            f"({MIN_CHUNK_TOKENS_FOR_GENERATION} tokens)"
        )
        return [], report

    capacity = {s.topic_id: s.chunk_count for s in stats}
    # Covering the scope needs no allocation, because nothing is being left out.
    allocation = dict(capacity) if n is None else allocate(compute_weights(stats), n, capacity)

    rng = random.Random(seed)
    selected: list[ChunkRef] = []
    for topic_id, count in sorted(allocation.items(), key=lambda kv: str(kv[0])):
        rows = by_topic[topic_id]
        # §3.3 step 3: least-used first, seeded RNG as the tie-break so repeated runs with
        # the same seed produce identical output (I6).
        ordered = sorted(rows, key=lambda c: (c.quiz_usage_count, rng.random(), str(c.id)))
        for chunk in ordered[:count]:
            selected.append(
                ChunkRef(
                    chunk_id=chunk.id,
                    topic_id=chunk.topic_id,
                    text=chunk.text,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    section_path=list(chunk.section_path),
                    token_count=chunk.token_count,
                    quiz_usage_count=chunk.quiz_usage_count,
                )
            )

    report.delivered = len(selected)
    report.topics_covered = len({c.topic_id for c in selected})
    report.allocation = {str(k): v for k, v in allocation.items()}
    if len(selected) < requested:
        available = sum(capacity.values())
        report.shortfall_reason = (
            f"scope holds {available} eligible passages; {requested} requested"
            if available < requested
            else "allocation could not place every question"
        )

    log.info(
        "sampler.sampled",
        requested=n,
        delivered=report.delivered,
        topics_in_scope=report.topics_in_scope,
        topics_covered=report.topics_covered,
        coverage=round(report.coverage, 3),
        seed=seed,
    )
    return selected, report


async def scope_size(scope: Scope) -> tuple[int, int]:
    """How many concepts a scope holds, and across how many topics.

    Used to tell the student what a quiz will cover *before* generating it — the length is
    determined by the material, so it should be visible in advance rather than a surprise.
    """
    stats, _ = await _load_stats(scope)
    return sum(s.chunk_count for s in stats), len(stats)


async def increment_usage(chunk_ids: list[uuid.UUID]) -> None:
    """§3.3 step 4 — only after generation succeeds."""
    if not chunk_ids:
        return
    async with session_scope() as session:
        for chunk in (
            await session.execute(select(Chunk).where(Chunk.id.in_(chunk_ids)))
        ).scalars():
            chunk.quiz_usage_count += 1
