"""Attempts, grading, and the explanation loop (spec §12).

**The answer-submission response is the product's core moment** (§12). It returns
everything needed to render the explanation with zero further round trips: what the
student chose, why that specific choice was wrong, why the right answer is right, and the
source passage with its page. Anything missing here becomes a spinner at exactly the
moment the student is most likely to give up.
"""

import json
import re
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import structlog
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sse_starlette.sse import EventSourceResponse

from recitai.config import settings
from recitai.db.models import (
    Answer,
    Attempt,
    Chunk,
    Course,
    Document,
    Question,
    Quiz,
    TopicMastery,
)
from recitai.db.session import session_scope
from recitai.generation.prompts import load
from recitai.ingestion.slide_images import availability, render_slide
from recitai.learning.mastery import promote_missed_question, update_mastery
from recitai.llm.ollama import OllamaClient
from recitai.retrieval.search import search
from recitai.retrieval.vector_store import VectorStore

log = structlog.get_logger(__name__)
router = APIRouter(tags=["attempts"])

#: How many passages a chat answer is grounded in. Enough for a question spanning two
#: slides, few enough to fit an 8B model's context alongside the answer it has to write.
CHAT_PASSAGES = 5


#: The repository root, derived from this file rather than from the working directory —
#: the API is started from backend/ but the material lives beside it, and resolving a
#: relative path against the CWD silently found nothing.
_REPO_ROOT = Path(__file__).resolve().parents[4]


def _material_path(filename: str) -> Path | None:
    """Locate the original file a chunk came from.

    Ingestion does not keep the upload, so the deck is looked up by name in the configured
    material directory. Absent means no picture, which the API says plainly rather than
    failing opaquely.
    """
    configured = Path(settings.materials_dir)
    bases = [configured] if configured.is_absolute() else [configured, _REPO_ROOT / configured]
    for base in bases:
        candidate = base / filename
        if candidate.exists():
            return candidate
        # Uploaded material lives under uploads/<course id>/, so search those too rather
        # than only the bundled corpus.
        uploads = base / "uploads"
        if uploads.is_dir():
            for found in uploads.glob(f"*/{filename}"):
                return found
    return None


class AttemptIn(BaseModel):
    quiz_id: uuid.UUID
    #: Discard an unfinished attempt and begin again.
    restart: bool = False


class AttemptOut(BaseModel):
    id: uuid.UUID
    quiz_id: uuid.UUID
    started_at: datetime
    #: Questions already answered in this attempt, so the client can pick up where the
    #: student left off rather than starting again.
    answered_question_ids: list[uuid.UUID] = Field(default_factory=list)
    resumed: bool = False


class SlideOut(BaseModel):
    """One slide's worth of the cited passage."""

    page: int
    heading: str | None
    text: str
    #: Where to fetch a picture of this slide, when one can be produced.
    image_url: str | None = None


class SourceOut(BaseModel):
    text: str
    page: int
    #: The passage usually spans several merged slides (D-009). Reporting only the first
    #: told the student "slide 48" while showing them four slides' text.
    page_end: int
    slides: list[SlideOut]
    section_path: list[str]
    document_name: str
    #: "pdf" | "companion-pdf" | "libreoffice" | "unavailable" — so the UI can explain
    #: why there is no picture instead of silently showing none.
    images: str = "unavailable"


#: Chunks store each merged slide behind a "### " heading (see ingestion.chunker). That is
#: a storage detail, not something to put in front of a student.
_SLIDE_HEADING = re.compile(r"^###\s+(.*)$", re.M)


def split_passage_by_slide(text: str, page_start: int, page_end: int) -> list[SlideOut]:
    """Split a merged passage back into the slides it came from.

    A passage usually spans several slides (D-009 merges them to reach a workable size), so
    showing it as one block under a single slide number is misleading — and the "### "
    markers that separate them are storage syntax leaking into the interface.
    """
    parts = _SLIDE_HEADING.split(text)
    # split() yields [preamble, heading, body, heading, body, ...]
    preamble = parts[0].strip()
    pairs = [(parts[i].strip(), parts[i + 1].strip()) for i in range(1, len(parts) - 1, 2)]

    slides: list[SlideOut] = []
    if preamble and not pairs:
        return [SlideOut(page=page_start, heading=None, text=preamble)]
    if preamble:
        slides.append(SlideOut(page=page_start, heading=None, text=preamble))

    for index, (heading, body) in enumerate(pairs):
        # Slide numbers are approximate within a merged passage: the chunker records the
        # range, not a number per heading. Reporting the range is honest; inventing a
        # precise number per slide would not be.
        page = min(page_start + index, page_end)
        cleaned = "\n".join(line.rstrip() for line in body.splitlines() if line.strip())
        slides.append(SlideOut(page=page, heading=heading or None, text=cleaned))
    return slides


