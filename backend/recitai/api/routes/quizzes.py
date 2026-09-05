"""Quiz generation and retrieval (spec §12).

`GET /quizzes/{id}` serves questions **without** correct answers. That strip is the
`PublicQuestion` type in `api/schemas.py`, which has no field able to carry `is_correct`
or `why_wrong` (plan/ISSUES.md I-010) — a leak would be a type error, not a review miss.
"""

import uuid

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from recitai.api.jobs import registry
from recitai.api.schemas import PublicQuiz, to_public_question
from recitai.db.models import Chunk, Question, Quiz
from recitai.db.session import session_scope
from recitai.generation.pipeline import generate_quiz
from recitai.generation.schemas import Difficulty
from recitai.llm.ollama import OllamaClient
from recitai.retrieval.resolver import Scope, resolve_scope
from recitai.retrieval.sampler import scope_size
from recitai.retrieval.vector_store import VectorStore

log = structlog.get_logger(__name__)
router = APIRouter(tags=["quizzes"])


class QuizRequest(BaseModel):
    course_id: uuid.UUID
    topic_ids: list[uuid.UUID] = Field(default_factory=list)
    query: str | None = None
    #: Omitted means "cover the scope" — one question per concept in the selected
    #: material, so the length follows the material rather than a number the student had
    #: to invent.
    n: int | None = Field(default=None, ge=1, le=60)
    difficulty: Difficulty = "recall"
    seed: int | None = None


async def _generate(request: QuizRequest, job_id: uuid.UUID) -> None:
    job = registry.get(job_id)
    assert job is not None
    client, store = OllamaClient(seed=request.seed), VectorStore()
    try:
        job.detail = "resolving scope"
        if request.topic_ids or not request.query:
            scope = Scope(course_id=request.course_id, topic_ids=list(request.topic_ids))
        else:
            # Free text: Path B locates the material, then EXPANDS to whole topics so the
            # sampler covers all of them (§3.2). Never generate from the retrieved chunks.
            scope = await resolve_scope(
                request.course_id, request.query, None, client=client, store=store
            )
        # The job's total is only known once the scope is resolved, when n was not given.
        if request.n is None:
            concepts, _ = await scope_size(scope)
            job.total = concepts
        job.detail = "generating"
        run = await generate_quiz(
            scope, request.n, client, difficulty=request.difficulty, seed=request.seed
        )
        job.progress = run.persisted
        job.result_id = run.quiz_id
        if run.quiz_id is None:
            job.status = "failed"
            job.error = run.sampler_shortfall or "no questions survived validation"
        else:
            job.detail = (
                f"{run.persisted} questions, validator pass rate " f"{run.validator_pass_rate:.0%}"
            )
    finally:
        await client.aclose()
        await store.aclose()


@router.get("/courses/{course_id}/coverage")
async def coverage(course_id: uuid.UUID, topic_ids: str = "") -> dict[str, object]:
    """What a quiz over this selection would cover, before committing to generating it.

    The length of a quiz follows the material, so the student should be able to see it in
    advance rather than discover it when the job finishes.
    """
    ids = [uuid.UUID(t) for t in topic_ids.split(",") if t.strip()]
    concepts, topics = await scope_size(Scope(course_id=course_id, topic_ids=ids))
    return {
        "concepts": concepts,
        "topics": topics,
        # Measured p50 is ~17 s per question, and roughly half need a second attempt.
        "estimated_seconds": concepts * 25,
    }


@router.post("/quizzes", status_code=202)
async def create_quiz(request: QuizRequest) -> dict[str, object]:
    """Generation takes minutes, so this returns a job to poll (§12)."""
    job = registry.create(total=request.n or 0)
    registry.spawn(job, _generate(request, job.id))
    return job.as_dict()


@router.get("/jobs/{job_id}")
async def job_status(job_id: uuid.UUID) -> dict[str, object]:
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(404, f"no job {job_id}")
    return job.as_dict()


@router.get("/quizzes/{quiz_id}", response_model=PublicQuiz)
async def get_quiz(quiz_id: uuid.UUID) -> PublicQuiz:
    """Questions as the student sees them: no correct answers, no rationales."""
    async with session_scope() as session:
        quiz = await session.get(Quiz, quiz_id)
        if quiz is None:
            raise HTTPException(404, f"no quiz {quiz_id}")
        questions = list(
            (
                await session.execute(
                    select(Question)
                    .where(Question.quiz_id == quiz_id)
                    .order_by(Question.order_index)
                )
            )
            .scalars()
            .all()
        )
        # section_path for display comes from the citing chunk, not the model.
        chunk_paths: dict[str, list[str]] = {}
        chunk_ids = {cid for q in questions for cid in q.source_chunk_ids}
        if chunk_ids:
            for chunk in (
                await session.execute(
                    select(Chunk).where(Chunk.id.in_([uuid.UUID(c) for c in chunk_ids]))
                )
            ).scalars():
                chunk_paths[str(chunk.id)] = list(chunk.section_path)

        return PublicQuiz(
            id=quiz.id,
            course_id=quiz.course_id,
            question_count=len(questions),
            difficulty=quiz.difficulty,
            questions=[
                to_public_question(
                    q.id,
                    q.stem,
                    q.options,
                    difficulty=q.difficulty,
                    page_refs=q.page_refs,
                    section_path=chunk_paths.get(
                        q.source_chunk_ids[0] if q.source_chunk_ids else "", []
                    ),
                )
                for q in questions
            ],
        )


@router.get("/courses/{course_id}/quizzes")
async def list_quizzes(course_id: uuid.UUID) -> list[dict[str, object]]:
    async with session_scope() as session:
        quizzes = (
            await session.execute(
                select(Quiz).where(Quiz.course_id == course_id).order_by(Quiz.created_at.desc())
            )
        ).scalars()
        return [
            {
                "id": str(q.id),
                "question_count": q.question_count,
                "difficulty": q.difficulty,
                "created_at": q.created_at.isoformat(),
                "generation_meta": q.generation_meta,
            }
            for q in quizzes
        ]
