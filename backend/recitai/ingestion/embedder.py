"""Embed chunks and upsert them to Qdrant with the §4.3 payload (spec §9 task 6)."""

import uuid

import structlog
from qdrant_client.models import PointStruct

from recitai.constants import EMBEDDING_BATCH_SIZE, EMBEDDING_DIM
from recitai.ingestion.chunker import TextChunk
from recitai.llm.base import LLMClient
from recitai.retrieval.vector_store import VectorStore

log = structlog.get_logger(__name__)


def build_payload(
    chunk: TextChunk,
    *,
    chunk_id: uuid.UUID,
    document_id: uuid.UUID,
    course_id: uuid.UUID,
    topic_id: uuid.UUID | None = None,
) -> dict[str, object]:
    """The §4.3 chunk metadata payload, exactly."""
    return {
        "chunk_id": str(chunk_id),
        "document_id": str(document_id),
        "course_id": str(course_id),
        "topic_id": str(topic_id) if topic_id else None,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "section_path": chunk.section_path,
        "heading_level": max(0, len(chunk.section_path) - 1),
        "token_count": chunk.token_count,
        "content_type": chunk.content_type,
    }


async def embed_chunks(
    client: LLMClient,
    store: VectorStore,
    chunks: list[TextChunk],
    chunk_ids: list[uuid.UUID],
    *,
    document_id: uuid.UUID,
    course_id: uuid.UUID,
) -> int:
    """Embed and upsert. Returns the number of vectors written."""
    if len(chunks) != len(chunk_ids):
        raise ValueError(f"{len(chunks)} chunks but {len(chunk_ids)} ids")
    if not chunks:
        return 0

    await store.ensure_collection()
    written = 0
    for start in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
        batch = chunks[start : start + EMBEDDING_BATCH_SIZE]
        ids = chunk_ids[start : start + EMBEDDING_BATCH_SIZE]
        vectors = await client.embed([c.text for c in batch])

        if len(vectors) != len(batch):
            raise RuntimeError(f"embedder returned {len(vectors)} vectors for {len(batch)} chunks")
        for vector in vectors:
            if len(vector) != EMBEDDING_DIM:
                raise RuntimeError(
                    f"embedding dim {len(vector)} != EMBEDDING_DIM {EMBEDDING_DIM} — "
                    f"the collection cannot accept it"
                )

        points = [
            PointStruct(
                id=str(cid),
                vector=vec,
                payload=build_payload(
                    chunk, chunk_id=cid, document_id=document_id, course_id=course_id
                ),
            )
            for chunk, cid, vec in zip(batch, ids, vectors, strict=True)
        ]
        await store.upsert_chunks(points)
        written += len(points)
        log.info("embedded", batch=start // EMBEDDING_BATCH_SIZE, written=written)
    return written
