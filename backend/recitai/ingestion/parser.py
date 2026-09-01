"""Document → pages of text, with correct page attribution (spec §9 tasks 1–2).

Page attribution is non-negotiable (invariant I1): a citation that names the wrong page
teaches a student to distrust every other citation. The page map is therefore built
first, from the source's own structure, and never inferred afterwards.

Dispatch is by file extension (D-008). `.pptx` is parsed with `python-pptx` rather than
PyMuPDF, which accepts the format without error but flattens every slide onto one page
and discards speaker notes (I-014). An unknown extension fails loudly rather than falling
through to a parser that would accept the file and mis-attribute it.
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import structlog

log = structlog.get_logger(__name__)

SourceKind = Literal["pdf", "pptx"]

#: Below this, a PDF is assumed to be scanned images rather than text (§9 task 2).
#: Deliberately NOT applied to slide decks: sparse text is normal there, not a failure
#: signal (I-016).
MIN_CHARS_PER_PAGE_PDF = 100


class UnsupportedFormatError(ValueError):
    """The file extension has no parser. Never fall back to a lenient one."""


class ScannedDocumentError(ValueError):
    """A PDF with too little extractable text. OCR is deferred (§9 task 2)."""


@dataclass(frozen=True)
class ParsedPage:
    """One page of a PDF, or one slide of a deck."""

    number: int  # 1-based, as a student would cite it
    heading: str | None
    text: str
    notes: str = ""

    @property
    def content(self) -> str:
        """Body plus speaker notes.

        Notes are included because on a lecture deck they are often the only prose, and
        they carry the misconceptions §4.5's distractors are built from.
        """
        if self.notes:
            return f"{self.text}\n\n[notes] {self.notes}".strip()
        return self.text


@dataclass(frozen=True)
class PageSpan:
    """Maps a character range of the assembled markdown back to a page."""

    start: int
    end: int
    page: int


@dataclass(frozen=True)
class ParsedDocument:
    filename: str
    source_kind: SourceKind
    pages: list[ParsedPage]
    sha256: str
    markdown: str = ""
    page_map: list[PageSpan] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def page_for_offset(self, offset: int) -> int:
        """Resolve a character offset in `markdown` to its page number (§9 task 1)."""
        for span in self.page_map:
            if span.start <= offset < span.end:
                return span.page
        if not self.page_map:
            raise ValueError("document has no pages")
        return self.page_map[-1].page


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _assemble(pages: list[ParsedPage]) -> tuple[str, list[PageSpan]]:
    """Concatenate pages into one markdown string, recording each page's char range."""
    parts: list[str] = []
    spans: list[PageSpan] = []
    cursor = 0
    for page in pages:
        block = ""
        if page.heading:
            block += f"## {page.heading}\n\n"
        block += page.content
        block += "\n\n"
        parts.append(block)
        spans.append(PageSpan(start=cursor, end=cursor + len(block), page=page.number))
        cursor += len(block)
    return "".join(parts), spans


# --------------------------------------------------------------------------- PPTX ----


#: Shapes whose tops fall within this many EMU are treated as one visual row.
#: 914400 EMU = 1 inch; ~0.12in is about one line of body text on a slide.
_ROW_BAND_EMU = 109728


@dataclass(frozen=True)
class _PositionedText:
    top: int
    left: int
    text: str


def _pptx_shape_text(shape: Any, title_id: int | None) -> list[_PositionedText]:
    """Text from one shape, with its position, recursing into groups.

    Position matters because slide decks routinely build "tables" out of dozens of
    individually placed text boxes. python-pptx yields shapes in XML (z-order) order,
    which scrambles them — on a real slide in this corpus, the P3 row precedes the P2 row
    and every value is separated from its column header. Text ordered that way cannot
    support a correct question, so reading order is reconstructed from geometry below.
    """
    out: list[_PositionedText] = []
    if getattr(shape, "shape_id", None) == title_id:
        return out

    top = getattr(shape, "top", None)
    left = getattr(shape, "left", None)

    # Groups nest arbitrarily; their text is real content and is easy to lose.
    if getattr(shape, "shape_type", None) is not None and hasattr(shape, "shapes"):
        for child in shape.shapes:
            out.extend(_pptx_shape_text(child, title_id))
        return out

    if getattr(shape, "has_table", False) and shape.has_table:
        for row_index, row in enumerate(shape.table.rows):
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                out.append(
                    _PositionedText(
                        top=(top or 0) + row_index, left=left or 0, text=" | ".join(cells)
                    )
                )
        return out

    if getattr(shape, "has_text_frame", False):
        text = shape.text_frame.text.strip()
        if text:
            # A shape with no explicit position inherits the layout's; sort it last rather
            # than pretending it sits at the top of the slide.
            out.append(
                _PositionedText(
                    top=top if top is not None else 1 << 40,
                    left=left if left is not None else 0,
                    text=text,
                )
            )
    return out


