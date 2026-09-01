"""Structure-aware chunking (spec §9 tasks 4–5, D-009).

Two strategies over one interface, chosen by measured text density rather than by file
type — a slide-shaped PDF chunks like a deck, not like a textbook (§9, "slide-deck
handling").

**Prose** (§9 task 4): split on headings; oversized sections split again on paragraph
boundaries toward `TARGET_CHUNK_TOKENS` with `CHUNK_OVERLAP_RATIO` overlap. Tables and
fenced code are never split.

**Slides** (D-009): merge consecutive slides greedily toward `TARGET_CHUNK_TOKENS`,
capped at `MAX_CHUNK_TOKENS`, breaking on structural markers. The spec's rule — merge
only slides sharing a heading — was measured against this corpus and kept 13% of it
(I-017); these decks give nearly every slide its own title, so there is nothing for it to
merge.

Token counts come from tiktoken, which is *not* Llama's tokenizer. The constants in §4.1
are calibrated against it and only need to be consistent and reproducible (invariant I6),
not exact. Changing the tokenizer reshapes every chunk boundary in the corpus and
invalidates prior measurements — see I-008.
"""

import re
from dataclasses import dataclass
from functools import lru_cache

from recitai.constants import (
    CHUNK_OVERLAP_RATIO,
    MAX_CHUNK_TOKENS,
    MIN_CHUNK_TOKENS,
    TARGET_CHUNK_TOKENS,
)
from recitai.ingestion.parser import ParsedDocument, ParsedPage

#: A document whose median page is below this is slide-shaped (§9 slide-deck handling).
SLIDE_MEDIAN_TOKEN_THRESHOLD = 200

#: Headings that mark navigation rather than content. Merging across one of these joins
#: two unrelated sections into a single chunk.
_STRUCTURAL_HEADINGS = re.compile(
    r"^\s*(outline|agenda|contents?|table of contents|overview|references|"
    r"bibliography|questions?|summary|acknowledge?ments?|thank you)\s*$",
    re.I,
)

_TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$")
_FENCE = re.compile(r"^\s*```")


@dataclass(frozen=True)
class TextChunk:
    text: str
    page_start: int
    page_end: int
    section_path: list[str]
    token_count: int
    content_type: str = "prose"


@lru_cache(maxsize=1)
def _encoder():  # type: ignore[no-untyped-def]
    import tiktoken

    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    if not text.strip():
        return 0
    return len(_encoder().encode(text))


def median_page_tokens(pages: list[ParsedPage]) -> float:
    counts = sorted(count_tokens(p.content) for p in pages)
    if not counts:
        return 0.0
    mid = len(counts) // 2
    if len(counts) % 2:
        return float(counts[mid])
    return (counts[mid - 1] + counts[mid]) / 2


def is_slide_shaped(document: ParsedDocument) -> bool:
    if document.source_kind == "pptx":
        return True
    return median_page_tokens(document.pages) < SLIDE_MEDIAN_TOKEN_THRESHOLD


