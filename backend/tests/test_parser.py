"""Parser tests — chiefly the I-014 regression guard."""

from pathlib import Path

import pytest

from recitai.ingestion.parser import (
    UnsupportedFormatError,
    _PositionedText,
    _reading_order,
    parse,
)


def test_pptx_slides_map_to_distinct_pages(synthetic_deck: Path) -> None:
    """I-014 regression guard.

    PyMuPDF opens .pptx without error and collapses every slide onto ONE page, which
    would make every citation read "page 1". This asserts the property that failure
    destroys: distinct slides produce distinct page numbers.
    """
    doc = parse(synthetic_deck)
    assert doc.page_count == 4
    assert [p.number for p in doc.pages] == [1, 2, 3, 4]
    assert len({p.number for p in doc.pages}) == 4


def test_slide_headings_and_notes_are_captured(synthetic_deck: Path) -> None:
    doc = parse(synthetic_deck)
    assert doc.pages[1].heading == "Horizontal Fragmentation"
    # Speaker notes are the main reason D-008 uses python-pptx over a PDF export.
    assert "confuse" in doc.pages[1].notes
    assert "confuse" in doc.pages[1].content


def test_title_is_not_duplicated_into_the_body(synthetic_deck: Path) -> None:
    """`shapes.title` returns a fresh proxy on each access, so an identity check inside
    the shape loop silently fails and repeats the title in every slide's body."""
    doc = parse(synthetic_deck)
    page = doc.pages[1]
    assert page.heading is not None
    assert page.text.count(page.heading) == 0


def test_page_for_offset_resolves_every_page(synthetic_deck: Path) -> None:
    doc = parse(synthetic_deck)
    for span in doc.page_map:
        assert doc.page_for_offset(span.start) == span.page
        assert doc.page_for_offset(span.end - 1) == span.page


def test_unknown_extension_fails_loudly(tmp_path: Path) -> None:
    """Never fall through to a parser that would accept the file and mis-attribute it."""
    bad = tmp_path / "notes.docx"
    bad.write_bytes(b"stub")
    with pytest.raises(UnsupportedFormatError, match="no parser"):
        parse(bad)


def test_reading_order_reconstructs_rows_from_geometry() -> None:
    """Decks build tables from individually placed text boxes, delivered in z-order.
    Ordering by position is what keeps a value on the same line as its column header."""
    inch = 914400
    items = [
        # z-order, as python-pptx delivers it: the second row arrives first.
        _PositionedText(top=2 * inch, left=3 * inch, text="250000"),
        _PositionedText(top=2 * inch, left=1 * inch, text="P3"),
        _PositionedText(top=1 * inch, left=1 * inch, text="PNO"),
        _PositionedText(top=1 * inch, left=3 * inch, text="BUDGET"),
    ]
    assert _reading_order(items) == ["PNO | BUDGET", "P3 | 250000"]
