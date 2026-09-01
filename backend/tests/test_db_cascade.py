"""Deleting a course must delete what hangs off it.

Needs a live Postgres, so it is skipped when one is not reachable — CI runs lint and the
unit suite without services.
"""

import uuid

import pytest
from sqlalchemy import func, select

from recitai.db.models import Chunk, Course, Document
from recitai.db.session import engine, session_scope

pytestmark = pytest.mark.asyncio


async def _db_available() -> bool:
    try:
        async with engine.connect():
            return True
    except Exception:
        return False


async def test_deleting_a_course_cascades_to_documents_and_chunks() -> None:
    """Regression: without `passive_deletes`, SQLAlchemy issues
    UPDATE documents SET course_id = NULL first, which violates NOT NULL — so a course
    could not be deleted at all."""
    if not await _db_available():
        pytest.skip("postgres not reachable")

    async with session_scope() as session:
        course = Course(name=f"cascade-probe-{uuid.uuid4()}")
        session.add(course)
        await session.flush()
        document = Document(
            course_id=course.id, filename="p.pptx", sha256="a" * 64, ingest_status="complete"
        )
        session.add(document)
        await session.flush()
        session.add(
            Chunk(
                document_id=document.id,
                course_id=course.id,
                text="body",
                page_start=1,
                page_end=1,
                section_path=["u", "t"],
                token_count=10,
            )
        )
        course_id, document_id = course.id, document.id

    async with session_scope() as session:
        doomed = await session.get(Course, course_id)
        assert doomed is not None
        await session.delete(doomed)

    async with session_scope() as session:
        assert await session.get(Course, course_id) is None
        assert await session.get(Document, document_id) is None
        orphans = await session.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.course_id == course_id)
        )
        assert orphans == 0, "chunks outlived their course"
