"""Render actual slide images for the explanation panel.

The extracted text tells a student *what* the slide says; the slide itself shows the
diagram, the table layout and the notation the text cannot carry. On this corpus 12% of
slides are diagram-only ([I-018]) — for those, text is close to useless and an image is
the whole content.

Two ways to get a picture of a slide, tried in order:

1. **A PDF exported beside the deck** — `2-Background.pdf` next to `2-Background.pptx`.
   Costs a one-off "Save as PDF" per deck and no dependency at all. PyMuPDF rasterises it.
2. **LibreOffice**, if installed, converting the deck to PDF on demand and caching it.

If neither is available the panel falls back to the extracted text, which is what it did
before — the feature degrades rather than breaks.

Note this does not revisit [D-008]: text extraction stays with `python-pptx`, which keeps
per-slide numbering, headings and speaker notes. LibreOffice is used here only to draw a
picture, which is the one thing it is better at.
"""

import hashlib
import shutil
import subprocess
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

#: Wide enough to read a dense table on a laptop, small enough to send over a slow link.
RENDER_WIDTH_PX = 1400

#: LibreOffice on a cold start is slow; a deck of 65 slides can take a while.
CONVERT_TIMEOUT_SECONDS = 180

_SOFFICE_CANDIDATES = (
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "soffice",
    "libreoffice",
)


def cache_dir() -> Path:
    path = Path.home() / ".cache" / "recitai" / "slides"
    path.mkdir(parents=True, exist_ok=True)
    return path


def find_soffice() -> str | None:
    for candidate in _SOFFICE_CANDIDATES:
        if candidate.startswith("/") and Path(candidate).exists():
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
    return None


def companion_pdf(source: Path) -> Path | None:
    """A PDF exported beside the deck, if the user made one."""
    sibling = source.with_suffix(".pdf")
    return sibling if sibling.exists() else None


def _converted_pdf(source: Path) -> Path | None:
    """Convert with LibreOffice, cached by content hash so it runs once per file."""
    soffice = find_soffice()
    if soffice is None:
        return None
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
    cached = cache_dir() / f"{digest}.pdf"
    if cached.exists():
        return cached

    out_dir = cache_dir() / digest
    out_dir.mkdir(exist_ok=True)
    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(source)],
            check=True,
            capture_output=True,
            timeout=CONVERT_TIMEOUT_SECONDS,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        log.warning("slide_images.convert_failed", file=source.name, error=str(exc)[:200])
        return None

    produced = next(iter(out_dir.glob("*.pdf")), None)
    if produced is None:
        return None
    produced.replace(cached)
    shutil.rmtree(out_dir, ignore_errors=True)
    return cached


def pdf_for(source: Path) -> Path | None:
    """The PDF to rasterise, however we can get one."""
    if source.suffix.lower() == ".pdf":
        return source
    return companion_pdf(source) or _converted_pdf(source)


def render_slide(source: Path, page: int) -> bytes | None:
    """A PNG of one slide, 1-indexed. None when no picture can be produced."""
    pdf = pdf_for(source)
    if pdf is None:
        return None

    digest = hashlib.sha256(f"{pdf}:{pdf.stat().st_mtime_ns}:{page}".encode()).hexdigest()[:16]
    cached = cache_dir() / f"{digest}-{page}.png"
    if cached.exists():
        return cached.read_bytes()

    import pymupdf

    with pymupdf.open(pdf) as document:
        if not 1 <= page <= document.page_count:
            return None
        rendered = document[page - 1]
        zoom = RENDER_WIDTH_PX / max(rendered.rect.width, 1)
        pixmap = rendered.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        data: bytes = pixmap.tobytes("png")

    cached.write_bytes(data)
    return data


def availability(source: Path) -> str:
    """Why a slide image is or is not available, for the API to report honestly."""
    if source.suffix.lower() == ".pdf":
        return "pdf"
    if companion_pdf(source):
        return "companion-pdf"
    if find_soffice():
        return "libreoffice"
    return "unavailable"
