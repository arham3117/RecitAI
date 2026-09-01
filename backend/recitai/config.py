"""Runtime configuration (spec §8 task 4).

The only thing that differs between local development and a hosted deployment is where
the services live — see plan/DECISIONS.md D-002. Application code never branches on
environment; it reads these values.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

from recitai import constants


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Ollama runs natively in dev (localhost) and containerised in prod (ollama:11434).
    # D-002 — this URL is the entire difference between the two topologies.
    ollama_base_url: str = "http://localhost:11434"

    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "recitai_chunks"

    # D-001 — Postgres from Phase 0, not SQLite.
    database_url: str = "postgresql+asyncpg://recitai:recitai@localhost:5433/recitai"

    gen_model: str = constants.GEN_MODEL
    embedding_model: str = constants.EMBEDDING_MODEL

    # Prompt selection is configuration, not code: §15 task 7 A/B-tests two prompt
    # versions against the harness, and §6 versions prompts by filename rather than
    # editing them in place.
    # v1 by measurement, not inertia. A seeded A/B (seed 7, same corpus) showed v2 cost
    # 40% of yield — 20 questions to 12 — while the "primary/main" construction it was
    # written to prevent went from 5% of stems to 17%, and 3 of its 18 UNIQUE rejections
    # affirmed the marked answer in their own reasoning. See plan/ISSUES.md I-028.
    question_prompt: str = "question_generation_v1"
    judge_prompt: str = "validator_judge_v1"

    log_level: str = "INFO"
    #: "console" for development, "json" in production (§16 task 6).
    log_format: str = "console"

    # An 8B model on a cold load can take well over a minute to return its first token.
    # A conventional short timeout here surfaces as an inscrutable failure, not slowness.
    llm_timeout_seconds: float = 300.0


settings = Settings()
