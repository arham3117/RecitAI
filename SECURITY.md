# Security

## Reporting a vulnerability

Please report security issues privately through
[GitHub's private vulnerability reporting](https://github.com/arham3117/RecitAI/security/advisories/new)
rather than opening a public issue. Include what an attacker could do and the smallest
reproduction you have; a fix or mitigation is welcome but not required.

This is a personal project, not a funded one — expect a response in days rather than
hours, and there is no bounty.

## What this project's threat model actually is

RecitAI is designed to run **on one person's machine, for that person**. That shapes what
counts as a vulnerability here.

**By design, and not bugs:**

- **No authentication.** The API assumes a single trusted local user. Every course is
  visible to whoever can reach the port.
- **The dev `docker-compose.yml` ships a known Postgres password** (`recitai`) on a
  container published to localhost. It is a development convenience.
  `docker-compose.prod.yml` refuses to start without `POSTGRES_PASSWORD` set in the
  environment.
- **Uploaded files are kept, not deleted after parsing**, so the explanation panel can
  render the real slide. They live under `materials/uploads/<course_id>/`.

**Consequently, do not expose this to a network you do not control.** If you deploy it,
put authentication in front of it; there is none inside it.

**Genuinely worth reporting:**

- Anything that lets one course read another course's material. Course isolation is a
  correctness guarantee (invariant I2, "closed world"), and a leak across courses is a
  real defect regardless of the single-user assumption.
- Path traversal through an uploaded filename, a course id, or a document id.
- Anything that causes course material to leave the machine. Inference is local by
  design (invariant I5) — the only outbound calls should be to Ollama on `localhost`.
- Injection through course material that changes what the backend *does*, as opposed to
  what the model says. Content in slides is untrusted input.

## Handling your own data

Course material is copyrighted more often than not, and `materials/` is gitignored for
that reason. Check before committing anything under it: `.gitignore` excludes `*.pptx`,
`*.ppt` and `*.pdf` repository-wide, with a narrow exception for the synthetic test
fixture.

Nothing is sent to a third-party API. Generation and embedding both run against a local
Ollama instance, and there is no telemetry.
