# RecitAI

Local-first RAG study assistant. Upload course material; get validated practice
questions and flashcards drawn only from it, with page-level citations.

**Read before implementing:** `plan/RECITAI_BUILD_SPEC.md` — the source of truth.

## Project documents

| File | What it holds |
|---|---|
| `plan/RECITAI_BUILD_SPEC.md` | The spec. Sections 0–6 are the contract; 7+ are the phase plan. |
| `plan/PROGRESS.md` | Phase board and session log. **Read this first to know where work stands.** |
| `plan/DECISIONS.md` | Every decision taken (`D-00N`), including deviations from the spec. |
| `plan/ISSUES.md` | Spec gaps, blockers, and measured problems (`I-00N`). |
| `docs/adr/` | Full ADRs for the architectural decisions. |

## Hard rules

- Quiz generation uses the coverage sampler (`retrieval/sampler.py`), NEVER vector search.
- All generated content must carry `source_chunk_ids` and `page_refs`. No exceptions.
- No RAG frameworks. Direct httpx to Ollama.
- Constants live in `recitai/constants.py`. Do not inline magic numbers.
- Prompts live in `recitai/prompts/*.md`. Do not inline prompt strings in Python.
- Never mock the LLM in application code. Mock only in tests, via the `LLMClient` protocol.
- Build one phase at a time. Do not start a phase until the previous phase's VERIFY passes.
- Hit a contradiction between spec and reality? Record it in `plan/ISSUES.md` and stop.
  Do not silently work around it.

## Deviations from the spec in force

These are deliberate and recorded — do not "fix" them back.

- **D-001** Postgres from Phase 0, not SQLite.
- **D-002** Ollama runs natively in dev (no GPU passthrough on macOS); containerised in prod.
- **D-003** Repo is rooted here; the spec lives at `plan/`, not `docs/BUILD_SPEC.md`.
- **D-008** PPTX is a first-class input, parsed with `python-pptx`. PyMuPDF silently
  flattens every slide onto one page — never route `.pptx` through it.
- **D-009** Slides merge greedily toward `TARGET_CHUNK_TOKENS`, not by shared heading.
  The spec's rule discards 87% of this corpus.

## Corpus

`materials/` — five `.pptx` decks, distributed database systems, 227 slides.
Gitignored (copyrighted). Measured profile in `plan/ISSUES.md` I-016; it has **no speaker
notes** and a ceiling of ~34 chunks.

## Commands

```
make dev      # start qdrant + postgres (Ollama is native)
make smoke    # Phase 0 gate: structured output + embedding against real models
make lint     # ruff + black + mypy
make test     # pytest
make ingest F=...   # Phase 1
make eval           # Phase 7
```