@router.post("/attempts", response_model=AttemptOut, status_code=201)
async def start_attempt(payload: AttemptIn) -> AttemptOut:
    """Resume an unfinished attempt, or begin a new one.

    Leaving a quiz part-way used to strand the answers: coming back created a fresh
    attempt at question one, and re-answering the same questions updated `topic_mastery`
    a second time — so abandoning a quiz quietly skewed the sampler's weakness term.
    Resuming is therefore the default, and starting over is the explicit choice.
    """
    async with session_scope() as session:
        quiz = await session.get(Quiz, payload.quiz_id)
        if quiz is None:
            raise HTTPException(404, f"no quiz {payload.quiz_id}")
        total = await session.scalar(
            select(func.count()).select_from(Question).where(Question.quiz_id == payload.quiz_id)
        )

        existing = None
        if not payload.restart:
            existing = await session.scalar(
                select(Attempt)
                .where(Attempt.quiz_id == payload.quiz_id, Attempt.completed_at.is_(None))
                .order_by(Attempt.started_at.desc())
                .limit(1)
            )

        if existing is not None:
            answered = list(
                (
                    await session.execute(
                        select(Answer.question_id).where(Answer.attempt_id == existing.id)
                    )
                )
                .scalars()
                .all()
            )
            # An attempt with every question answered is finished in all but name; a new
            # run should start clean rather than resume into nothing.
            if len(answered) < int(total or 0):
                return AttemptOut(
                    id=existing.id,
                    quiz_id=existing.quiz_id,
                    started_at=existing.started_at,
                    answered_question_ids=answered,
                    resumed=len(answered) > 0,
                )

        attempt = Attempt(quiz_id=payload.quiz_id)
        session.add(attempt)
        await session.flush()
        return AttemptOut(id=attempt.id, quiz_id=attempt.quiz_id, started_at=attempt.started_at)


class AnswerIn(BaseModel):
    question_id: uuid.UUID
    selected_option_id: str | None = None
    time_taken_ms: int | None = None


class AnswerOut(BaseModel):
    """§12's payload, verbatim in shape. Everything the explanation panel needs."""

    is_correct: bool
    correct_option_id: str
    selected_option_id: str | None
    why_wrong: str | None
    explanation: str
    source: SourceOut | None


@router.post("/attempts/{attempt_id}/answers", response_model=AnswerOut)
async def submit_answer(attempt_id: uuid.UUID, payload: AnswerIn) -> AnswerOut:
    async with session_scope() as session:
        attempt = await session.get(Attempt, attempt_id)
        if attempt is None:
            raise HTTPException(404, f"no attempt {attempt_id}")
        question = await session.get(Question, payload.question_id)
        if question is None:
            raise HTTPException(404, f"no question {payload.question_id}")

        options = question.options
        correct = next((o for o in options if o.get("is_correct")), None)
        if correct is None:
            # Every persisted question passed the validator's schema check, so this means
            # the row was corrupted after the fact — surface it rather than guess.
            raise HTTPException(500, f"question {question.id} has no correct option")
        chosen = next((o for o in options if o["id"] == payload.selected_option_id), None)
        is_correct = bool(chosen and chosen.get("is_correct"))

        session.add(
            Answer(
                attempt_id=attempt_id,
                question_id=question.id,
                selected_option_id=payload.selected_option_id,
                is_correct=is_correct,
                time_taken_ms=payload.time_taken_ms,
            )
        )
        await update_mastery(session, question, is_correct)

        # §13 task 4: a missed question becomes a flashcard. Done after the answer is
        # recorded so a promotion failure cannot lose the answer itself.
        promoted = None
        if not is_correct:
            promoted = question

        # The source passage, resolved from the question's own citation (§17: always
        # prefer the question's source_chunk_ids over a fresh search).
        source: SourceOut | None = None
        if question.source_chunk_ids:
            chunk = await session.get(Chunk, uuid.UUID(question.source_chunk_ids[0]))
            if chunk is not None:
                document = await session.get(Document, chunk.document_id)
                slides = split_passage_by_slide(chunk.text, chunk.page_start, chunk.page_end)
                kind = "unavailable"
                if document is not None:
                    path = _material_path(document.filename)
                    if path is not None:
                        kind = availability(path)
                        if kind != "unavailable":
                            for slide in slides:
                                slide.image_url = (
                                    f"/api/documents/{document.id}/slides/{slide.page}.png"
                                )
                source = SourceOut(
                    text="\n\n".join(s.text for s in slides)[:2000],
                    page=chunk.page_start,
                    page_end=chunk.page_end,
                    slides=slides,
                    section_path=list(chunk.section_path),
                    document_name=document.filename if document else "unknown",
                    images=kind,
                )

        response = AnswerOut(
            is_correct=is_correct,
            correct_option_id=str(correct["id"]),
            selected_option_id=payload.selected_option_id,
            why_wrong=None if is_correct else (chosen or {}).get("why_wrong"),
            explanation=question.explanation,
            source=source,
        )

    # Promoted after the answer transaction commits, so a promotion failure can never
    # lose the answer itself (§13 task 4).
    if promoted is not None:
        await promote_missed_question(promoted)
    return response


