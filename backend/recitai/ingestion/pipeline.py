"""Ingestion orchestration (spec §9).

parse → clean → chunk → persist → embed, with the document row tracking status the whole
way. Failures set `ingest_status='failed'` with the reason and re-raise: a document that
half-ingested must say so rather than looking complete (§0.2).

Idempotency (§9 task 8): re-ingesting a file whose sha256 already exists in the course is
a no-op.
"""

import uuid
from dataclasses import dataclass
from pathlib import Path

import structlog
from sqlalchemy import delete, func, select

from recitai.db.models import Chunk, Course, Document
from recitai.db.session import session_scope
from recitai.ingestion.chunker import chunk_document
from recitai.ingestion.cleaner import clean
from recitai.ingestion.embedder import embed_chunks
from recitai.ingestion.parser import PARSERS, parse, sha256_file
from recitai.llm.base import LLMClient
from recitai.retrieval.vector_store import VectorStore

log = structlog.get_logger(__name__)

SUPPORTED_SUFFIXES = frozenset(PARSERS)


@dataclass
class IngestResult:
    document_id: uuid.UUID
    filename: str
    status: str
    page_count: int = 0
    chunk_count: int = 0
    vectors_written: int = 0
    skipped_reason: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in {"complete", "skipped"}


async def get_or_create_course(name: str, code: str | None = None) -> uuid.UUID:
    async with session_scope() as session:
        existing = await session.scalar(select(Course).where(Course.name == name))
        if existing:
            return existing.id
        course = Course(name=name, code=code)
        session.add(course)
        await session.flush()
        return course.id


async def ingest_file(
    path: Path,
    course_id: uuid.UUID,
    client: LLMClient,
    store: VectorStore,
    *,
    force: bool = False,
) -> IngestResult:
    digest = sha256_file(path)

    # --- idempotency (§9 task 8) -------------------------------------------------
    async with session_scope() as session:
        existing = await session.scalar(
            select(Document).where(Document.course_id == course_id, Document.sha256 == digest)
        )
        if existing and not force:
            if existing.ingest_status == "complete":
                return IngestResult(
                    document_id=existing.id,
                    filename=path.name,
                    status="skipped",
                    page_count=existing.page_count or 0,
                    skipped_reason="identical file already ingested",
                )
            # A previous run failed or died midway; clear it and start over rather than
            # leaving a half-populated document in place.
            await session.execute(delete(Chunk).where(Chunk.document_id == existing.id))
            await session.delete(existing)
        elif existing and force:
            await session.execute(delete(Chunk).where(Chunk.document_id == existing.id))
            await session.delete(existing)

    if existing is not None:
        await store.delete_by_document(existing.id)

    async with session_scope() as session:
        document = Document(
            course_id=course_id,
            filename=path.name,
            sha256=digest,
            ingest_status="processing",
        )
        session.add(document)
        await session.flush()
        document_id = document.id

    try:
        parsed = clean(parse(path))
        chunks = chunk_document(parsed, unit_name=path.stem)
        if not chunks:
            raise ValueError(
                f"{path.name}: parsed {parsed.page_count} pages but produced no chunks"
            )

        chunk_ids = [uuid.uuid4() for _ in chunks]
        async with session_scope() as session:
            session.add_all(
                [
                    Chunk(
                        id=cid,
                        document_id=document_id,
                        course_id=course_id,
                        text=c.text,
                        page_start=c.page_start,
                        page_end=c.page_end,
                        section_path=c.section_path,
                        token_count=c.token_count,
                        content_type=c.content_type,
                        vector_id=str(cid),
                    )
                    for c, cid in zip(chunks, chunk_ids, strict=True)
                ]
            )

        written = await embed_chunks(
            client, store, chunks, chunk_ids, document_id=document_id, course_id=course_id
        )

        async with session_scope() as session:
            doc = await session.get(Document, document_id)
            assert doc is not None
            doc.page_count = parsed.page_count
            doc.ingest_status = "complete"

        log.info(
            "ingested",
            filename=path.name,
            pages=parsed.page_count,
            chunks=len(chunks),
            vectors=written,
        )
        return IngestResult(
            document_id=document_id,
            filename=path.name,
            status="complete",
            page_count=parsed.page_count,
            chunk_count=len(chunks),
            vectors_written=written,
        )

    except Exception as exc:
        # Record the failure against the document, then re-raise the detail to the caller.
        async with session_scope() as session:
            doc = await session.get(Document, document_id)
            if doc is not None:
                doc.ingest_status = "failed"
                doc.ingest_error = f"{type(exc).__name__}: {exc}"[:2000]
        log.error("ingest_failed", filename=path.name, error=str(exc))
        return IngestResult(
            document_id=document_id,
            filename=path.name,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
        )


def discover(target: Path) -> list[Path]:
    """A file, or every supported document in a directory (I-015)."""
    if target.is_file():
        return [target]
    found = sorted(
        p
        for p in target.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES and not p.name.startswith("~$")
    )
    return found


async def ingest(
    target: Path, course_name: str, client: LLMClient, store: VectorStore, *, force: bool = False
) -> list[IngestResult]:
    paths = discover(target)
    if not paths:
        raise FileNotFoundError(
            f"no supported documents under {target} "
            f"(looking for {', '.join(sorted(SUPPORTED_SUFFIXES))})"
        )
    course_id = await get_or_create_course(course_name)
    return [await ingest_file(p, course_id, client, store, force=force) for p in paths]


async def course_chunk_count(course_id: uuid.UUID) -> int:
    async with session_scope() as session:
        total = await session.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.course_id == course_id)
        )
        return int(total or 0)
