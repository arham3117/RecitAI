"""Chunker tests — D-009's merge strategy and the §9 task 4 invariants."""

from recitai.constants import MAX_CHUNK_TOKENS, MIN_CHUNK_TOKENS
from recitai.ingestion.chunker import (
    TextChunk,
    _merge_undersized,
    chunk_slides,
    count_tokens,
    is_slide_shaped,
)
from recitai.ingestion.parser import ParsedDocument, ParsedPage


def _doc(pages: list[ParsedPage]) -> ParsedDocument:
    return ParsedDocument(filename="d.pptx", source_kind="pptx", pages=pages, sha256="0" * 64)


def test_sparse_slides_merge_instead_of_being_discarded() -> None:
    """I-017: the spec merges only slides sharing a heading. These decks give every
    slide a distinct title, so that rule keeps 13% of the corpus. D-009 merges toward
    the token target instead."""
    pages = [
        ParsedPage(number=i, heading=f"Distinct Topic {i}", text="word " * 60) for i in range(1, 13)
    ]
    chunks = chunk_slides(_doc(pages), "Unit")
    assert len(chunks) < len(pages), "sparse slides must merge, not survive one-per-chunk"
    assert all(c.token_count <= MAX_CHUNK_TOKENS for c in chunks)
    # Every slide's content must still be present somewhere.
    joined = " ".join(c.text for c in chunks)
    for page in pages:
        assert page.heading is not None
        assert page.heading in joined


def test_merged_chunk_spans_the_pages_it_covers() -> None:
    pages = [ParsedPage(number=i, heading=f"T{i}", text="word " * 40) for i in range(1, 7)]
    chunks = chunk_slides(_doc(pages), "Unit")
    assert chunks[0].page_start == 1
    assert chunks[-1].page_end == 6
    for c in chunks:
        assert c.page_end >= c.page_start


def test_structural_slides_break_the_merge_run() -> None:
    """Merging across an 'Outline' slide would join two unrelated sections."""
    pages = [
        ParsedPage(number=1, heading="Alpha", text="word " * 30),
        ParsedPage(number=2, heading="Outline", text="Alpha\nBeta"),
        ParsedPage(number=3, heading="Beta", text="word " * 30),
    ]
    chunks = chunk_slides(_doc(pages), "Unit")
    assert len(chunks) == 2
    assert "Beta" not in chunks[0].text
    # The navigation slide itself carries no examinable content.
    assert all("Outline" not in c.text for c in chunks)


def test_section_path_is_unit_then_topic() -> None:
    pages = [ParsedPage(number=1, heading="Entropy", text="word " * 50)]
    chunks = chunk_slides(_doc(pages), "Thermodynamics")
    assert chunks[0].section_path == ["Thermodynamics", "Entropy"]


def test_undersized_chunks_merge_into_a_neighbour() -> None:
    tiny = "word " * 5
    big = "word " * 300
    chunks = [
        TextChunk(big, 1, 1, ["U"], count_tokens(big)),
        TextChunk(tiny, 2, 2, ["U"], count_tokens(tiny)),
    ]
    merged = _merge_undersized(chunks)
    assert len(merged) == 1
    assert merged[0].page_end == 2, "merging must extend the page range, not lose a page"
    assert merged[0].token_count >= MIN_CHUNK_TOKENS


def test_prose_pdf_is_not_treated_as_slides() -> None:
    dense = ParsedDocument(
        filename="book.pdf",
        source_kind="pdf",
        pages=[ParsedPage(number=1, heading=None, text="word " * 500)],
        sha256="0" * 64,
    )
    assert not is_slide_shaped(dense)
