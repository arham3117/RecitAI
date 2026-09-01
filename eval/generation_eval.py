"""Generation quality and groundedness (spec §15 tasks 3–4, 6).

Scored over what is already persisted rather than by generating afresh, so the report is
reproducible and cheap. The validator's own report is stored per question (§5.4), which
makes the pass rate a fact rather than a re-derivation.
"""

import asyncio
import re
import statistics as st
import sys
from dataclasses import dataclass, field
from pathlib import Path

import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from recitai.db.models import Chunk, Document, Question, Quiz  # noqa: E402
from recitai.db.session import session_scope  # noqa: E402

#: A word must be at least this long to count as evidence of overlap; "the" proves nothing.
MIN_EVIDENCE_WORD = 5


@dataclass
class GenerationMetrics:
    questions: int
    quizzes: int
    validator_pass_rate: float
    failure_codes: dict[str, int] = field(default_factory=dict)
    with_citations: int = 0
    resolvable_citations: int = 0
    pages_in_range: int = 0
    grounded_explanations: int = 0
    audited: int = 0
    mean_overlap: float = 0.0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0

    def report(self) -> str:
        def pct(a: int, b: int) -> str:
            return f"{(a / b * 100) if b else 0:.0f}%"

        return "\n".join(
            [
                f"  questions        {self.questions} across {self.quizzes} quiz(zes)",
                f"  validator pass   {self.validator_pass_rate:.0%}",
                f"  rejections       {self.failure_codes or '{}'}",
                "",
                "  invariant I1 — groundedness",
                f"    carry citations       {self.with_citations}/{self.questions} "
                f"({pct(self.with_citations, self.questions)})",
                f"    citations resolvable  {self.resolvable_citations}/{self.questions} "
                f"({pct(self.resolvable_citations, self.questions)})",
                f"    cited page in range   {self.pages_in_range}/{self.questions} "
                f"({pct(self.pages_in_range, self.questions)})",
                "",
                "  groundedness audit (§15 task 4)",
                f"    explanations audited  {self.audited}",
                f"    supported by source   {self.grounded_explanations}/{self.audited} "
                f"({pct(self.grounded_explanations, self.audited)})",
                f"    mean lexical overlap  {self.mean_overlap:.0%}",
                "",
                "  latency (§15 task 6)",
                f"    per question p50      {self.latency_p50_ms / 1000:.1f}s",
                f"    per question p95      {self.latency_p95_ms / 1000:.1f}s",
            ]
        )


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= MIN_EVIDENCE_WORD}


async def evaluate(audit_sample: int = 20) -> GenerationMetrics:
    async with session_scope() as session:
        quizzes = list((await session.execute(sa.select(Quiz))).scalars().all())
        questions = list((await session.execute(sa.select(Question))).scalars().all())
        chunks = {str(c.id): c for c in (await session.execute(sa.select(Chunk))).scalars()}
        documents = {d.id: d for d in (await session.execute(sa.select(Document))).scalars()}

    if not questions:
        raise SystemExit("no generated questions — run `recitai generate` first")

    codes: dict[str, int] = {}
    passes = 0
    latencies: list[float] = []
    for quiz in quizzes:
        meta = quiz.generation_meta or {}
        for code, count in (meta.get("failure_codes") or {}).items():
            codes[code] = codes.get(code, 0) + int(count)
        rate = meta.get("validator_pass_rate")
        if rate is not None:
            passes += float(rate) * quiz.question_count
        duration = meta.get("duration_ms")
        attempts = meta.get("total_attempts") or quiz.question_count
        if duration and attempts:
            latencies.append(float(duration) / float(attempts))

    with_citations = sum(1 for q in questions if q.source_chunk_ids and q.page_refs)
    resolvable = sum(
        1 for q in questions if q.source_chunk_ids and all(c in chunks for c in q.source_chunk_ids)
    )
    in_range = 0
    for question in questions:
        if not question.source_chunk_ids or not question.page_refs:
            continue
        chunk = chunks.get(question.source_chunk_ids[0])
        if chunk is None:
            continue
        document = documents.get(chunk.document_id)
        if document is None or document.page_count is None:
            continue
        if all(1 <= p <= document.page_count for p in question.page_refs) and (
            chunk.page_start <= min(question.page_refs)
            and max(question.page_refs) <= chunk.page_end
        ):
            in_range += 1

    # §15 task 4: is each explanation actually supported by the chunk it cites? Lexical
    # overlap is a weak proxy for entailment, but it is deterministic and it catches the
    # failure that matters — an explanation about something the passage never mentions.
    sample = questions[:audit_sample]
    overlaps: list[float] = []
    grounded = 0
    for question in sample:
        chunk = chunks.get(question.source_chunk_ids[0]) if question.source_chunk_ids else None
        if chunk is None:
            continue
        explanation_words = _words(question.explanation)
        if not explanation_words:
            continue
        shared = explanation_words & _words(chunk.text)
        overlap = len(shared) / len(explanation_words)
        overlaps.append(overlap)
        if overlap >= 0.30:
            grounded += 1

    return GenerationMetrics(
        questions=len(questions),
        quizzes=len(quizzes),
        validator_pass_rate=passes / len(questions) if questions else 0.0,
        failure_codes=codes,
        with_citations=with_citations,
        resolvable_citations=resolvable,
        pages_in_range=in_range,
        grounded_explanations=grounded,
        audited=len(overlaps),
        mean_overlap=st.mean(overlaps) if overlaps else 0.0,
        latency_p50_ms=st.median(latencies) if latencies else 0.0,
        latency_p95_ms=max(latencies) if latencies else 0.0,
    )


if __name__ == "__main__":
    print(asyncio.run(evaluate()).report())
