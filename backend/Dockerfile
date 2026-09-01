# Multi-stage build (spec §16 task 3).
#
# Stage 1 resolves dependencies with uv into a self-contained virtualenv; stage 2 copies
# that venv into a slim runtime with no build toolchain and no uv. Keeping the resolver
# out of the final image is the point: it is the largest thing in the build and none of it
# is needed at runtime.

# ---------------------------------------------------------------- builder ----
FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies resolve from the lockfile alone, so this layer is cached until the lock
# changes — application edits do not trigger a reinstall.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY recitai ./recitai
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

# ---------------------------------------------------------------- runtime ----
FROM python:3.12-slim-bookworm AS runtime

# libgomp is required by scikit-learn's OpenMP runtime (the §10 task 2 clustering
# fallback); curl serves the healthcheck.
RUN apt-get update \
    && apt-get install --no-install-recommends -y libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root (§16 task 3). Created before the copy so ownership is right without a chown
# layer over the whole venv.
RUN useradd --create-home --uid 10001 recitai

WORKDIR /app
COPY --from=builder --chown=recitai:recitai /app/.venv /app/.venv
COPY --from=builder --chown=recitai:recitai /app/recitai /app/recitai
COPY --chown=recitai:recitai alembic /app/alembic
COPY --chown=recitai:recitai alembic.ini /app/alembic.ini

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER recitai
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "recitai.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
