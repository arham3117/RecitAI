"""Path B — similarity search (spec §3.1, §10 task 5).

For explanations, follow-up questions, scope resolution, and citation lookup: cases where
a real query with semantics exists. **Never** for choosing chunks to generate from — that
is Path A's job (`sampler.py`), and the distinction is the architecture (ADR 0001).
"""

import uuid
from dataclasses import dataclass

from recitai.constants import DEFAULT_TOP_K
from recitai.llm.base import LLMClient
from recitai.retrieval.vector_store import VectorStore


@dataclass(frozen=True)
class SearchHit:
    chunk_id: uuid.UUID
    score: float
    page_start: int
    page_end: int
    section_path: list[str]
    topic_id: uuid.UUID | None


async def search(
    query: str,
    client: LLMClient,
    store: VectorStore,
    *,
    course_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    topic_ids: list[uuid.UUID] | None = None,
    limit: int = DEFAULT_TOP_K,
) -> list[SearchHit]:
    vectors = await client.embed([query])
    raw = await store.search(
        vectors[0],
        course_id=course_id,
        document_id=document_id,
        topic_ids=topic_ids,
        limit=limit,
    )
    hits: list[SearchHit] = []
    for item in raw:
        topic_raw = item.get("topic_id")
        hits.append(
            SearchHit(
                chunk_id=uuid.UUID(str(item["chunk_id"])),
                score=float(item["score"]),
                page_start=int(item["page_start"]),
                page_end=int(item["page_end"]),
                section_path=list(item.get("section_path") or []),
                topic_id=uuid.UUID(str(topic_raw)) if topic_raw else None,
            )
        )
    return hits
