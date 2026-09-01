"""Phase 0 verification gate (spec §8 task 7).

Proves the two calls every later phase is built on actually work against the real local
models: a schema-constrained completion that parses, and an embedding of the right
dimension. Exits non-zero on failure — this gate is not advisory.
"""

import asyncio
import sys
import time
from typing import Literal

from pydantic import BaseModel, Field

from recitai.constants import EMBEDDING_DIM
from recitai.llm.ollama import OllamaClient


class SmokeAnswer(BaseModel):
    """A miniature of §4.5's shape: enum, constrained list, required prose."""

    topic: str
    confidence: Literal["low", "medium", "high"]
    keywords: list[str] = Field(min_length=2, max_length=4)


async def main() -> int:
    client = OllamaClient()
    failures: list[str] = []
    try:
        # --- 1. structured output -------------------------------------------------
        print(f"[1/2] schema-constrained completion via {client.gen_model} ...")
        t0 = time.perf_counter()
        raw = await client.complete(
            "Summarise what a distributed database is, in one topic label.",
            system="You answer only with JSON matching the provided schema.",
            temperature=0.0,
            schema=SmokeAnswer.model_json_schema(),
        )
        elapsed = time.perf_counter() - t0
        try:
            parsed = SmokeAnswer.model_validate_json(raw)
        except Exception as exc:
            failures.append(f"structured output did not parse: {exc}\n  raw: {raw[:300]!r}")
        else:
            print(f"      parsed OK in {elapsed:.1f}s -> {parsed.model_dump()}")

        # --- 2. embeddings --------------------------------------------------------
        print(f"[2/2] embedding via {client.embedding_model} ...")
        t0 = time.perf_counter()
        vectors = await client.embed(["entropy never decreases", "carnot efficiency"])
        elapsed = time.perf_counter() - t0
        if len(vectors) != 2:
            failures.append(f"expected 2 embeddings, got {len(vectors)}")
        else:
            dim = len(vectors[0])
            print(f"      got {len(vectors)} vectors of dim {dim} in {elapsed:.2f}s")
            if dim != EMBEDDING_DIM:
                failures.append(f"embedding dim {dim} != EMBEDDING_DIM {EMBEDDING_DIM}")
            else:
                print(f"      {dim}")
    finally:
        await client.aclose()

    if failures:
        print("\nSMOKE TEST FAILED", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("\nSMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
