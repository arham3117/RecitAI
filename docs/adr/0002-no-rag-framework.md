# ADR 0002 — No RAG framework; direct httpx to Ollama

Status: accepted · 2026-08-31 · Spec §0.2, §4.4 · Log entry: [D-007](../../plan/DECISIONS.md#d-007)

## Context

LangChain, LlamaIndex, and Haystack all offer a short path from documents to a working
question-answering pipeline, and that path is genuinely shorter than writing one.

The retrieval design here is ADR 0001's two-path split: generation must draw from a
deterministic coverage sampler, never from similarity search. Frameworks are built around
the assumption this project rejects — that retrieval means embedding a query and taking
the top-k. Expressing "filter by metadata, weight topics by size and student weakness,
allocate by largest remainder, sort by usage count, tie-break by seeded RNG" inside one
means subclassing a retriever to do something its interface was not designed for.

## Decision

No RAG framework. The model is reached through `llm/ollama.py`, an `httpx` client
implementing the `LLMClient` protocol (spec §4.4). Retrieval is our own code against
`qdrant-client`. Structured output uses Ollama's `format` parameter with a Pydantic JSON
schema, constraining the decoder rather than requesting JSON politely.

## Consequences

Every call is inspectable, the dependency surface stays small, and the interesting part
of the system — the sampler and the validator — is written plainly rather than hidden
inside a framework's control flow.

The cost is roughly one file of infrastructure we would otherwise inherit: retries,
batching, streaming, and structured-output handling.

`LLMClient` is the only seam a different inference backend would need, which keeps the
hosting question ([I-013](../../plan/ISSUES.md#i-013)) open at zero cost. It exists for
tests and for that future adapter — not as an escape hatch to reach for when the local
model is slow (spec §0.2).
