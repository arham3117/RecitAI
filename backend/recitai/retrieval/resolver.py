"""Scope resolution (spec §3.2).

Two entry points, one `Scope`:

- The student picks from the topic tree → a pure metadata filter.
- The student types free text → fuzzy-match topic names first; on a miss, vector search
  locates the material and the result is **expanded** to the topic ids of the chunks
  found.

The expansion is the whole point. Search LOCATES the chapter; the sampler then covers ALL
of it. Returning the retrieved chunks directly is the failure ADR 0001 exists to prevent,
wearing the right module name.
"""

import uuid
from dataclasses import dataclass, field

import structlog
from rapidfuzz import fuzz
from sqlalchemy import select

from recitai.constants import FUZZY_MATCH_THRESHOLD, RESOLVER_TOP_K
from recitai.db.models import Topic
from recitai.db.session import session_scope
from recitai.llm.base import LLMClient
from recitai.retrieval.vector_store import VectorStore

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Scope:
    course_id: uuid.UUID
    topic_ids: list[uuid.UUID] = field(default_factory=list)  # empty = whole course
    document_ids: list[uuid.UUID] | None = None

    @property
    def is_whole_course(self) -> bool:
        return not self.topic_ids


async def _leaf_topics(course_id: uuid.UUID) -> list[Topic]:
    """Topics that hold chunks: those which are not the parent of another topic.

    Defined structurally rather than as "has a parent", because the tree may be a single
    level deep (D-011) — a unit-level topic has no parent and is still a leaf. The
    previous definition returned nothing for a one-level tree, so every free-text query
    silently fell back to whole-course scope.
    """
    async with session_scope() as session:
        rows = list(
            (await session.execute(select(Topic).where(Topic.course_id == course_id)))
            .scalars()
            .all()
        )
    parents = {t.parent_topic_id for t in rows if t.parent_topic_id is not None}
    return [t for t in rows if t.id not in parents]


async def resolve_scope(
    course_id: uuid.UUID,
    query: str | None = None,
    topic_ids: list[uuid.UUID] | None = None,
    *,
    client: LLMClient | None = None,
    store: VectorStore | None = None,
) -> Scope:
    # 1. Explicit selection from the topic tree — the default path.
    if topic_ids:
        return Scope(course_id=course_id, topic_ids=list(topic_ids))

    if not query:
        return Scope(course_id=course_id, topic_ids=[])

    topics = await _leaf_topics(course_id)
    if not topics:
        return Scope(course_id=course_id, topic_ids=[])

    # 2. Fuzzy match against topic names.
    matches = [
        t for t in topics if fuzz.ratio(query.lower(), t.name.lower()) >= FUZZY_MATCH_THRESHOLD
    ]
    if matches:
        log.info("resolver.fuzzy_hit", query=query, topics=[t.name for t in matches])
        return Scope(course_id=course_id, topic_ids=[t.id for t in matches])

    # 3. Miss → Path B locates the material, then EXPAND to whole topics.
    if client is None or store is None:
        log.info("resolver.no_search_client", query=query)
        return Scope(course_id=course_id, topic_ids=[])

    vectors = await client.embed([query])
    hits = await store.search(vectors[0], course_id=course_id, limit=RESOLVER_TOP_K)

    expanded: list[uuid.UUID] = []
    for hit in hits:
        raw = hit.get("topic_id")
        if raw:
            tid = uuid.UUID(str(raw))
            if tid not in expanded:
                expanded.append(tid)

    log.info(
        "resolver.expanded",
        query=query,
        chunks_found=len(hits),
        topics_expanded=len(expanded),
        note="generation covers all of these topics, not just the retrieved chunks",
    )
    return Scope(course_id=course_id, topic_ids=expanded)
