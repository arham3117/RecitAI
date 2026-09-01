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