@router.get("/documents/{document_id}/slides/{page}.png")
async def slide_image(document_id: uuid.UUID, page: int) -> Response:
    """A picture of one slide (§14 — the source panel is where the value lands).

    The extracted text says what a slide states; it cannot show a diagram, and 12% of
    slides in this corpus are diagram-only. Cached on disk after the first render.
    """
    async with session_scope() as session:
        document = await session.get(Document, document_id)
        if document is None:
            raise HTTPException(404, f"no document {document_id}")
        filename = document.filename

    path = _material_path(filename)
    if path is None:
        raise HTTPException(404, f"the source file for {filename} is no longer on disk")
    png = render_slide(path, page)
    if png is None:
        raise HTTPException(
            404,
            f"no image available for {filename} slide {page}. Export the deck to PDF beside "
            f"it (File → Save as PDF), or install LibreOffice, and it will appear.",
        )
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/quizzes/{quiz_id}/progress")
async def quiz_progress(quiz_id: uuid.UUID) -> dict[str, object]:
    """How far through this quiz the student is, if they are part-way."""
    async with session_scope() as session:
        total = int(
            await session.scalar(
                select(func.count()).select_from(Question).where(Question.quiz_id == quiz_id)
            )
            or 0
        )
        attempt = await session.scalar(
            select(Attempt)
            .where(Attempt.quiz_id == quiz_id, Attempt.completed_at.is_(None))
            .order_by(Attempt.started_at.desc())
            .limit(1)
        )
        answered = 0
        if attempt is not None:
            answered = int(
                await session.scalar(
                    select(func.count()).select_from(Answer).where(Answer.attempt_id == attempt.id)
                )
                or 0
            )
    return {
        "total": total,
        "answered": answered if answered < total else 0,
        "in_progress": 0 < answered < total,
    }


@router.get("/attempts/{attempt_id}/results")
async def attempt_results(attempt_id: uuid.UUID) -> dict[str, object]:
    async with session_scope() as session:
        attempt = await session.get(Attempt, attempt_id)
        if attempt is None:
            raise HTTPException(404, f"no attempt {attempt_id}")
        answers = list(
            (await session.execute(select(Answer).where(Answer.attempt_id == attempt_id)))
            .scalars()
            .all()
        )
        correct = sum(1 for a in answers if a.is_correct)
        score = correct / len(answers) if answers else 0.0

        attempt.completed_at = datetime.now(UTC)
        attempt.score = score

        # Per-topic breakdown (§12), from the questions actually answered.
        by_topic: dict[str, dict[str, int]] = {}
        for answer in answers:
            question = await session.get(Question, answer.question_id)
            if question is None or question.topic_id is None:
                continue
            key = str(question.topic_id)
            bucket = by_topic.setdefault(key, {"answered": 0, "correct": 0})
            bucket["answered"] += 1
            bucket["correct"] += 1 if answer.is_correct else 0

        return {
            "attempt_id": str(attempt_id),
            "answered": len(answers),
            "correct": correct,
            "score": round(score, 3),
            "per_topic": by_topic,
        }


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    #: Restrict to selected topics; empty means the whole course.
    topic_ids: list[uuid.UUID] = Field(default_factory=list)


