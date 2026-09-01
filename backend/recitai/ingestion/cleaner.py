"""Strip boilerplate that survives extraction (spec §9 task 3).

Three problems, in order of impact:

1. Running headers and footers. A line repeating on most pages is furniture, not content.
   Left in, it is indexed, embedded, and eventually quizzed on.
2. Hyphenation across line breaks. "distrib-\\nuted" must become "distributed" or the
   token never matches anything.
3. Standalone page numbers, which survive as one-token lines.

Detection is frequency-based rather than positional, because slide decks put their
furniture wherever the template does.
"""

import re
from collections import Counter

from recitai.ingestion.parser import ParsedDocument, ParsedPage

#: A line appearing on more than this fraction of pages is furniture (§9 task 3).
REPEAT_THRESHOLD = 0.60

#: Below this many pages, "repeats on 60%" is noise — 2 of 3 pages proves nothing.
MIN_PAGES_FOR_REPEAT_DETECTION = 5

_PAGE_NUMBER = re.compile(
    r"^\s*(?:page\s*)?[-–—(\[]?\s*\d{1,4}\s*(?:/\s*\d{1,4})?\s*[-–—)\]]?\s*$", re.I
)
_HYPHEN_BREAK = re.compile(r"(\w+)-\s*\n\s*(\w+)")
_MULTI_BLANK = re.compile(r"\n{3,}")

#: Numbered running footers: "Page 12", "Slide 3 of 40", "Ch. 2 — 15". Matched by shape,
#: and only on short lines, so a sentence that happens to contain a number survives.
_PAGE_MARKER = re.compile(
    r"^\s*\S{0,40}?\s*(?:page|slide|pg\.?|p\.)\s*\d{1,4}(?:\s*(?:of|/)\s*\d{1,4})?\s*$",
    re.I,
)
MAX_PAGE_MARKER_WORDS = 6


def _normalise(line: str) -> str:
    """Fingerprint for repeat detection: case and whitespace only.

    Digits are deliberately NOT normalised. Doing so collapses "Real content 1" and
    "Real content 2" — genuinely different material — into one fingerprint, so a slide
    series that numbers its examples would be detected as furniture and deleted whole.
    Numbered footers are handled by `_PAGE_MARKER` instead, which targets the shape of a
    page marker rather than the presence of a digit.
    """
    return re.sub(r"\s+", " ", line.strip().lower())


def find_repeated_lines(pages: list[ParsedPage], threshold: float = REPEAT_THRESHOLD) -> set[str]:
    """Fingerprints of lines that recur on more than `threshold` of pages."""
    if len(pages) < MIN_PAGES_FOR_REPEAT_DETECTION:
        return set()

    counts: Counter[str] = Counter()
    for page in pages:
        seen = {_normalise(line) for line in page.text.splitlines() if line.strip()}
        counts.update(seen)

    cutoff = threshold * len(pages)
    # A repeated line that is long is more likely a genuinely repeated definition than
    # furniture, so only short lines are eligible.
    return {fp for fp, n in counts.items() if n > cutoff and len(fp) <= 120}


def repair_hyphenation(text: str) -> str:
    return _HYPHEN_BREAK.sub(r"\1\2", text)


def clean_page(page: ParsedPage, furniture: set[str]) -> ParsedPage:
    kept: list[str] = []
    for line in page.text.splitlines():
        stripped = line.strip()
        if not stripped:
            kept.append("")
            continue
        if _normalise(stripped) in furniture:
            continue
        if _PAGE_NUMBER.match(stripped):
            continue
        if len(stripped.split()) <= MAX_PAGE_MARKER_WORDS and _PAGE_MARKER.match(stripped):
            continue
        kept.append(stripped)

    text = _MULTI_BLANK.sub("\n\n", repair_hyphenation("\n".join(kept))).strip()
    notes = _MULTI_BLANK.sub("\n\n", repair_hyphenation(page.notes)).strip()
    return ParsedPage(number=page.number, heading=page.heading, text=text, notes=notes)


def clean(document: ParsedDocument) -> ParsedDocument:
    """Return the document with furniture removed. Page numbering is never altered."""
    furniture = find_repeated_lines(document.pages)
    pages = [clean_page(p, furniture) for p in document.pages]

    from recitai.ingestion.parser import _assemble

    markdown, page_map = _assemble(pages)
    return ParsedDocument(
        filename=document.filename,
        source_kind=document.source_kind,
        pages=pages,
        sha256=document.sha256,
        markdown=markdown,
        page_map=page_map,
    )
