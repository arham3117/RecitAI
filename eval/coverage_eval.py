"""Coverage across consecutive quizzes (spec §15 task 5).

**This is the number that proves the Path A design works** (§15), and the one to put in
the README. A similarity-based pipeline cannot guarantee it: embedding a chapter name and
taking the top-k returns the chunks that *say* the chapter name most, so the same few
passages win every time and the rest of the material is never asked about.

Measured without generating anything: the sampler is deterministic and the question is
which chunks it selects, not what the model writes about them.
"""

import asyncio
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from recitai.db.models import Chunk, Course, Topic  # noqa: E402
from recitai.db.session import session_scope  # noqa: E402
from recitai.retrieval.resolver import Scope  # noqa: E402
from recitai.retrieval.sampler import sample_chunks  # noqa: E402

QUIZZES = 5
QUESTIONS_PER_QUIZ = 10


@dataclass
class CoverageMetrics:
    topics_in_course: int
    topics_covered: int
    chunks_in_course: int
    chunks_covered: int
    per_quiz: list[int] = field(default_factory=list)

    @property
    def topic_coverage(self) -> float:
        return self.topics_covered / self.topics_in_course if self.topics_in_course else 0.0

    @property
    def chunk_coverage(self) -> float:
        return self.chunks_covered / self.chunks_in_course if self.chunks_in_course else 0.0

    def report(self) -> str:
        verdict = "PASS" if self.topic_coverage >= 0.90 else "BELOW TARGET"
        return "\n".join(
            [
                f"  quizzes          {QUIZZES} x {QUESTIONS_PER_QUIZ} questions",
                f"  topic coverage   {self.topic_coverage:.0%} "
                f"({self.topics_covered}/{self.topics_in_course})   target >=90%  {verdict}",
                f"  chunk coverage   {self.chunk_coverage:.0%} "
                f"({self.chunks_covered}/{self.chunks_in_course})",
                f"  topics per quiz  {self.per_quiz}",
            ]
        )


async def evaluate(quizzes: int = QUIZZES, n: int = QUESTIONS_PER_QUIZ) -> CoverageMetrics:
    async with session_scope() as session:
        course = await session.scalar(sa.select(Course))
        if course is None:
            raise SystemExit("no ingested course")
        topics = list(
            (await session.execute(sa.select(Topic).where(Topic.course_id == course.id)))
            .scalars()
            .all()
        )
        chunks = list(
            (await session.execute(sa.select(Chunk).where(Chunk.course_id == course.id)))
            .scalars()
            .all()
        )
        # Snapshot usage counts so the measurement can restore them: freshness depends on
        # quiz_usage_count, and an evaluation must not silently reshape future sampling.
        original = {c.id: c.quiz_usage_count for c in chunks}

    scope = Scope(course_id=course.id)
    seen_topics: set[uuid.UUID | None] = set()
    seen_chunks: set[uuid.UUID] = set()
    per_quiz: list[int] = []
    try:
        for i in range(quizzes):
            selected, _ = await sample_chunks(scope, n, seed=i)
            per_quiz.append(len({c.topic_id for c in selected}))
            seen_topics.update(c.topic_id for c in selected)
            seen_chunks.update(c.chunk_id for c in selected)
            # Consecutive quizzes: the freshness term must see the previous one's usage,
            # or every quiz samples identically and coverage is flattered.
            async with session_scope() as session:
                for chunk_id in {c.chunk_id for c in selected}:
                    row = await session.get(Chunk, chunk_id)
                    if row is not None:
                        row.quiz_usage_count += 1
    finally:
        async with session_scope() as session:
            for chunk_id, count in original.items():
                row = await session.get(Chunk, chunk_id)
                if row is not None:
                    row.quiz_usage_count = count

    return CoverageMetrics(
        topics_in_course=len(topics),
        topics_covered=len(seen_topics - {None}),
        chunks_in_course=len(chunks),
        chunks_covered=len(seen_chunks),
        per_quiz=per_quiz,
    )


if __name__ == "__main__":
    print(asyncio.run(evaluate()).report())
