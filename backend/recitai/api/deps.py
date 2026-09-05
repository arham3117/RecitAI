"""Shared route guards."""

import uuid

from fastapi import HTTPException

from recitai.db.models import Course
from recitai.db.session import session_scope


async def require_course(course_id: uuid.UUID) -> None:
    """404 unless the course exists.

    Without this a course sub-resource answers 200 with an empty list for a course that
    was never created, so a client cannot tell "you have no topics yet" from "that course
    does not exist" — and a typo in an id looks like an empty course rather than a
    mistake. `POST /documents` already guarded; the read paths did not.
    """
    async with session_scope() as session:
        if await session.get(Course, course_id) is None:
            raise HTTPException(404, f"no course {course_id}")
