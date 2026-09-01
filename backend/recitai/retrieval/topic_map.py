"""Build the topic tree from chunk section paths (spec §10 task 2).

`section_path` is `[unit, heading]` — the document is the unit, the slide heading (or PDF
heading) names the passage.

**A topic must group more than one chunk, or it is not a topic.** The spec's model is a
topic the size of a chapter: §3.1's worked example is "Chapter 2: Thermodynamics", 41
chunks over 30 pages. Building one topic per heading on this corpus produced 35 topics for
35 chunks — a 1:1 mapping in which choosing a topic *is* choosing a chunk, the sampler's
size and freshness weights are all identical, and §10's ≥80% coverage target becomes
arithmetically unreachable (20 questions cannot touch 28 of 35 topics).

So the tree is built at the finest level that still groups: heading-level topics when
headings genuinely repeat across chunks, unit-level otherwise. See D-011.

Where a document has fewer than `MIN_DISTINCT_PATHS` usable headings, the spec falls back
to clustering chunk embeddings with HDBSCAN and naming each cluster via
`topic_naming_v1.md`. That path is implemented as a documented gap rather than guessed at:
this corpus has 227 titled slides out of 227, so it has never run, and shipping an
unexercised clustering path would be worse than saying so.
"""

import uuid

import structlog
from sqlalchemy import func, select, update

from recitai.db.models import Chunk, Topic
from recitai.db.session import session_scope
from recitai.retrieval.vector_store import VectorStore

log = structlog.get_logger(__name__)

#: Below this many distinct section paths, headings are not a usable tree (§10 task 2).
MIN_DISTINCT_PATHS = 3

#: If this fraction or more of heading-level topics would hold a single chunk, headings do
#: not group anything and the tree collapses to unit level (D-011).
SINGLETON_COLLAPSE_RATIO = 0.8


class NoUsableHeadingsError(RuntimeError):
    """The document has no heading structure to build topics from.

    Spec §10 task 2 calls for HDBSCAN clustering here. Not implemented — see
    plan/ISSUES.md I-024. Raised rather than silently producing a one-topic course, which
    would quietly defeat invariant I3.
    """


async def build_topic_map(
    course_id: uuid.UUID, vector_store: VectorStore | None = None
) -> list[Topic]:
    """Create topics from section paths and assign every chunk to one.

    Idempotent: re-running replaces the course's topics and reassigns its chunks.
    """
    async with session_scope() as session:
        rows: list[tuple[list[str], int]] = [
            (list(path or []), int(count))
            for path, count in (
                await session.execute(
                    select(Chunk.section_path, func.count(Chunk.id))
                    .where(Chunk.course_id == course_id)
                    .group_by(Chunk.section_path)
                )
            ).all()
        ]

        if not rows:
            raise ValueError(f"course {course_id} has no chunks — ingest before mapping topics")

        distinct = {tuple(path) for path, _ in rows if path}
        if len(distinct) < MIN_DISTINCT_PATHS:
            raise NoUsableHeadingsError(
                f"course {course_id} has {len(distinct)} distinct section paths, below the "
                f"{MIN_DISTINCT_PATHS} needed to build a tree from headings. Clustering "
                f"fallback is not implemented (plan/ISSUES.md I-024)."
            )

        # Does the heading level actually group chunks, or is it 1:1 with them?
        singletons = sum(1 for _path, count in rows if count == 1)
        collapse = len(rows) > 0 and singletons / len(rows) >= SINGLETON_COLLAPSE_RATIO
        if collapse:
            grouped: dict[tuple[str, ...], int] = {}
            for path, count in rows:
                key = (path[0],) if path else ()
                grouped[key] = grouped.get(key, 0) + count
            rows = [(list(k), v) for k, v in grouped.items()]
            log.info(
                "topic_map.collapsed_to_units",
                course_id=str(course_id),
                reason="heading-level topics would be 1:1 with chunks",
                units=len(rows),
            )

        # Clear any previous mapping so a re-run cannot leave stale topics behind.
        await session.execute(
            update(Chunk).where(Chunk.course_id == course_id).values(topic_id=None)
        )
        existing = (
            (await session.execute(select(Topic).where(Topic.course_id == course_id)))
            .scalars()
            .all()
        )
        for topic in existing:
            await session.delete(topic)
        await session.flush()

        units: dict[str, Topic] = {}
        created: list[Topic] = []
        topic_assignments: list[tuple[uuid.UUID, list[uuid.UUID]]] = []
        order = 0

        if not collapse:
            # Two levels: unit rows exist purely as parents and hold no chunks directly.
            for path, _count in sorted(rows, key=lambda r: (r[0] or [""])[0]):
                if not path or path[0] in units:
                    continue
                unit = Topic(
                    course_id=course_id,
                    name=path[0],
                    section_path=[path[0]],
                    parent_topic_id=None,
                    order_index=order,
                )
                session.add(unit)
                await session.flush()
                units[path[0]] = unit
                order += 1

        for index, (path, count) in enumerate(sorted(rows, key=lambda r: tuple(r[0] or []))):
            if not path:
                continue
            parent = units.get(path[0]) if not collapse else None
            topic = Topic(
                course_id=course_id,
                name=path[-1] if len(path) > 1 and not collapse else path[0],
                section_path=list(path),
                parent_topic_id=parent.id if parent else None,
                chunk_count=count,
                order_index=index,
            )
            session.add(topic)
            await session.flush()
            if collapse:
                # Match on the unit prefix: chunks keep their full heading path.
                stmt = update(Chunk).where(
                    Chunk.course_id == course_id,
                    Chunk.section_path[0].astext == path[0],
                )
            else:
                stmt = update(Chunk).where(
                    Chunk.course_id == course_id, Chunk.section_path == list(path)
                )
            await session.execute(stmt.values(topic_id=topic.id))
            assigned = list(
                (
                    await session.execute(
                        select(Chunk.id).where(
                            Chunk.course_id == course_id, Chunk.topic_id == topic.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            topic_assignments.append((topic.id, assigned))
            created.append(topic)

        for unit in units.values():
            unit.chunk_count = sum(t.chunk_count for t in created if t.parent_topic_id == unit.id)

        log.info("topic_map.built", course_id=str(course_id), units=len(units), topics=len(created))

    # Mirror the assignment into the vector payloads. Ingestion writes vectors before the
    # topic tree exists, so every payload starts with topic_id: null — and the resolver's
    # expansion step (§3.2) reads exactly that field. Left unset, every free-text scope
    # silently collapses to the whole course.
    store = vector_store or VectorStore()
    try:
        for topic_id, chunk_ids in topic_assignments:
            await store.set_topic_for_chunks(topic_id, chunk_ids)
    finally:
        if vector_store is None:
            await store.aclose()

    return created


async def topic_tree(course_id: uuid.UUID) -> list[tuple[Topic, list[Topic]]]:
    """Units with their child topics, in syllabus order."""
    async with session_scope() as session:
        topics = (
            (
                await session.execute(
                    select(Topic).where(Topic.course_id == course_id).order_by(Topic.order_index)
                )
            )
            .scalars()
            .all()
        )
    units = [t for t in topics if t.parent_topic_id is None]
    return [(u, [t for t in topics if t.parent_topic_id == u.id]) for u in units]
