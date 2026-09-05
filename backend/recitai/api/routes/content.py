"""Courses, documents and topics (spec §12)."""

import shutil
import uuid
from pathlib import Path

import structlog
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select

from recitai.db.models import Chunk, Course, Document, Topic
from recitai.db.session import session_scope
from recitai.ingestion.pipeline import (
    SUPPORTED_SUFFIXES,
    ingest_file,
    reserve_document,
    uploads_dir,
)
from recitai.llm.ollama import OllamaClient
from recitai.retrieval.topic_map import build_topic_map
from recitai.retrieval.vector_store import VectorStore

log = structlog.get_logger(__name__)
router = APIRouter(tags=["content"])


class CourseIn(BaseModel):
    name: str
    code: str | None = None


class CourseOut(BaseModel):
    id: uuid.UUID
    name: str
    code: str | None = None
    document_count: int = 0
    chunk_count: int = 0


@router.post("/courses", response_model=CourseOut, status_code=201)
async def create_course(payload: CourseIn) -> CourseOut:
    async with session_scope() as session:
        course = Course(name=payload.name, code=payload.code)
        session.add(course)
        await session.flush()
        return CourseOut(id=course.id, name=course.name, code=course.code)


@router.delete("/courses/{course_id}", status_code=204)
async def delete_course(course_id: uuid.UUID) -> None:
    """Delete a course and everything derived from it.

    Postgres cascades to documents, chunks, topics, quizzes, attempts and flashcards; the
    vectors and the uploaded files are outside that guarantee and are cleared here. Doing
    the vector delete first means a failure leaves rows without vectors — recoverable by
    re-ingesting — rather than vectors without rows, which is a silent correctness bug:
    passages that no longer exist would still be retrievable.
    """
    async with session_scope() as session:
        course = await session.get(Course, course_id)
        if course is None:
            raise HTTPException(404, f"no course {course_id}")
        name = course.name

    store = VectorStore()
    try:
        await store.delete_by_course(course_id)
    finally:
        await store.aclose()

    uploads = uploads_dir(course_id, create=False)
    if uploads.exists():
        shutil.rmtree(uploads, ignore_errors=True)

    async with session_scope() as session:
        course = await session.get(Course, course_id)
        if course is not None:
            await session.delete(course)

    log.info("course_deleted", course_id=str(course_id), name=name)


@router.get("/courses", response_model=list[CourseOut])
async def list_courses() -> list[CourseOut]:
    async with session_scope() as session:
        courses = (await session.execute(select(Course).order_by(Course.created_at))).scalars()
        out: list[CourseOut] = []
        for course in courses:
            docs = await session.scalar(
                select(func.count()).select_from(Document).where(Document.course_id == course.id)
            )
            chunks = await session.scalar(
                select(func.count()).select_from(Chunk).where(Chunk.course_id == course.id)
            )
            out.append(
                CourseOut(
                    id=course.id,
                    name=course.name,
                    code=course.code,
                    document_count=int(docs or 0),
                    chunk_count=int(chunks or 0),
                )
            )
        return out


class DocumentOut(BaseModel):
    id: uuid.UUID
    filename: str
    ingest_status: str
    page_count: int | None = None
    chunk_count: int = 0
    ingest_error: str | None = None


async def _ingest_and_map(path: Path, course_id: uuid.UUID, document_id: uuid.UUID) -> None:
    """Ingest, then rebuild the topic tree so the new material is scoped correctly.

    The uploaded file is deliberately *not* deleted: it is what a slide image is rendered
    from (D-017), and it is what a re-ingest would read.
    """
    client, store = OllamaClient(), VectorStore()
    try:
        result = await ingest_file(path, course_id, client, store, document_id=document_id)
        if result.status == "complete":
            await build_topic_map(course_id, store, client=client)
    finally:
        await client.aclose()
        await store.aclose()


@router.post("/courses/{course_id}/documents", response_model=DocumentOut, status_code=202)
async def upload_document(
    course_id: uuid.UUID, background: BackgroundTasks, file: UploadFile = File(...)
) -> DocumentOut:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail=(
                f"no parser for '{suffix}'. Supported: {', '.join(sorted(SUPPORTED_SUFFIXES))}. "
                f"Legacy .ppt, Keynote and Google Slides must be re-saved as .pptx."
            ),
        )
    async with session_scope() as session:
        if await session.get(Course, course_id) is None:
            raise HTTPException(404, f"no course {course_id}")

    # Keep the original name: it is what the student sees in the sidebar, and a temp name
    # told them nothing. Collisions get a numeric suffix rather than overwriting.
    original = Path(file.filename or f"upload{suffix}").name
    destination = uploads_dir(course_id) / original
    counter = 1
    while destination.exists():
        destination = uploads_dir(course_id) / f"{Path(original).stem}-{counter}{suffix}"
        counter += 1
    with destination.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)

    # Reserve the row before returning, so the id handed back is the id that will hold the
    # result and the client can actually poll it.
    document_id = await reserve_document(course_id, destination)
    background.add_task(_ingest_and_map, destination, course_id, document_id)

    return DocumentOut(id=document_id, filename=destination.name, ingest_status="pending")


@router.get("/documents/{document_id}/status", response_model=DocumentOut)
async def document_status(document_id: uuid.UUID) -> DocumentOut:
    async with session_scope() as session:
        document = await session.get(Document, document_id)
        if document is None:
            raise HTTPException(404, f"no document {document_id}")
        chunks = await session.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
        )
        return DocumentOut(
            id=document.id,
            filename=document.filename,
            ingest_status=document.ingest_status,
            page_count=document.page_count,
            chunk_count=int(chunks or 0),
            ingest_error=document.ingest_error,
        )


@router.get("/courses/{course_id}/documents", response_model=list[DocumentOut])
async def list_documents(course_id: uuid.UUID) -> list[DocumentOut]:
    async with session_scope() as session:
        documents = (
            await session.execute(
                select(Document).where(Document.course_id == course_id).order_by(Document.filename)
            )
        ).scalars()
        out = []
        for d in documents:
            chunks = await session.scalar(
                select(func.count()).select_from(Chunk).where(Chunk.document_id == d.id)
            )
            out.append(
                DocumentOut(
                    id=d.id,
                    filename=d.filename,
                    ingest_status=d.ingest_status,
                    page_count=d.page_count,
                    chunk_count=int(chunks or 0),
                    ingest_error=d.ingest_error,
                )
            )
        return out


class TopicOut(BaseModel):
    id: uuid.UUID
    name: str
    chunk_count: int
    parent_topic_id: uuid.UUID | None = None


@router.get("/courses/{course_id}/topics", response_model=list[TopicOut])
async def list_topics(course_id: uuid.UUID) -> list[TopicOut]:
    async with session_scope() as session:
        topics = (
            await session.execute(
                select(Topic).where(Topic.course_id == course_id).order_by(Topic.order_index)
            )
        ).scalars()
        return [
            TopicOut(
                id=t.id,
                name=t.name,
                chunk_count=t.chunk_count,
                parent_topic_id=t.parent_topic_id,
            )
            for t in topics
        ]
