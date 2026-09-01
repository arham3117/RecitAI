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

These are deliberate and recorded in `plan/DECISIONS.md` — do not "fix" them back.

- **D-001** Postgres from Phase 0, not SQLite.
- **D-002** Ollama runs natively in dev (no GPU passthrough on macOS); containerised in prod.
- **D-003** Repo is rooted here; the spec lives at `plan/`, not `docs/BUILD_SPEC.md`.
- **D-008** PPTX is a first-class input, parsed with `python-pptx`. PyMuPDF silently
  flattens every slide onto one page — never route `.pptx` through it.
- **D-009** Slides merge greedily toward `TARGET_CHUNK_TOKENS`, not by shared heading.
  The spec's rule discards 87% of this corpus.
- **D-010** `constants.py` is excluded from formatters and diff-tested against spec §4.1.
- **D-011** A topic must group more than one chunk; the sampler redistributes shortfall.
- **D-012** Clustering uses agglomerative partitioning, not HDBSCAN — HDBSCAN drops
  outliers, which would leave chunks in no topic and invisible to the sampler.
- **D-013** `GEN_MODEL` stays on llama3.1:8b. Qwen 2.5 14B was measured: better on quality
  signals, 36% slower, and it did not fix the arithmetic failure it was tried for.
- **D-016** No Celery and no Prometheus — a single-user demo cannot use the guarantee.
  The concurrency story is therefore untested.

## Things measured, so do not re-litigate them

- **Prompt changes lost to deterministic checks, twice.** Sharpening the prompt cost 40%
  of yield and made the target pattern *more* frequent; a 14B model cost 36% latency and
  did not fix it; a regex fixed both at ~zero cost. Where a failure is mechanically
  detectable, §5.1's free tier wins.
- **Generation must be seeded to compare anything.** `--seed` drives the sampler *and* the
  model. Before that, two runs with identical prompts differed 22 vs 18 persisted, so any
  single-run A/B measured noise.
- **`make eval` is the arbiter.** Coverage ≥90% is the number that proves the Path A
  design; it currently reads 100%.

## Corpus

`materials/` — five `.pptx` decks, distributed database systems, 227 slides.
Gitignored (copyrighted). Measured profile in `plan/ISSUES.md` I-016; it has **no speaker
notes** and a ceiling of ~34 chunks.

## Commands

```
make dev              # qdrant + postgres (Ollama runs natively — D-002)
make migrate          # alembic upgrade head
make smoke            # structured output + embedding against the real models
make services         # assert the app can actually reach postgres and qdrant
make ingest F=materials C="Course name"
make api              # backend on :8000 (also serves a single-page client at /)
make web              # Next.js frontend on :3000
make eval             # the §15 metrics report
make compare LOGS="a.txt b.txt"   # A/B two generation runs
make lint && make test
```
