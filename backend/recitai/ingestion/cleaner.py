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

#: PowerPoint's Symbol font encodes characters in the Unicode Private Use Area at
#: U+F0xx, where xx is the Adobe Symbol code point. Extracted verbatim they are
#: meaningless outside that font and render as blank boxes — and worse, they carry the
#: mathematics: `{t | t ∈ R and t ∉ S}` extracts as `{t | t  R and t  S}`, which does not
#: say what the slide says. Measured on this corpus: 63% of chunks affected, `∈` alone
#: appearing 36 times. See plan/ISSUES.md I-031.
_SYMBOL_FONT_PUA = {
    # Greek lowercase (Adobe Symbol a–z)
    "a": "α",
    "b": "β",
    "c": "χ",
    "d": "δ",
    "e": "ε",
    "f": "φ",
    "g": "γ",
    "h": "η",
    "i": "ι",
    "j": "ϕ",
    "k": "κ",
    "l": "λ",
    "m": "μ",
    "n": "ν",
    "o": "ο",
    "p": "π",
    "q": "θ",
    "r": "ρ",
    "s": "σ",
    "t": "τ",
    "u": "υ",
    "v": "ϖ",
    "w": "ω",
    "x": "ξ",
    "y": "ψ",
    "z": "ζ",
    # Greek uppercase
    "A": "Α",
    "B": "Β",
    "C": "Χ",
    "D": "Δ",
    "E": "Ε",
    "F": "Φ",
    "G": "Γ",
    "H": "Η",
    "I": "Ι",
    "J": "ϑ",
    "K": "Κ",
    "L": "Λ",
    "M": "Μ",
    "N": "Ν",
    "O": "Ο",
    "P": "Π",
    "Q": "Θ",
    "R": "Ρ",
    "S": "Σ",
    "T": "Τ",
    "U": "Υ",
    "V": "ς",
    "W": "Ω",
    "X": "Ξ",
    "Y": "Ψ",
    "Z": "Ζ",
}
#: Non-letter Symbol code points, by their Adobe Symbol byte.
_SYMBOL_FONT_MATH = {
    0x22: "∀",
    0x24: "∃",
    0x27: "∋",
    0x2D: "−",
    0x40: "≅",
    0x5C: "∴",
    0xA3: "≤",
    0xA5: "∞",
    0xAC: "←",
    0xAE: "→",
    0xB0: "°",
    0xB1: "±",
    0xB3: "≥",
    0xB4: "×",
    0xB8: "÷",
    0xB9: "≠",
    0xBB: "≈",
    0xC7: "∩",
    0xC8: "∪",
    0xCC: "⊄",
    0xCD: "⊆",
    0xCE: "∈",
    0xCF: "∉",
    0xD0: "∠",
    0xD6: "√",
    0xD9: "∧",
    0xDA: "∨",
    0xDB: "⇔",
    0xDC: "⇐",
    0xDD: "⇒",
    0xDE: "⇑",
    0xE0: "◊",
    0xE1: "⟨",
    0xE5: "Σ",
    0xF1: "⟩",
}


def restore_symbol_font(text: str) -> str:
    """Map Symbol-font Private Use Area code points back to real Unicode.

    A character left in the PUA is not merely ugly: it silently removes an operator from a
    formula, so the passage no longer states what the slide states — and a question
    generated from it is grounded in text that lost its meaning.
    """
    if not any("\uf020" <= ch <= "\uf0ff" for ch in text):
        return text
    out: list[str] = []
    for ch in text:
        if "\uf020" <= ch <= "\uf0ff":
            code = ord(ch) - 0xF000
            letter = chr(code)
            out.append(_SYMBOL_FONT_PUA.get(letter) or _SYMBOL_FONT_MATH.get(code, ""))
        else:
            out.append(ch)
    return "".join(out)


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
    heading = restore_symbol_font(page.heading) if page.heading else page.heading
    return ParsedPage(
        number=page.number,
        heading=heading,
        text=restore_symbol_font(text),
        notes=restore_symbol_font(notes),
    )


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
