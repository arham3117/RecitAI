"""Generator, dedup, and prompt-loader tests.

The LLM is mocked here and only here, through the `LLMClient` protocol (§0.3).
"""

import uuid
from collections.abc import AsyncIterator

import pytest

from recitai.generation.dedup import cosine
from recitai.generation.generator import _is_insufficient, generate_question
from recitai.generation.prompts import load
from recitai.retrieval.sampler import ChunkRef

VALID_QUESTION = """
{"stem": "Which property guarantees every item appears in some fragment?",
 "options": [
   {"id": "A", "text": "Completeness", "is_correct": true, "why_wrong": null},
   {"id": "B", "text": "Disjointness", "is_correct": false, "why_wrong": "confuses overlap"},
   {"id": "C", "text": "Reconstruction", "is_correct": false, "why_wrong": "confuses rebuild"},
   {"id": "D", "text": "Decomposition", "is_correct": false, "why_wrong": "confuses splitting"}],
 "explanation": "The passage defines completeness this way.",
 "difficulty": "recall"}
"""


class FakeLLM:
    """A stand-in for the protocol. Mocking belongs in tests, never in app code."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []

    async def complete(self, prompt: str, **kwargs: object) -> str:
        self.calls.append(prompt)
        return self.responses.pop(0) if self.responses else VALID_QUESTION

    async def stream(self, prompt: str, **kwargs: object) -> AsyncIterator[str]:
        yield ""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # Distinct orthogonal-ish vectors so the overlap check never trips by accident.
        return [[float(i == j) for j in range(768)] for i, _ in enumerate(texts)]


def _chunk() -> ChunkRef:
    return ChunkRef(
        chunk_id=uuid.uuid4(),
        topic_id=uuid.uuid4(),
        text="Decomposition is complete if each data item can be found in some fragment.",
        page_start=9,
        page_end=15,
        section_path=["3-Distribution Design", "Fragmentation"],
        token_count=400,
        quiz_usage_count=0,
    )


# ------------------------------------------------------------------- prompts ----


def test_every_prompt_file_loads_with_both_blocks() -> None:
    for name in (
        "question_generation_v1",
        "validator_judge_v1",
        "explanation_followup_v1",
        "flashcard_generation_v1",
        "topic_naming_v1",
    ):
        prompt = load(name)
        assert prompt.system and prompt.user_template
        assert prompt.version == "v1"


def test_missing_placeholder_raises_rather_than_leaking_into_the_prompt() -> None:
    """An unfilled {placeholder} reads to the model as instruction text."""
    prompt = load("question_generation_v1")
    with pytest.raises(KeyError, match="missing placeholders"):
        prompt.render(course_name="c")


# ------------------------------------------------------------------ citations ----


@pytest.mark.asyncio
async def test_citations_come_from_the_chunk_not_the_model() -> None:
    """I1 and §4.5: asked for its own citations a model invents page numbers, so the
    pipeline attaches them from the sampler's record."""
    chunk = _chunk()
    outcome = await generate_question(
        chunk, "DDB", FakeLLM([VALID_QUESTION]), run_judge_checks=False
    )
    assert outcome.ok
    assert outcome.source_chunk_ids == [str(chunk.chunk_id)]
    assert outcome.page_refs == [9, 10, 11, 12, 13, 14, 15]


@pytest.mark.asyncio
async def test_insufficient_passage_is_skipped_not_failed() -> None:
    """§6.1: generating nothing is the correct outcome for a thin passage (I2)."""
    outcome = await generate_question(
        _chunk(), "DDB", FakeLLM(['{"insufficient": true}']), run_judge_checks=False
    )
    assert not outcome.ok
    assert outcome.skip_reason is not None and "too thin" in outcome.skip_reason


@pytest.mark.asyncio
async def test_malformed_json_is_retried_then_abandoned() -> None:
    """§4.4: retry once with the error appended, then fail the chunk. Nothing malformed
    may reach the database."""
    llm = FakeLLM(["not json at all", "still not json"])
    outcome = await generate_question(_chunk(), "DDB", llm, run_judge_checks=False)
    assert not outcome.ok
    assert outcome.attempts == 2
    assert "invalid" in llm.calls[1], "the retry must tell the model what was wrong"


