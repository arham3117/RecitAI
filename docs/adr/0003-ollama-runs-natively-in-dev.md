# ADR 0003 — Ollama runs natively in development, containerised in production

Status: accepted · 2026-08-31 · Spec §8 task 2, §16 task 3 · Decision log: `D-002`

## Context

Spec §8 puts Ollama in `docker-compose.yml` alongside Qdrant and Postgres. Development
happens on an Apple M5 Pro; the project is intended to be hosted once built.

Docker on macOS provides no GPU passthrough — Metal is reachable only from a native
process. A containerised Ollama on this machine therefore runs CPU-only, roughly an order
of magnitude slower. That is not merely inconvenient: Phase 7 exists to produce latency
measurements, and measuring a CPU-bound container would yield numbers describing a
configuration nobody will ever deploy.

On a Linux host with an NVIDIA GPU, the opposite holds. GPU passthrough works via the
NVIDIA Container Toolkit, and containerising Ollama gives reproducible deploys.

## Decision

Split by compose file, which the spec already anticipates:

- **`docker-compose.yml`** (development) — Qdrant and Postgres. Ollama runs natively on
  the host and is reached at `http://localhost:11434`.
- **`docker-compose.prod.yml`** (hosting) — adds an Ollama service with the NVIDIA runtime;
  containers reach it at `http://ollama:11434`.

The sole difference visible to application code is `OLLAMA_BASE_URL`, owned by
`config.py`. Nothing branches on environment.

Both files are written in Phase 0. The production topology is not deferred to Phase 8,
because a deployment path first attempted at the end of a project is where week-long
surprises live.

## Consequences

Local generation runs at GPU speed, and Phase 7's latency numbers describe a real
deployment.

The costs are two compose files to keep in step, and a development environment that is
not byte-identical to production. The divergence is limited to where the model server
lives, and that boundary is a single URL — a smaller risk than the alternative, which is
either unusably slow local development or an untested deploy.

The remaining open question is not architectural but economic: an always-on GPU host is
the expensive part of hosting this, and invariant I5 makes local inference the default.
Tracked as `I-013`; the `LLMClient` protocol (ADR 0002) is the
seam that keeps hosted inference available without committing to it now.
