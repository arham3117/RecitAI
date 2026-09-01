"""Ollama client (spec §8 task 6).

Direct httpx against the Ollama HTTP API — no RAG framework (D-007). Structured output
uses Ollama's `format` parameter with a Pydantic JSON schema, so the model is constrained
at decode time rather than asked politely to return JSON.
"""

import json
from collections.abc import AsyncIterator
from types import TracebackType

import httpx
import structlog

from recitai.config import settings
from recitai.constants import EMBEDDING_BATCH_SIZE, GEN_MAX_TOKENS, GEN_TEMPERATURE

log = structlog.get_logger(__name__)


class OllamaError(RuntimeError):
    """Ollama returned something unusable. Never swallowed — spec §0.2."""


class OllamaClient:
    """Implements the LLMClient protocol (§4.4) against a local Ollama runtime."""

    def __init__(
        self,
        base_url: str | None = None,
        gen_model: str | None = None,
        embedding_model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.gen_model = gen_model or settings.gen_model
        self.embedding_model = embedding_model or settings.embedding_model
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout or settings.llm_timeout_seconds),
        )

    async def __aenter__(self) -> "OllamaClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    def _messages(self, prompt: str, system: str | None) -> list[dict[str, str]]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = GEN_TEMPERATURE,
        schema: dict | None = None,
    ) -> str:
        payload: dict[str, object] = {
            "model": self.gen_model,
            "messages": self._messages(prompt, system),
            "stream": False,
            "options": {"temperature": temperature, "num_predict": GEN_MAX_TOKENS},
        }
        if schema is not None:
            payload["format"] = schema

        resp = await self._client.post("/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("message", {}).get("content")
        if not content:
            raise OllamaError(
                f"empty completion from {self.gen_model}; "
                f"done_reason={data.get('done_reason')!r}"
            )
        log.debug(
            "ollama.complete",
            model=self.gen_model,
            structured=schema is not None,
            prompt_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
        )
        return str(content)

    async def stream(self, prompt: str, *, system: str | None = None) -> AsyncIterator[str]:
        payload = {
            "model": self.gen_model,
            "messages": self._messages(prompt, system),
            "stream": True,
            "options": {"temperature": GEN_TEMPERATURE, "num_predict": GEN_MAX_TOKENS},
        }
        async with self._client.stream("POST", "/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                chunk = json.loads(line)
                piece = chunk.get("message", {}).get("content", "")
                if piece:
                    yield piece
                if chunk.get("done"):
                    break

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = texts[start : start + EMBEDDING_BATCH_SIZE]
            resp = await self._client.post(
                "/api/embed", json={"model": self.embedding_model, "input": batch}
            )
            resp.raise_for_status()
            embeddings = resp.json().get("embeddings")
            if not embeddings or len(embeddings) != len(batch):
                raise OllamaError(
                    f"{self.embedding_model} returned "
                    f"{len(embeddings) if embeddings else 0} embeddings for {len(batch)} inputs"
                )
            vectors.extend(embeddings)
        return vectors