@pytest.mark.asyncio
async def test_a_rejected_question_is_regenerated_with_the_failure_reasons() -> None:
    """§5.3: failure reasons go back into the prompt."""
    padded = VALID_QUESTION.replace(
        '"text": "Completeness"',
        '"text": "Completeness, meaning that every single data item in the original '
        'relation appears in at least one fragment produced by the decomposition"',
    )
    llm = FakeLLM([padded, VALID_QUESTION])
    outcome = await generate_question(_chunk(), "DDB", llm, run_judge_checks=False)
    assert outcome.ok
    assert outcome.attempts == 2
    assert "LENGTH_BIAS" in llm.calls[1]


def test_insufficient_detection() -> None:
    assert _is_insufficient('{"insufficient": true}')
    assert _is_insufficient('  {"insufficient":  true}  ')
    assert not _is_insufficient(VALID_QUESTION)


# ---------------------------------------------------------------------- dedup ----


def test_cosine_bounds() -> None:
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


# --------------------------------------------------- persisted-content invariants ----


async def _services_or_skip() -> None:
    import asyncpg

    from recitai.db.session import engine

    try:
        async with engine.connect():
            return
    except (asyncpg.CannotConnectNowError, ConnectionRefusedError, OSError) as exc:
        pytest.skip(f"postgres not reachable: {exc}")


@pytest.mark.asyncio
async def test_every_persisted_question_carries_citations() -> None:
    """§11 VERIFY, stated as an assertion: every persisted question must have non-empty
    `source_chunk_ids` and `page_refs`. Invariant I1 — content that cannot cite its source
    is not persisted."""
    import sqlalchemy as sa

    from recitai.db.models import Question
    from recitai.db.session import session_scope

    await _services_or_skip()
    async with session_scope() as session:
        questions = list((await session.execute(sa.select(Question))).scalars().all())
    if not questions:
        pytest.skip("no generated questions yet")

    uncited = [q for q in questions if not q.source_chunk_ids or not q.page_refs]
    assert not uncited, f"{len(uncited)}/{len(questions)} persisted questions lack citations"


@pytest.mark.asyncio
async def test_no_malformed_question_reaches_the_database() -> None:
    """Every stored row must still parse as the schema that produced it, and every
    distractor must carry its rationale."""
    import sqlalchemy as sa

    from recitai.db.models import Question
    from recitai.db.session import session_scope
    from recitai.generation.schemas import GeneratedQuestion

    await _services_or_skip()
    async with session_scope() as session:
        questions = list((await session.execute(sa.select(Question))).scalars().all())
    if not questions:
        pytest.skip("no generated questions yet")

    for row in questions:
        model = GeneratedQuestion.model_validate(
            {
                "stem": row.stem,
                "options": row.options,
                "explanation": row.explanation,
                "difficulty": row.difficulty,
            }
        )
        assert len(model.options) == 4
        assert sum(o.is_correct for o in model.options) == 1
        for distractor in model.distractors:
            assert (distractor.why_wrong or "").strip(), f"{row.id}: distractor has no rationale"


@pytest.mark.asyncio
async def test_cited_pages_exist_in_the_source_document() -> None:
    """A citation naming a page the document does not have is the failure mode I1 exists
    to prevent — it teaches the student to distrust every other citation."""
    import sqlalchemy as sa

    from recitai.db.models import Chunk, Document, Question
    from recitai.db.session import session_scope

    await _services_or_skip()
    async with session_scope() as session:
        questions = list((await session.execute(sa.select(Question))).scalars().all())
        if not questions:
            pytest.skip("no generated questions yet")
        chunks = {str(c.id): c for c in (await session.execute(sa.select(Chunk))).scalars().all()}
        docs = {d.id: d for d in (await session.execute(sa.select(Document))).scalars().all()}

    for q in questions:
        for chunk_id in q.source_chunk_ids:
            chunk = chunks.get(chunk_id)
            assert chunk is not None, f"question {q.id} cites unknown chunk {chunk_id}"
            document = docs[chunk.document_id]
            assert document.page_count is not None
            for page in q.page_refs:
                assert 1 <= page <= document.page_count, (
                    f"question {q.id} cites page {page} of {document.filename}, "
                    f"which has {document.page_count} pages"
                )
            assert chunk.page_start <= min(q.page_refs)
            assert max(q.page_refs) <= chunk.page_end


