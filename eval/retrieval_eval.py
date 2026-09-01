"""Retrieval metrics (spec §15 task 2): recall@k and MRR over the golden set.

Measures **Path B only**. Path A never runs a similarity search, so recall is not the
property that matters for quiz generation — coverage is, and that is `coverage_eval.py`.
"""

import asyncio
import json
import statistics as st
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from recitai.constants import DEFAULT_TOP_K  # noqa: E402
from recitai.db.models import Chunk, Course  # noqa: E402
from recitai.db.session import session_scope  # noqa: E402
from recitai.llm.ollama import OllamaClient  # noqa: E402
from recitai.retrieval.search import search  # noqa: E402
from recitai.retrieval.vector_store import VectorStore  # noqa: E402

GOLDEN = Path(__file__).parent / "golden_set.jsonl"


@dataclass
class RetrievalMetrics:
    queries: int
    recall_at_k: float
    mrr: float
    k: int
    misses: list[str]

    def report(self) -> str:
        lines = [
            f"  queries          {self.queries}",
            f"  recall@{self.k}         {self.recall_at_k:.2f}",
            f"  MRR              {self.mrr:.3f}",
        ]
        if self.misses:
            lines.append(f"  misses           {len(self.misses)}")
            lines += [f"    - {m[:70]}" for m in self.misses[:5]]
        return "\n".join(lines)


async def evaluate(k: int = DEFAULT_TOP_K) -> RetrievalMetrics:
    rows = [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]
    async with session_scope() as session:
        course = await session.scalar(sa.select(Course))
        if course is None:
            raise SystemExit("no ingested course — run `make ingest` first")
        chunks = list(
            (await session.execute(sa.select(Chunk).where(Chunk.course_id == course.id)))
            .scalars()
            .all()
        )
    by_section: dict[tuple[str, ...], uuid.UUID] = {
        tuple(c.section_path): c.id for c in chunks
    }

    client, store = OllamaClient(), VectorStore()
    hits, reciprocal, misses, counted = 0, [], [], 0
    try:
        for row in rows:
            expected = by_section.get(tuple(row["source_section"]))
            if expected is None:
                # The golden set is keyed on section path so it survives re-ingest; a pair
                # whose section no longer exists is skipped rather than scored as a miss.
                continue
            counted += 1
            results = await search(row["query"], client, store, course_id=course.id, limit=k)
            ids = [r.chunk_id for r in results]
            if expected in ids:
                hits += 1
                reciprocal.append(1 / (ids.index(expected) + 1))
            else:
                reciprocal.append(0.0)
                misses.append(row["query"])
    finally:
        await client.aclose()
        await store.aclose()

    return RetrievalMetrics(
        queries=counted,
        recall_at_k=hits / counted if counted else 0.0,
        mrr=st.mean(reciprocal) if reciprocal else 0.0,
        k=k,
        misses=misses,
    )


if __name__ == "__main__":
    print(asyncio.run(evaluate()).report())
