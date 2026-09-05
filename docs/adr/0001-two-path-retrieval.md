# ADR 0001 — Two retrieval paths: coverage sampling, never vector search, for generation

Status: accepted · 2026-08-31 · Spec §3.1, §3.3 · Decision log: `D-006`

## Context

A student selects "Chapter 2: Thermodynamics" — 41 chunks over ~30 pages — and asks for
a 15-question quiz.

The reflexive implementation embeds the string "thermodynamics", retrieves the top-k
chunks, and generates from those. It fails in a way that does not look like failure. The
chunks that win a similarity contest against the word "thermodynamics" are the ones that
*say* "thermodynamics" most often, which is the chapter introduction. The student
receives five definition questions, nothing on entropy calculation, and no indication
that 26 of 30 pages were never considered.

The output is well-formed, grounded, and correctly cited. It is still useless as study
material, and nothing downstream can detect that.

## Decision

Scoping is a **filter**, not a search. Two access patterns over one indexed corpus:

| | Path A — Coverage | Path B — Similarity |
|---|---|---|
| Mechanism | Metadata filter + deterministic sampler | Vector search + optional rerank |
| Is there a query? | No query exists | A real user query with semantics |
| Used for | Quiz generation, flashcard generation, syllabus view | Explanations, follow-ups, scope resolution, citation lookup |
| Guarantees | Full coverage of the scope | Relevance to a question |
| Module | `retrieval/sampler.py` | `retrieval/search.py` |

Where a student types free text rather than picking a topic, Path B **locates** the
material and the resolver then **expands** to the topic IDs of what it found; the sampler
covers all of those topics. Generation never happens from the retrieved chunks directly.
That expansion step is the whole mechanism — a resolver that returns the retrieved chunks
is the failure this ADR exists to prevent, wearing the right module name.

## Consequences

Coverage becomes a measurable property rather than a hope: Phase 7 reports the percentage
of topics represented across five consecutive quizzes, targeting ≥90%. That number is the
evidence this design works, and it is the one to put in the README.

The cost is that the sampler is custom code — topic weighting by size, freshness, and
student weakness, then largest-remainder allocation — that no framework provides. This is
the main reason ADR 0002 rejects RAG frameworks: they cannot express this, and building
it inside one means fighting the abstraction.

One rule the spec left open is recorded in `I-006`: where the
allocation exceeds a topic's supply of eligible chunks, the shortfall must be
redistributed and reported, never silently dropped.