@pytest.mark.asyncio
async def test_reingesting_a_document_discards_questions_derived_from_it() -> None:
    """Regression: `questions.source_chunk_ids` is a JSON array, so the database cannot
    enforce the reference. A `--force` re-ingest replaced every chunk with new UUIDs and
    left 22 of 39 questions citing rows that no longer existed — a student clicking
    through to the source would find nothing, which is exactly what I1 exists to prevent,
    arriving after generation rather than during it."""

    from recitai.db.models import Chunk, Course, Document, Question, Quiz
    from recitai.db.session import session_scope
    from recitai.ingestion.pipeline import _discard_derived_questions

    await _services_or_skip()

    async with session_scope() as session:
        course = Course(name=f"orphan-probe-{uuid.uuid4()}")
        session.add(course)
        await session.flush()
        document = Document(
            course_id=course.id, filename="p.pptx", sha256="b" * 64, ingest_status="complete"
        )
        session.add(document)
        await session.flush()
        chunk = Chunk(
            document_id=document.id,
            course_id=course.id,
            text="body",
            page_start=1,
            page_end=2,
            section_path=["u", "t"],
            token_count=200,
        )
        session.add(chunk)
        await session.flush()
        quiz = Quiz(course_id=course.id, scope={}, question_count=1, generation_meta={})
        session.add(quiz)
        await session.flush()
        question = Question(
            quiz_id=quiz.id,
            stem="s",
            options=[],
            explanation="e",
            source_chunk_ids=[str(chunk.id)],
            page_refs=[1],
        )
        session.add(question)
        await session.flush()
        document_id, quiz_id, question_id, course_id = (
            document.id,
            quiz.id,
            question.id,
            course.id,
        )

    discarded = await _discard_derived_questions(document_id)
    assert discarded == 1

    async with session_scope() as session:
        assert await session.get(Question, question_id) is None
        assert await session.get(Quiz, quiz_id) is None, "an emptied quiz must go too"
        # clean up
        doomed = await session.get(Course, course_id)
        if doomed is not None:
            await session.delete(doomed)


@pytest.mark.asyncio
async def test_no_question_cites_a_chunk_that_does_not_exist() -> None:
    """The invariant the above protects, asserted over whatever is currently stored."""
    import sqlalchemy as sa

    from recitai.db.models import Chunk, Question
    from recitai.db.session import session_scope

    await _services_or_skip()
    async with session_scope() as session:
        live = {str(c) for c in (await session.execute(sa.select(Chunk.id))).scalars().all()}
        questions = list((await session.execute(sa.select(Question))).scalars().all())
    if not questions:
        pytest.skip("no generated questions yet")

    dangling = [q for q in questions if not set(q.source_chunk_ids or []).issubset(live)]
    assert not dangling, f"{len(dangling)}/{len(questions)} questions cite deleted chunks"


# ------------------------------------------------------------ prompt versioning ----


def test_v2_prompts_are_drop_in_replacements_for_v1() -> None:
    """§6 versions prompts by filename rather than editing in place, so an A/B in Phase 7
    can attribute a quality change to the prompt that caused it. A v2 that needs different
    placeholders is not a swap, it is a rewrite of the call site."""
    for base in ("question_generation", "validator_judge"):
        v1, v2 = load(f"{base}_v1"), load(f"{base}_v2")
        assert v1.placeholders() == v2.placeholders()
        assert v2.version == "v2"


def test_v2_question_prompt_addresses_the_recorded_failures() -> None:
    """I-028: the model invented a "primary" ranking the passage did not state, and wrote
    distractors that the passage also supported. I-029: it asked for a computed count and
    got the arithmetic wrong."""
    text = load("question_generation_v2").system.lower()
    assert "primary" in text and "rank" in text, "I-028: no rule against an invented ranking"
    assert "also be supported" in text or "also supported" in text, "I-028: no self-check"
    assert "compute" in text, "I-029: no rule against asking for a computed quantity"


def test_v2_judge_checks_distractors_against_the_passage() -> None:
    text = load("validator_judge_v2").user_template.lower()
    assert "each of the three distractors" in text
    assert "does not state outright" in text, "I-029: judge must reject unstated numbers"


def test_prompt_selection_is_configuration() -> None:
    """Phase 7 §15 task 7 A/B-tests prompt versions; that must not be a code edit."""
    from recitai.config import settings

    assert settings.question_prompt.startswith("question_generation_v")
    assert settings.judge_prompt.startswith("validator_judge_v")
    load(settings.question_prompt)
    load(settings.judge_prompt)
