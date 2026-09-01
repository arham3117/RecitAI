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

    log_level: str = "INFO"

    # An 8B model on a cold load can take well over a minute to return its first token.
    # A conventional short timeout here surfaces as an inscrutable failure, not slowness.
    llm_timeout_seconds: float = 300.0


settings = Settings()