@router.post("/courses/{course_id}/chat")
async def chat(course_id: uuid.UUID, payload: ChatIn) -> EventSourceResponse:
    """Ask a question about the course material (v2 — see plan/DECISIONS.md D-018).

    This is **Path B**: a real query with semantics, which is exactly what §3.1 reserves
    similarity search for. It is not Path A, and nothing here influences what a student is
    quizzed on.

    Invariant I2 holds — the model is given passages and told it has no other knowledge.
    I1 holds too: the passages are sent to the client *before* the answer starts, with
    their slides, so a claim can be traced the moment it appears.
    """
    client, store = OllamaClient(), VectorStore()
    try:
        hits = await search(
            payload.message,
            client,
            store,
            course_id=course_id,
            topic_ids=list(payload.topic_ids) or None,
            limit=CHAT_PASSAGES,
        )
    finally:
        await store.aclose()

    async with session_scope() as session:
        course = await session.get(Course, course_id)
        course_name = course.name if course else "this course"
        chunks: list[Chunk] = []
        for hit in hits:
            chunk = await session.get(Chunk, hit.chunk_id)
            if chunk is not None:
                chunks.append(chunk)
        documents: dict[uuid.UUID, Document | None] = {}
        for chunk in chunks:
            if chunk.document_id not in documents:
                documents[chunk.document_id] = await session.get(Document, chunk.document_id)

    sources: list[dict[str, object]] = []
    for index, chunk in enumerate(chunks):
        document = documents.get(chunk.document_id)
        image_url = None
        if document is not None:
            path = _material_path(document.filename)
            if path is not None and availability(path) != "unavailable":
                image_url = f"/api/documents/{document.id}/slides/{chunk.page_start}.png"
        sources.append(
            {
                "n": index + 1,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "section_path": list(chunk.section_path),
                "document_name": document.filename if document else "unknown",
                "image_url": image_url,
            }
        )

    if not chunks:

        async def empty() -> AsyncIterator[dict[str, str]]:
            yield {"event": "sources", "data": json.dumps([])}
            yield {
                "data": (
                    "There is nothing in this course's material about that. Try rephrasing, "
                    "or ask about one of the topics in the sidebar."
                )
            }
            yield {"event": "done", "data": ""}

        await client.aclose()
        return EventSourceResponse(empty())

    prompt = load("chat_answer_v1")
    passages = "\n\n".join(
        f"[{i + 1}] (slide {c.page_start}"
        + (f"-{c.page_end}" if c.page_end != c.page_start else "")
        + f", {' > '.join(c.section_path)})\n{c.text}"
        for i, c in enumerate(chunks)
    )
    rendered = prompt.render(course_name=course_name, passages=passages, question=payload.message)

    async def stream() -> AsyncIterator[dict[str, str]]:
        try:
            # Sources first: the student sees what the answer will be built from before a
            # word of it arrives, which is the point of citing at all.
            yield {"event": "sources", "data": json.dumps(sources)}
            async for piece in client.stream(rendered, system=prompt.system):
                yield {"data": piece}
            yield {"event": "done", "data": ""}
        finally:
            await client.aclose()

    return EventSourceResponse(stream())


class FollowUpIn(BaseModel):
    followup: str


@router.post("/questions/{question_id}/explain")
async def explain(question_id: uuid.UUID, payload: FollowUpIn) -> EventSourceResponse:
    """Streamed follow-up (§12, §6.3).

    The student's specific misconception is passed into the prompt — that is what makes
    this better than a generic re-explanation (§6.3).
    """
    async with session_scope() as session:
        question = await session.get(Question, question_id)
        if question is None:
            raise HTTPException(404, f"no question {question_id}")
        options = question.options
        correct = next((o for o in options if o.get("is_correct")), {})
        wrong = next((o for o in options if not o.get("is_correct")), {})
        chunk = (
            await session.get(Chunk, uuid.UUID(question.source_chunk_ids[0]))
            if question.source_chunk_ids
            else None
        )
        stem, explanation = question.stem, question.explanation
        pages = question.page_refs

    prompt = load("explanation_followup_v1")
    rendered = prompt.render(
        section_path=" > ".join(chunk.section_path) if chunk else "",
        page=pages[0] if pages else "?",
        chunk_text=chunk.text if chunk else explanation,
        stem=stem,
        chosen_option_text=wrong.get("text", ""),
        why_wrong=wrong.get("why_wrong", ""),
        correct_option_text=correct.get("text", ""),
        followup=payload.followup,
    )

    async def stream() -> AsyncIterator[dict[str, str]]:
        client = OllamaClient()
        try:
            async for piece in client.stream(rendered, system=prompt.system):
                yield {"data": piece}
            yield {"event": "done", "data": ""}
        finally:
            await client.aclose()

    return EventSourceResponse(stream())


@router.get("/courses/{course_id}/mastery")
async def course_mastery(course_id: uuid.UUID) -> list[dict[str, object]]:
    async with session_scope() as session:
        rows = (
            await session.execute(select(TopicMastery).where(TopicMastery.course_id == course_id))
        ).scalars()
        return [
            {
                "topic_id": str(m.topic_id),
                "attempts": m.attempts_count,
                "correct": m.correct_count,
                "accuracy": m.accuracy,
            }
            for m in rows
        ]


@router.get("/health")
async def health() -> dict[str, object]:
    async with session_scope() as session:
        chunks = await session.scalar(select(func.count()).select_from(Chunk))
    return {"status": "ok", "chunks": int(chunks or 0)}