def _classify(text: str) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return "prose"
    if sum(1 for ln in lines if _TABLE_LINE.match(ln)) >= max(2, len(lines) // 2):
        return "table"
    if any(_FENCE.match(ln) for ln in lines):
        return "code"
    return "prose"


# -------------------------------------------------------------------------- slides ----


def chunk_slides(document: ParsedDocument, unit_name: str) -> list[TextChunk]:
    """D-009: greedy merge toward the token target, breaking on structural markers."""
    chunks: list[TextChunk] = []
    buffer: list[ParsedPage] = []
    buffer_tokens = 0

    def flush() -> None:
        nonlocal buffer, buffer_tokens
        if not buffer:
            return
        parts: list[str] = []
        for page in buffer:
            if page.heading:
                parts.append(f"### {page.heading}")
            if page.content:
                parts.append(page.content)
        text = "\n\n".join(parts).strip()
        if text:
            # section_path is a real hierarchy: the deck is the unit, the first heading in
            # the merged run names the topic. Phase 2 builds the topic tree from this.
            head = next((p.heading for p in buffer if p.heading), None)
            path = [unit_name] + ([head] if head else [])
            chunks.append(
                TextChunk(
                    text=text,
                    page_start=buffer[0].number,
                    page_end=buffer[-1].number,
                    section_path=path,
                    token_count=count_tokens(text),
                    content_type=_classify(text),
                )
            )
        buffer, buffer_tokens = [], 0

    for page in document.pages:
        heading = page.heading or ""
        page_tokens = count_tokens(page.content) + count_tokens(heading)

        if _STRUCTURAL_HEADINGS.match(heading):
            flush()
            continue  # navigation slides carry no examinable content

        if buffer and (
            buffer_tokens + page_tokens > TARGET_CHUNK_TOKENS
            or buffer_tokens + page_tokens > MAX_CHUNK_TOKENS
        ):
            flush()

        buffer.append(page)
        buffer_tokens += page_tokens

    flush()
    return _merge_undersized(chunks)


# --------------------------------------------------------------------------- prose ----


def _split_paragraphs(text: str) -> list[str]:
    """Paragraph split that keeps tables and fenced code intact (§9 task 4)."""
    blocks: list[str] = []
    current: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
            current.append(line)
            continue
        if not in_fence and not line.strip() and current:
            blocks.append("\n".join(current).strip())
            current = []
            continue
        # A table row must never be separated from the rows around it.
        if (
            not in_fence
            and _TABLE_LINE.match(line)
            and current
            and not _TABLE_LINE.match(current[-1])
        ):
            pass
        current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    return [b for b in blocks if b]


def chunk_prose(document: ParsedDocument, unit_name: str) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    for page in document.pages:
        blocks = _split_paragraphs(page.content)
        buffer: list[str] = []
        buffer_tokens = 0
        path = [unit_name] + ([page.heading] if page.heading else [])

        def emit(parts: list[str], _page: ParsedPage = page, _path: list[str] = path) -> None:
            # Loop variables are bound as defaults rather than captured: the closure is
            # only called within this iteration today, but a deferred call would silently
            # attribute the chunk to the last page of the document.
            text = "\n\n".join(parts).strip()
            if not text:
                return
            chunks.append(
                TextChunk(
                    text=text,
                    page_start=_page.number,
                    page_end=_page.number,
                    section_path=_path,
                    token_count=count_tokens(text),
                    content_type=_classify(text),
                )
            )

        for block in blocks:
            block_tokens = count_tokens(block)
            if buffer and buffer_tokens + block_tokens > TARGET_CHUNK_TOKENS:
                emit(buffer)
                # Overlap carries the tail of the previous chunk forward so a sentence
                # split across a boundary is still answerable from one chunk.
                overlap_budget = int(TARGET_CHUNK_TOKENS * CHUNK_OVERLAP_RATIO)
                tail: list[str] = []
                tail_tokens = 0
                for prev in reversed(buffer):
                    prev_tokens = count_tokens(prev)
                    if tail_tokens + prev_tokens > overlap_budget:
                        break
                    tail.insert(0, prev)
                    tail_tokens += prev_tokens
                buffer, buffer_tokens = tail, tail_tokens
            buffer.append(block)
            buffer_tokens += block_tokens
        emit(buffer)
    return _merge_undersized(chunks)


# ------------------------------------------------------------------------- shared ----


def _merge_undersized(chunks: list[TextChunk]) -> list[TextChunk]:
    """Merge any chunk below MIN_CHUNK_TOKENS into its neighbour (§9 task 4).

    Only within a section. Merging across a section boundary would produce a chunk whose
    recorded `section_path` describes just its first half, so a question drawn from the
    second half would cite the wrong section — a groundedness failure (I1) that no later
    stage can detect.

    A small section therefore stays small, and simply falls below
    MIN_CHUNK_TOKENS_FOR_GENERATION rather than being quietly padded with unrelated
    material. That is the honest outcome: §0.2 forbids relaxing a threshold to make thin
    material look usable.
    """
    if not chunks:
        return chunks

    out: list[TextChunk] = []
    for chunk in chunks:
        if (
            out
            and chunk.token_count < MIN_CHUNK_TOKENS
            and out[-1].token_count + chunk.token_count <= MAX_CHUNK_TOKENS
            and out[-1].section_path == chunk.section_path
        ):
            prev = out[-1]
            text = f"{prev.text}\n\n{chunk.text}"
            out[-1] = TextChunk(
                text=text,
                page_start=prev.page_start,
                page_end=chunk.page_end,
                section_path=prev.section_path,
                token_count=count_tokens(text),
                content_type=prev.content_type,
            )
        else:
            out.append(chunk)
    return out


def chunk_document(document: ParsedDocument, unit_name: str) -> list[TextChunk]:
    if is_slide_shaped(document):
        return chunk_slides(document, unit_name)
    return chunk_prose(document, unit_name)
