"""Question deduplication (spec §11 task 6).

Embed stems; reject any with cosine ≥ `MAX_STEM_SIMILARITY` against another question in
the same quiz, or against the last `DEDUP_LOOKBACK_QUIZZES` quizzes for the course.

This matters more on a small corpus than the spec assumes: with ~35 chunks
([I-018](../../plan/ISSUES.md)), the sampler's freshness term rotates toward less-used
chunks exactly as dedup starts rejecting what they produce.
"""

import uuid

import numpy as np
import structlog
from sqlalchemy import desc, select

from recitai.constants import DEDUP_LOOKBACK_QUIZZES, MAX_STEM_SIMILARITY
from recitai.db.models import Question, Quiz
from recitai.db.session import session_scope
from recitai.llm.base import LLMClient

log = structlog.get_logger(__name__)


def cosine(a: list[float], b: list[float]) -> float:
    va, vb = np.array(a, dtype=float), np.array(b, dtype=float)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(va @ vb / (na * nb))


async def recent_stems(course_id: uuid.UUID, limit: int = DEDUP_LOOKBACK_QUIZZES) -> list[str]:
    async with session_scope() as session:
        quiz_ids = list(
            (
                await session.execute(
                    select(Quiz.id)
                    .where(Quiz.course_id == course_id)
                    .order_by(desc(Quiz.created_at))
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        if not quiz_ids:
            return []
        return list(
            (await session.execute(select(Question.stem).where(Question.quiz_id.in_(quiz_ids))))
            .scalars()
            .all()
        )


class Deduplicator:
    """Accumulates accepted stems within a run and checks new ones against them."""

    def __init__(self, client: LLMClient, threshold: float = MAX_STEM_SIMILARITY) -> None:
        self._client = client
        self._threshold = threshold
        self._vectors: list[list[float]] = []
        self._stems: list[str] = []

    async def prime(self, course_id: uuid.UUID) -> None:
        """Load stems from the last few quizzes so a new quiz does not repeat them."""
        stems = await recent_stems(course_id)
        if not stems:
            return
        self._vectors = await self._client.embed(stems)
        self._stems = list(stems)
        log.info("dedup.primed", stems=len(stems))

    async def check(self, stem: str) -> tuple[bool, str | None]:
        """Return (is_duplicate, the stem it duplicates)."""
        vector = (await self._client.embed([stem]))[0]
        for existing_vector, existing_stem in zip(self._vectors, self._stems, strict=True):
            if cosine(vector, existing_vector) >= self._threshold:
                return True, existing_stem
        self._vectors.append(vector)
        self._stems.append(stem)
        return False, None