def _reading_order(items: list[_PositionedText]) -> list[str]:
    """Group positioned text into visual rows, top to bottom then left to right.

    Cells sharing a row are joined with " | " so a header row and its values stay on one
    line — the association between "BUDGET" and "150000" is the whole content of the
    slide, and it is lost the moment they land on separate lines.
    """
    if not items:
        return []
    ordered = sorted(items, key=lambda i: (i.top, i.left))
    rows: list[list[_PositionedText]] = [[ordered[0]]]
    for item in ordered[1:]:
        if abs(item.top - rows[-1][0].top) <= _ROW_BAND_EMU:
            rows[-1].append(item)
        else:
            rows.append([item])

    lines: list[str] = []
    for row in rows:
        cells = [c.text for c in sorted(row, key=lambda i: i.left)]
        if len(cells) == 1:
            lines.append(cells[0])
        else:
            lines.append(" | ".join(cells))
    return lines


def parse_pptx(path: Path) -> ParsedDocument:
    from pptx import Presentation

    prs = Presentation(str(path))
    pages: list[ParsedPage] = []

    for index, slide in enumerate(prs.slides, start=1):
        title_shape = slide.shapes.title
        # Capture the id once: `shapes.title` returns a fresh proxy on each access, so an
        # identity comparison inside the loop silently fails and duplicates the title into
        # the body of every slide.
        title_id = title_shape.shape_id if title_shape is not None else None
        heading = None
        if title_shape is not None and title_shape.has_text_frame:
            heading = title_shape.text_frame.text.strip() or None

        positioned: list[_PositionedText] = []
        for shape in slide.shapes:
            positioned.extend(_pptx_shape_text(shape, title_id))
        body = _reading_order(positioned)

        notes = ""
        if slide.has_notes_slide:
            frame = slide.notes_slide.notes_text_frame
            if frame is not None and frame.text:
                notes = frame.text.strip()

        pages.append(
            ParsedPage(number=index, heading=heading, text="\n".join(body).strip(), notes=notes)
        )

    markdown, page_map = _assemble(pages)
    return ParsedDocument(
        filename=path.name,
        source_kind="pptx",
        pages=pages,
        sha256=sha256_file(path),
        markdown=markdown,
        page_map=page_map,
    )


# ---------------------------------------------------------------------------- PDF ----


def parse_pdf(path: Path) -> ParsedDocument:
    import pymupdf4llm

    page_dicts = pymupdf4llm.to_markdown(str(path), page_chunks=True)
    pages: list[ParsedPage] = []
    for index, page in enumerate(page_dicts, start=1):
        text = (page.get("text") or "").strip()
        pages.append(ParsedPage(number=index, heading=None, text=text))

    total_chars = sum(len(p.text) for p in pages)
    if pages and total_chars / len(pages) < MIN_CHARS_PER_PAGE_PDF:
        raise ScannedDocumentError(
            f"{path.name}: {total_chars} characters across {len(pages)} pages "
            f"({total_chars / len(pages):.0f}/page) is below the {MIN_CHARS_PER_PAGE_PDF}/page "
            f"floor — this looks like a scanned document. OCR is not supported."
        )

    markdown, page_map = _assemble(pages)
    return ParsedDocument(
        filename=path.name,
        source_kind="pdf",
        pages=pages,
        sha256=sha256_file(path),
        markdown=markdown,
        page_map=page_map,
    )


# ----------------------------------------------------------------------- dispatch ----

PARSERS = {".pptx": parse_pptx, ".pdf": parse_pdf}


def parse(path: Path) -> ParsedDocument:
    """Parse a document by extension. Raises rather than guessing (D-008)."""
    suffix = path.suffix.lower()
    parser = PARSERS.get(suffix)
    if parser is None:
        raise UnsupportedFormatError(
            f"{path.name}: no parser for '{suffix}'. Supported: {', '.join(sorted(PARSERS))}. "
            f"Legacy .ppt, Keynote and Google Slides must be re-saved as .pptx — never "
            f"exported to PDF, which discards speaker notes and slide structure (D-008)."
        )
    doc = parser(path)
    log.info(
        "parsed",
        filename=doc.filename,
        kind=doc.source_kind,
        pages=doc.page_count,
        chars=len(doc.markdown),
    )
    return doc
