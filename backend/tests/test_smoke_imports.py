"""Phase 0 has no application logic to test. These assert the contracts later phases
depend on: the spec's constants are present and unmodified, and the client satisfies
the protocol."""

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
    client: LLMClient = OllamaClient()
    assert hasattr(client, "complete")
    assert hasattr(client, "stream")
    assert hasattr(client, "embed")
