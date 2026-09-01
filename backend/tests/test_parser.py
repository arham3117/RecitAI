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
    cell = 2 * inch  # cells abut, as a drawn table's do
    items = [
        # z-order, as python-pptx delivers it: the second row arrives first.
        _PositionedText(top=2 * inch, left=3 * inch, text="250000", width=cell),
        _PositionedText(top=2 * inch, left=1 * inch, text="P3", width=cell),
        _PositionedText(top=1 * inch, left=1 * inch, text="PNO", width=cell),
        _PositionedText(top=1 * inch, left=3 * inch, text="BUDGET", width=cell),
    ]
    assert _reading_order(items) == ["PNO | BUDGET", "P3 | 250000"]


def test_side_by_side_tables_are_cut_into_separate_blocks() -> None:
    """I-027 regression.

    Two tables printed side by side were banded into shared rows, interleaving their
    columns. A model reading that passage answered "8 rows" for a Cartesian product that
    has 32 — and the validator could not catch it, because the claim really was supported
    by the passage as extracted. Ingestion quality bounds generation quality.
    """
    inch = 914400
    cell = inch  # abutting cells, so the only gap is the gutter between the two tables
    items = [
        # Left table: EMP, two rows.
        _PositionedText(top=1 * inch, left=1 * inch, text="ENO", width=cell),
        _PositionedText(top=1 * inch, left=2 * inch, text="ENAME", width=cell),
        _PositionedText(top=2 * inch, left=1 * inch, text="E1", width=cell),
        _PositionedText(top=2 * inch, left=2 * inch, text="J. Doe", width=cell),
        # Right table, across a 1in gutter: EMP x PAY.
        _PositionedText(top=1 * inch, left=4 * inch, text="TITLE", width=cell),
        _PositionedText(top=1 * inch, left=5 * inch, text="SALARY", width=cell),
        _PositionedText(top=2 * inch, left=4 * inch, text="Eng.", width=cell),
        _PositionedText(top=2 * inch, left=5 * inch, text="55000", width=cell),
    ]
    lines = _reading_order(items)
    assert lines == [
        "ENO | ENAME",
        "E1 | J. Doe",
        "TITLE | SALARY",
        "Eng. | 55000",
    ], "each table must be read whole before the next, not interleaved row by row"


def test_a_column_cut_is_preferred_over_a_taller_row_gap() -> None:
    """On the I-027 slide the tallest vertical gap sits between two stacked left-hand
    tables while the right-hand table spans the full height. Cutting on the taller gap
    first would slice that table in half."""
    inch = 914400
    items = [
        _PositionedText(top=1 * inch, left=1 * inch, text="topleft", width=inch, height=inch),
        _PositionedText(top=5 * inch, left=1 * inch, text="bottomleft", width=inch, height=inch),
        _PositionedText(top=1 * inch, left=4 * inch, text="rightA", width=inch, height=inch),
        _PositionedText(top=5 * inch, left=4 * inch, text="rightB", width=inch, height=inch),
    ]
    lines = _reading_order(items)
    assert lines == ["topleft", "bottomleft", "rightA", "rightB"]


def test_a_single_wide_block_is_not_split() -> None:
    """A bullet list is one text frame, so no gutter exists to split — but a wide shape
    beside a narrow one must not be cut on ordinary spacing either."""
    inch = 914400
    items = [
        _PositionedText(top=1 * inch, left=1 * inch, text="a bullet", width=6 * inch),
        _PositionedText(top=2 * inch, left=1 * inch, text="another bullet", width=6 * inch),
    ]
    assert _reading_order(items) == ["a bullet", "another bullet"]


def test_uniform_column_gaps_do_not_split_a_single_table() -> None:
    """A table whose cells are separated by equal gaps has no dominant gutter, so it must
    be read as one table. An absolute threshold alone cannot decide this: a real gutter
    measured on this corpus is 0.59in, narrower than some tables' column spacing."""
    inch = 914400
    items = []
    for row, values in enumerate([("PNO", "PNAME", "BUDGET"), ("P1", "Instr.", "150000")]):
        for col, text in enumerate(values):
            items.append(
                _PositionedText(
                    top=(row + 1) * inch,
                    left=(col * 2 + 1) * inch,
                    text=text,
                    width=inch + inch // 2,  # 0.5in gaps, uniform
                )
            )
    assert _reading_order(items) == ["PNO | PNAME | BUDGET", "P1 | Instr. | 150000"]
