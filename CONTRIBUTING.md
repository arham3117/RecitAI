# Contributing to RecitAI

Thanks for taking a look. This document covers how the project is built and what a change
has to satisfy before it lands.

## The rules that are not negotiable

RecitAI makes six promises to a student, and they constrain the code more than any style
guide does. They come from §2 of the build spec, which is kept outside this repository:

| | Invariant | What it forbids |
|---|---|---|
| **I1** | Groundedness | Generated content without `source_chunk_ids` and `page_refs` |
| **I2** | Closed world | Any answer drawn from the model's general knowledge |
| **I3** | Coverage | Quiz generation via vector search — it must use the sampler |
| **I4** | Validated output | Serving a question the validator has not passed |
| **I5** | Local inference | Sending course material to a third-party API |
| **I6** | Determinism | An unseeded run that cannot be reproduced |

**I3 is the one people break by accident.** Vector search returns what a query is *most
like*, which is the opposite of what a quiz needs — it will return the same well-embedded
passages every time and silently never ask about the rest of the syllabus. Quiz generation
goes through `retrieval/sampler.py`. Explanations, chat and scope resolution are Path B and
may use search freely. See [`docs/adr/0001-two-path-retrieval.md`](docs/adr/0001-two-path-retrieval.md).

## Setting up

```bash
make dev                                   # qdrant + postgres in Docker
ollama pull llama3.1:8b-instruct-q5_K_M
ollama pull nomic-embed-text
make install && make migrate
make smoke                                 # proves both models actually respond
```

`make smoke` is the gate: it exercises schema-constrained completion and embedding against
the real local models. If it fails, nothing else will work and the error will be less clear.

## Before you open a pull request

```bash
make lint          # ruff + black --check + mypy (strict)
make test          # pytest
make reconcile     # qdrant and postgres agree, in both directions
cd frontend && npx tsc --noEmit && npx next build
```

All of these must pass. Two notes on the frontend:

- **Do not run a formatter over it.** There is no Prettier config and no configured
  ESLint; the files are hand-formatted. `prettier --write` on `app/page.tsx` once produced
  411 changed lines where 245 were real, and no `printWidth` reproduces the committed
  style. `tsc --noEmit` and `next build` are the gates.
- The API tests run against a **live** service and database by design — `TestClient`
  collides with the async engine-disposal fixture (issue `I-026`). Anything a
  test creates must be cleaned up; use the `scratch_course` fixture.

## Conventions

- **Constants live in `recitai/constants.py`**, which is diff-tested against spec §4.1 and
  excluded from formatters. Do not inline magic numbers, and do not reformat that file.
- **Prompts live in `recitai/prompts/*.md`**, never as string literals in Python.
- **Never mock the LLM in application code.** Mock only in tests, through the `LLMClient`
  protocol.
- **No RAG frameworks.** Direct `httpx` to Ollama — see
  [`docs/adr/0002-no-rag-framework.md`](docs/adr/0002-no-rag-framework.md).

## Deliberate departures — do not "fix" these back

Each of these looks like a mistake until you know why it is there. They were taken against
the spec on purpose, and every one is recorded in the decision log with its measurement.

| | Departure | Why |
|---|---|---|
| **D-001** | Postgres from the first phase, not SQLite | Removes a migrate-a-populated-database step later |
| **D-002** | Ollama runs natively in development, containerised in production | Docker on Apple Silicon has no GPU passthrough, so a containerised model runs an order of magnitude slower — and would have corrupted every latency number |
| **D-008** | `.pptx` is parsed with `python-pptx`, never PyMuPDF | PyMuPDF silently flattens every slide onto one page. Nothing errors; the page numbers are simply wrong, and page numbers are the product |
| **D-009** | Slides merge greedily toward `TARGET_CHUNK_TOKENS`, not by shared heading | The spec's heading rule discards **87%** of this corpus |
| **D-010** | `constants.py` is excluded from formatters and diff-tested against spec §4.1 | A formatter reflowing it would silently break the equality the test depends on |
| **D-011** | A topic must group more than one chunk; the sampler redistributes the shortfall | Single-chunk topics starve the allocation and the shortfall vanishes unreported |
| **D-012** | Clustering uses agglomerative partitioning, not HDBSCAN | HDBSCAN discards outliers. A discarded chunk belongs to no topic, and a chunk in no topic is invisible to the sampler — silently uncoverable material, which is the one failure this project exists to prevent |
| **D-013** | `GEN_MODEL` stays on llama3.1:8b | Qwen 2.5 14B measured better on quality signals but 36% slower, and did not fix the failure it was tried for |
| **D-016** | No Celery, no Prometheus | A single-user local tool cannot use the guarantee. The cost is honest: the concurrency story is untested |

## Measure before you claim

This project has a habit, and it is the most useful thing in it: **a change to generation
quality is not accepted without a seeded A/B**. `--seed` drives the sampler *and* the
model, because before it existed two runs of an identical prompt produced 22 and 18
persisted questions — so any single-run comparison was measuring noise.

```bash
make ingest F=materials C="Your Course"
# generate twice with the same seed, changing one thing
make compare LOGS="before.txt after.txt"
make eval          # the §15 metrics report; coverage must stay ≥90%
```

Two changes have already been reverted on measurement rather than opinion: a sharpened
prompt that cost 40% of yield while making the target failure *more* frequent, and a 14B
model that was 36% slower and did not fix the arithmetic error it was tried for. A regex
fixed both at roughly zero cost. Where a failure is mechanically detectable, prefer the
deterministic check.

Three findings worth not repeating:

- **Prompt sharpening lost to a deterministic check, twice.** Where a failure can be
  detected mechanically, the free tier of §5.1 beats both instructing a bigger model and
  instructing a smaller one.
- **Nothing can be compared without a seed.** Two runs of an identical prompt produced 22
  and 18 persisted questions, so a single-run A/B measures noise, not the change.
- **`make eval` is the arbiter.** Topic coverage ≥90% is the number that proves the Path A
  design. It currently reads 100%, and a change that lowers it is a regression regardless
  of what else it improves.

## Recording decisions

The project keeps three logs outside this repository — a decision log (`D-0NN`, including
what was rejected and why), an issue register (`I-0NN`, each with its measurement), and a
progress log. Comments in the code cite those identifiers, which is why you will see
`D-013` or `I-030` in a docstring with nothing to click.

If you are working from a checkout alone, [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md),
[`docs/evaluation.md`](docs/evaluation.md) and [`docs/adr/`](docs/adr/) carry the reasoning
you need. If you have the logs, a change that alters behaviour should update them.

If you hit a contradiction between the spec and reality, record it and stop. Do not
silently work around it — that rule is why the issue log is worth reading.

## Reporting a bug

Please include what you observed, what you expected, and the smallest thing that
reproduces it. If it concerns generation quality, a seed makes it reproducible and is
worth more than a description.
