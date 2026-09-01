"""Phase 0 has no application logic to test. These assert the contracts later phases
depend on: the spec's constants are present, and the client really does satisfy the
LLMClient protocol."""

from recitai import constants
from recitai.llm.base import LLMClient
from recitai.llm.ollama import OllamaClient


def test_constants_match_spec() -> None:
    # Spot-check the values later phases hard-depend on (spec §4.1).
    assert constants.EMBEDDING_DIM == 768
    assert constants.TARGET_CHUNK_TOKENS == 600
    assert constants.MIN_CHUNK_TOKENS_FOR_GENERATION == 150
    assert constants.OPTIONS_PER_QUESTION == 4
    assert constants.GEN_MODEL == "llama3.1:8b-instruct-q5_K_M"
    assert len(constants.BANNED_PHRASES) == 6


def test_ollama_client_satisfies_protocol() -> None:
    """Structural conformance is checked by mypy, not at runtime — this assignment is
    the assertion, and it only means anything because `make lint` now type-checks
    tests/ as well as recitai/ (it previously did not, which is how the `stream`
    signature mismatch in I-021 went unnoticed)."""
    client: LLMClient = OllamaClient()
    assert callable(client.complete)
    assert callable(client.stream)
    assert callable(client.embed)


def test_stream_returns_an_async_iterator_not_a_coroutine() -> None:
    """I-021 regression guard. `stream()` is an async generator: calling it yields an
    async iterator directly. If it were ever rewritten as a plain `async def` returning
    one, callers would need an extra `await` and every `async for` would break."""
    import inspect

    assert inspect.isasyncgenfunction(OllamaClient.stream)
