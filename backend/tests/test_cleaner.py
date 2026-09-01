"""Cleaner tests — spec §9 task 3."""

from recitai.ingestion.cleaner import clean_page, find_repeated_lines, repair_hyphenation
from recitai.ingestion.parser import ParsedPage


def test_repeated_footer_is_detected_and_stripped() -> None:
    pages = [
        ParsedPage(number=i, heading=f"T{i}", text=f"Real content {i}\nDistributed DBMS 2024")
        for i in range(1, 11)
    ]
    furniture = find_repeated_lines(pages)
    assert furniture, "a line on every page is furniture"
    cleaned = clean_page(pages[0], furniture)
    assert "Real content 1" in cleaned.text
    assert "Distributed DBMS" not in cleaned.text


def test_numbered_content_is_not_mistaken_for_furniture() -> None:
    """Digit-insensitive fingerprints would collapse "Example 1"/"Example 2" into one
    repeated line and delete a whole slide series."""
    pages = [
        ParsedPage(number=i, heading=None, text=f"Example {i} shows a horizontal fragment.")
        for i in range(1, 11)
    ]
    furniture = find_repeated_lines(pages)
    cleaned = clean_page(pages[0], furniture)
    assert "Example 1 shows a horizontal fragment." in cleaned.text


def test_numbered_footers_are_stripped_by_shape() -> None:
    """ "Slide 3 of 10" differs on every page, so repeat detection cannot catch it. It is
    removed by matching the shape of a page marker instead."""
    page = ParsedPage(number=3, heading=None, text="Body text here.\nSlide 3 of 10")
    cleaned = clean_page(page, set())
    assert "Slide 3 of 10" not in cleaned.text
    assert "Body text here." in cleaned.text


def test_short_documents_are_left_alone() -> None:
    """On three pages, 'appears on 60%' proves nothing."""
    pages = [ParsedPage(number=i, heading=None, text="Shared line") for i in range(1, 4)]
    assert find_repeated_lines(pages) == set()


def test_hyphenation_across_line_breaks_is_repaired() -> None:
    assert repair_hyphenation("distrib-\nuted database") == "distributed database"


def test_standalone_page_numbers_are_dropped() -> None:
    page = ParsedPage(number=1, heading=None, text="Real sentence.\n42\nMore text.")
    cleaned = clean_page(page, set())
    assert "42" not in cleaned.text.split()
    assert "Real sentence." in cleaned.text
