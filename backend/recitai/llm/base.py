"""The LLM boundary (spec §4.4).

`OllamaClient` is the only implementation in v1. This protocol exists so tests can
substitute a fake, and so a hosted adapter remains possible later (plan/ISSUES.md I-013)
— not so it can be reached for when the local model is slow (spec §0.2).

Never mock the LLM in application code. Mock only in tests, through this protocol.
"""

from collections.abc import AsyncIterator
from typing import Protocol

from recitai.constants import GEN_TEMPERATURE


class LLMClient(Protocol):
    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = GEN_TEMPERATURE,
        schema: dict | None = None,
    ) -> str: ...

    async def stream(self, prompt: str, *, system: str | None = None) -> AsyncIterator[str]: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
