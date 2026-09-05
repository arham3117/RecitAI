"""Qdrant wrapper (spec §9 task 6, §10 task 1).

Holds the §4.3 payload schema and the payload indexes that make metadata filtering — the
mechanism Path A depends on (§3.1) — actually fast.
"""

import uuid
from typing import Any

import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from recitai.config import settings
from recitai.constants import EMBEDDING_DIM

log = structlog.get_logger(__name__)

#: Qdrant must filter on these (§4.3). Without payload indexes the filter degrades to a
#: full scan, which is precisely the hot path for quiz generation.
INDEXED_PAYLOAD_FIELDS = ("course_id", "topic_id", "document_id")


class VectorStore:
    def __init__(self, url: str | None = None, collection: str | None = None) -> None:
        self.collection = collection or settings.qdrant_collection
        self._client = AsyncQdrantClient(url=url or settings.qdrant_url, timeout=60)

    async def aclose(self) -> None:
        await self._client.close()

    async def ensure_collection(self) -> None:
        if not await self._client.collection_exists(self.collection):
            await self._client.create_collection(
                self.collection,
                vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
            )
            log.info("qdrant.collection_created", collection=self.collection, dim=EMBEDDING_DIM)
        for field in INDEXED_PAYLOAD_FIELDS:
            try:
                await self._client.create_payload_index(
                    self.collection, field_name=field, field_schema=PayloadSchemaType.KEYWORD
                )
            except Exception as exc:  # noqa: BLE001 - index already present is benign
                log.debug("qdrant.index_exists", field=field, detail=str(exc)[:120])

    async def upsert_chunks(self, points: list[PointStruct]) -> None:
        if not points:
            return
        await self._client.upsert(self.collection, points=points)

    async def delete_by_document(self, document_id: uuid.UUID) -> None:
        """Remove a document's vectors so a re-ingest cannot leave orphans behind."""
        await self._client.delete(
            self.collection,
            points_selector=Filter(
                must=[FieldCondition(key="document_id", match=MatchValue(value=str(document_id)))]
            ),
        )

    async def delete_by_course(self, course_id: uuid.UUID) -> None:
        """Remove a whole course's vectors.

        Postgres cascades a course delete down to its chunks, but Qdrant knows nothing
        about that: without this the vectors survive their rows, and a passage that no
        longer exists stays retrievable by chat and explanations.
        """
        await self._client.delete(
            self.collection,
            points_selector=Filter(
                must=[FieldCondition(key="course_id", match=MatchValue(value=str(course_id)))]
            ),
        )

    async def set_topic_for_chunks(self, topic_id: uuid.UUID, chunk_ids: list[uuid.UUID]) -> None:
        """Write `topic_id` into the payload of already-indexed chunks.

        Ingestion writes vectors before the topic tree exists, so every payload starts
        with `topic_id: null`. The resolver's expansion step (§3.2) reads exactly that
        field: left unset, free-text scoping silently degrades to the whole course and
        nothing reports a problem.
        """
        if not chunk_ids:
            return
        await self._client.set_payload(
            self.collection,
            payload={"topic_id": str(topic_id)},
            points=[str(c) for c in chunk_ids],
        )

    async def count(self, course_id: uuid.UUID | None = None) -> int:
        flt = None
        if course_id is not None:
            flt = Filter(
                must=[FieldCondition(key="course_id", match=MatchValue(value=str(course_id)))]
            )
        result = await self._client.count(self.collection, count_filter=flt, exact=True)
        return int(result.count)

    async def search(
        self,
        vector: list[float],
        *,
        course_id: uuid.UUID | None = None,
        document_id: uuid.UUID | None = None,
        topic_ids: list[uuid.UUID] | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Path B (§3.1). Never used to choose chunks for generation."""
        conditions: list[FieldCondition | Filter] = []
        if course_id is not None:
            conditions.append(
                FieldCondition(key="course_id", match=MatchValue(value=str(course_id)))
            )
        if document_id is not None:
            conditions.append(
                FieldCondition(key="document_id", match=MatchValue(value=str(document_id)))
            )
        if topic_ids:
            conditions.append(
                Filter(
                    should=[
                        FieldCondition(key="topic_id", match=MatchValue(value=str(t)))
                        for t in topic_ids
                    ]
                )
            )
        response = await self._client.query_points(
            self.collection,
            query=vector,
            query_filter=Filter(must=conditions) if conditions else None,
            limit=limit,
            with_payload=True,
        )
        return [{"id": p.id, "score": p.score, **(p.payload or {})} for p in response.points]
