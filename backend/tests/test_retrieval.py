"""Retrieval tests.

The pure-function sampler tests run anywhere. `test_golden_recall` is the §10 VERIFY and
needs Qdrant, Ollama, and an ingested corpus, so it skips when those are absent — CI runs
service-free.
"""

import json
import uuid
from pathlib import Path

import pytest

from recitai.retrieval.sampler import TopicStats, allocate, compute_weights

REPO = Path(__file__).resolve().parents[2]
GOLDEN = REPO / "eval" / "golden_set.jsonl"


def _tid(n: int) -> uuid.UUID:
    return uuid.UUID(int=n)


# ------------------------------------------------------------------ weighting ----


def test_weight_is_size_times_freshness_times_weakness() -> None:
    stats = [
        TopicStats(_tid(1), chunk_count=10, mean_usage=0.0, accuracy=None),
        TopicStats(_tid(2), chunk_count=10, mean_usage=0.0, accuracy=None),
    ]
    w = compute_weights(stats)
    assert w[_tid(1)] == pytest.approx(w[_tid(2)])


def test_a_weak_topic_outweighs_a_strong_one_of_equal_size() -> None:
    """weakness ranges 1.0-2.0, so a topic the student is failing gets up to double."""
    stats = [
        TopicStats(_tid(1), chunk_count=10, mean_usage=0.0, accuracy=0.2),  # failing
        TopicStats(_tid(2), chunk_count=10, mean_usage=0.0, accuracy=0.95),  # solid
    ]
    w = compute_weights(stats)
    assert w[_tid(1)] > w[_tid(2)]


def test_heavily_quizzed_topics_decay() -> None:
    """freshness rotates coverage across sessions."""
    stats = [
        TopicStats(_tid(1), chunk_count=10, mean_usage=0.0, accuracy=None),
        TopicStats(_tid(2), chunk_count=10, mean_usage=9.0, accuracy=None),
    ]
    w = compute_weights(stats)
    assert w[_tid(1)] > w[_tid(2)]


# ----------------------------------------------------------------- allocation ----


def test_every_topic_gets_at_least_one_when_n_exceeds_topic_count() -> None:
    """I3: a topic allocated zero is a topic the student is never asked about."""
    weights = {_tid(i): float(i) for i in range(1, 6)}
    alloc = allocate(weights, n=10)
    assert len(alloc) == 5
    assert all(v >= 1 for v in alloc.values())
    assert sum(alloc.values()) == 10


def test_allocation_totals_exactly_n() -> None:
    weights = {_tid(1): 0.5, _tid(2): 0.3, _tid(3): 0.2}
    for n in (3, 7, 20, 21):
        assert sum(allocate(weights, n).values()) == n


def test_capacity_shortfall_is_redistributed_not_dropped() -> None:
    """I-006. The spec is silent on what happens when a topic holds fewer eligible chunks
    than it was allocated. Dropping the remainder concentrates the shortfall in exactly
    the topics with the sparsest material."""
    weights = {_tid(1): 0.5, _tid(2): 0.5}
    capacity = {_tid(1): 1, _tid(2): 20}
    alloc = allocate(weights, n=10, capacity=capacity)
    assert alloc[_tid(1)] == 1, "must not exceed what the topic can supply"
    assert sum(alloc.values()) == 10, "the remainder must go somewhere"
    assert alloc[_tid(2)] == 9


def test_allocation_cannot_exceed_total_capacity() -> None:
    weights = {_tid(1): 0.5, _tid(2): 0.5}
    capacity = {_tid(1): 2, _tid(2): 3}
    alloc = allocate(weights, n=50, capacity=capacity)
    assert sum(alloc.values()) == 5


def test_allocation_is_deterministic() -> None:
    """I6 — identical inputs, identical output, every time."""
    weights = {_tid(i): 1.0 for i in range(1, 8)}
    runs = [allocate(weights, 13) for _ in range(5)]
    assert all(r == runs[0] for r in runs)


# --------------------------------------------------------------- golden recall ----


def test_golden_set_is_well_formed() -> None:
    rows = [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]
    assert len(rows) >= 10
    assert all(r["query"] and len(r["source_section"]) == 2 for r in rows)
    assert len({r["id"] for r in rows}) == len(rows)


