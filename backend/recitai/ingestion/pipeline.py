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

from recitai.db.models import Chunk, Course, Document, Question, Quiz
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


async def _discard_derived_questions(document_id: uuid.UUID) -> int:
    """Delete questions whose source chunks belong to a document being re-ingested.

    `questions.source_chunk_ids` is a JSON array, so the database cannot enforce the
    reference: replacing a document's chunks leaves every question generated from it
    citing rows that no longer exist. The student clicks through to the source and finds
    nothing, which is the exact failure invariant I1 exists to prevent — arriving after
    the fact rather than at generation time.

    Deleting them is the honest response. A re-ingest means the passage changed, and this
    project has already seen a case where it changed because the old passage was **wrong**
    (I-027) — questions derived from it should not outlive it. Quizzes left with no
    questions go too.
    """
    async with session_scope() as session:
        chunk_ids = {
            str(cid)
            for cid in (
                await session.execute(select(Chunk.id).where(Chunk.document_id == document_id))
            )
            .scalars()
            .all()
        }
        if not chunk_ids:
            return 0

        questions = list((await session.execute(select(Question))).scalars().all())
        doomed = [q for q in questions if chunk_ids.intersection(q.source_chunk_ids or [])]
        affected_quizzes = {q.quiz_id for q in doomed}
        for question in doomed:
            await session.delete(question)
        await session.flush()

        for quiz_id in affected_quizzes:
            remaining = await session.scalar(
                select(func.count()).select_from(Question).where(Question.quiz_id == quiz_id)
            )
            if not remaining:
                quiz = await session.get(Quiz, quiz_id)
                if quiz is not None:
                    await session.delete(quiz)
        return len(doomed)


def uploads_dir(course_id: uuid.UUID, create: bool = True) -> Path:
    """Where an uploaded file is kept.

    Ingestion used to read from a temp file and delete it, which cost two things: the
    stored filename was the temp name rather than the student's, and the original was gone
    — so a slide image could never be rendered for uploaded material (D-017). Uploads are
    now kept beside the bundled corpus.
    """
    from recitai.config import settings

    root = Path(settings.materials_dir)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[3] / root
    path = root / "uploads" / str(course_id)
    # Deleting a course needs the path without the side effect of creating it.
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


async def reserve_document(course_id: uuid.UUID, path: Path) -> uuid.UUID:
    """Create the document row up front and return its real id.

    The upload endpoint has to hand the client something it can poll. It previously
    returned a freshly minted UUID that matched no row at all, so every status request
    404'd and the interface could not tell the student whether ingestion had finished.
    """
    digest = sha256_file(path)
    async with session_scope() as session:
        existing = await session.scalar(
            select(Document).where(Document.course_id == course_id, Document.sha256 == digest)
        )
        if existing is not None:
            return existing.id
        document = Document(
            course_id=course_id, filename=path.name, sha256=digest, ingest_status="pending"
        )
        session.add(document)
        await session.flush()
        return document.id


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
    document_id: uuid.UUID | None = None,
) -> IngestResult:
    """Ingest one file. `document_id` adopts a row already reserved for it, so the id the
    client is polling stays the id that ends up holding the result."""
    digest = sha256_file(path)

    # --- idempotency (§9 task 8) -------------------------------------------------
    async with session_scope() as session:
        existing = await session.scalar(
            select(Document).where(Document.course_id == course_id, Document.sha256 == digest)
        )
        if existing is not None and existing.id == document_id:
            # The row this run reserved is not a previous ingest to clear away.
            existing = None
        if existing and not force and existing.ingest_status == "complete":
            return IngestResult(
                document_id=existing.id,
                filename=path.name,
                status="skipped",
                page_count=existing.page_count or 0,
                skipped_reason="identical file already ingested",
            )
        existing_id = existing.id if existing else None

    if existing_id is not None:
        # Discard first: `_discard_derived_questions` finds questions by looking up the
        # document's chunks, so deleting the chunks before calling it leaves nothing to
        # match and every derived question survives with a dangling citation. That is
        # exactly what I-030 was written to prevent, and the original fix ran in the wrong
        # order — caught by the invariant test on the first --force re-ingest after it.
        orphaned = await _discard_derived_questions(existing_id)
        if orphaned:
            log.warning(
                "ingest.discarded_stale_questions",
                filename=path.name,
                questions=orphaned,
                reason="their source chunks were replaced by this re-ingest",
            )
        async with session_scope() as session:
            await session.execute(delete(Chunk).where(Chunk.document_id == existing_id))
            doomed = await session.get(Document, existing_id)
            if doomed is not None:
                await session.delete(doomed)
        await store.delete_by_document(existing_id)

    async with session_scope() as session:
        reserved = await session.get(Document, document_id) if document_id else None
        if reserved is not None:
            reserved.ingest_status = "processing"
            document = reserved
        else:
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

        # A course can be deleted while one of its uploads is still being ingested in the
        # background. Postgres cascades the chunk rows away, but the vectors written a
        # moment ago outlive them — leaving passages that no longer exist yet are still
        # retrievable, which is the I2 failure `reconcile_vectors.py` exists to catch.
        async with session_scope() as session:
            doc = await session.get(Document, document_id)
        if doc is None:
            await store.delete_by_document(document_id)
            log.info("ingest_discarded", filename=path.name, reason="course deleted mid-ingest")
            return IngestResult(
                document_id=document_id,
                filename=path.name,
                status="discarded",
                skipped_reason="the course was deleted while this file was being ingested",
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