@pytest.mark.asyncio
async def test_golden_recall() -> None:
    """§10 VERIFY: at least 8 of 10 hand-written questions retrieve their source chunk
    in the top 5. This measures Path B only — generation never uses it."""
    from recitai.constants import DEFAULT_TOP_K

    await _services_or_skip()

    import sqlalchemy as sa

    from recitai.db.models import Chunk, Course
    from recitai.db.session import session_scope
    from recitai.llm.ollama import OllamaClient
    from recitai.retrieval.search import search
    from recitai.retrieval.vector_store import VectorStore

    async with session_scope() as session:
        course = await session.scalar(sa.select(Course))
        if course is None:
            pytest.skip("no ingested course")
        chunks = list(
            (await session.execute(sa.select(Chunk).where(Chunk.course_id == course.id)))
            .scalars()
            .all()
        )
    if not chunks:
        pytest.skip("no ingested chunks")

    by_section = {tuple(c.section_path): c.id for c in chunks}
    rows = [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]

    client = OllamaClient()
    store = VectorStore()
    hits = 0
    try:
        for row in rows:
            expected = by_section.get(tuple(row["source_section"]))
            if expected is None:
                continue
            results = await search(
                row["query"], client, store, course_id=course.id, limit=DEFAULT_TOP_K
            )
            if expected in [r.chunk_id for r in results]:
                hits += 1
    finally:
        await client.aclose()
        await store.aclose()

    assert hits >= 8, f"recall@{DEFAULT_TOP_K} was {hits}/10; the spec's bar is 8/10"


# ------------------------------------------------------- resolver regressions ----


async def _services_or_skip() -> None:
    """Skip only when the database genuinely is not there.

    Anything else — a closed event loop, a bad URL, a missing table — is a real failure
    and must surface rather than masquerade as an absent service.
    """
    import asyncpg

    from recitai.db.session import engine

    try:
        async with engine.connect():
            return
    except (asyncpg.CannotConnectNowError, ConnectionRefusedError, OSError) as exc:
        pytest.skip(f"postgres not reachable: {exc}")


@pytest.mark.asyncio
async def test_leaf_topics_found_in_a_single_level_tree() -> None:
    """Regression: leaves were defined as "has a parent", which returns nothing when the
    tree is one level deep (D-011). Every free-text query then silently resolved to
    whole-course scope — a scoping failure that still returns a plausible quiz."""
    import sqlalchemy as sa

    from recitai.db.models import Course, Topic
    from recitai.db.session import session_scope
    from recitai.retrieval.resolver import _leaf_topics

    await _services_or_skip()
    async with session_scope() as session:
        course = await session.scalar(sa.select(Course))
        if course is None:
            pytest.skip("no ingested course")
        topics = list(
            (await session.execute(sa.select(Topic).where(Topic.course_id == course.id)))
            .scalars()
            .all()
        )
    if not topics:
        pytest.skip("topics not mapped")

    leaves = await _leaf_topics(course.id)
    assert leaves, "a mapped course must expose leaf topics"
    assert len(leaves) <= len(topics)


@pytest.mark.asyncio
async def test_vector_payloads_carry_topic_id_after_mapping() -> None:
    """Regression: ingestion writes vectors before topics exist, so payloads start with
    topic_id null. The resolver's expansion reads exactly that field — unset, it expands
    to nothing and scoping silently degrades to the whole course."""
    import sqlalchemy as sa

    from recitai.db.models import Course
    from recitai.db.session import session_scope
    from recitai.llm.ollama import OllamaClient
    from recitai.retrieval.vector_store import VectorStore

    await _services_or_skip()
    async with session_scope() as session:
        course = await session.scalar(sa.select(Course))
        if course is None:
            pytest.skip("no ingested course")

    client, store = OllamaClient(), VectorStore()
    try:
        vector = await client.embed(["distributed database fragmentation"])
        hits = await store.search(vector[0], course_id=course.id, limit=5)
    finally:
        await client.aclose()
        await store.aclose()

    if not hits:
        pytest.skip("nothing indexed")
    missing = [h for h in hits if not h.get("topic_id")]
    assert not missing, f"{len(missing)}/{len(hits)} indexed chunks have no topic_id"
