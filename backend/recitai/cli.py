"""Command line interface (spec §9 task 9)."""

import asyncio
import uuid
from pathlib import Path

import typer
from sqlalchemy import func, select

from recitai.db.models import Chunk, Course, Document
from recitai.db.session import session_scope
from recitai.ingestion.pipeline import ingest as run_ingest
from recitai.llm.ollama import OllamaClient
from recitai.retrieval.vector_store import VectorStore

app = typer.Typer(add_completion=False, help="RecitAI — local-first study partner")


@app.command()
def ingest(
    path: Path = typer.Argument(..., exists=True, help="A document, or a directory of them"),
    course: str = typer.Option(..., "--course", "-c", help="Course name"),
    force: bool = typer.Option(False, "--force", help="Re-ingest even if unchanged"),
) -> None:
    """Ingest a document or directory into a course."""

    async def _run() -> int:
        client = OllamaClient()
        store = VectorStore()
        try:
            results = await run_ingest(path, course, client, store, force=force)
        except FileNotFoundError as exc:
            # A mistyped path or a directory of unsupported files is ordinary user error;
            # it deserves a message, not a stack trace.
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            return 1
        finally:
            await client.aclose()
            await store.aclose()

        failed = 0
        for r in results:
            if r.status == "complete":
                typer.echo(
                    f"  {r.filename}: {r.page_count} pages -> {r.chunk_count} chunks, "
                    f"{r.vectors_written} vectors"
                )
            elif r.status == "skipped":
                typer.echo(f"  {r.filename}: skipped ({r.skipped_reason})")
            else:
                failed += 1
                typer.secho(f"  {r.filename}: FAILED — {r.error}", fg=typer.colors.RED, err=True)
        typer.echo(f"\n{len(results) - failed}/{len(results)} documents ingested")
        return 1 if failed else 0

    raise typer.Exit(asyncio.run(_run()))


@app.command()
def courses() -> None:
    """List courses with their document and chunk counts."""

    async def _run() -> None:
        async with session_scope() as session:
            rows = (await session.execute(select(Course).order_by(Course.created_at))).scalars()
            for c in rows:
                docs = await session.scalar(
                    select(func.count()).select_from(Document).where(Document.course_id == c.id)
                )
                chunks = await session.scalar(
                    select(func.count()).select_from(Chunk).where(Chunk.course_id == c.id)
                )
                typer.echo(f"{c.id}  {c.name}  ({docs} documents, {chunks} chunks)")

    asyncio.run(_run())


@app.command()
def documents(course_id: uuid.UUID = typer.Option(..., "--course")) -> None:
    """List a course's documents and their ingest status."""

    async def _run() -> None:
        async with session_scope() as session:
            rows = (
                await session.execute(
                    select(Document)
                    .where(Document.course_id == course_id)
                    .order_by(Document.filename)
                )
            ).scalars()
            for d in rows:
                detail = f" — {d.ingest_error}" if d.ingest_error else ""
                pages = f"{d.page_count or '?':>4}p"
                typer.echo(f"{d.id}  {d.ingest_status:<10} {pages}  {d.filename}{detail}")

    asyncio.run(_run())


@app.command()
def chunks(
    document: uuid.UUID = typer.Option(..., "--document", "-d"),
    limit: int = typer.Option(20, "--limit", "-n"),
    full: bool = typer.Option(False, "--full", help="Print entire chunk text"),
) -> None:
    """Inspect a document's chunks — the Phase 1 manual verification path (§9 VERIFY)."""

    async def _run() -> None:
        async with session_scope() as session:
            rows = (
                await session.execute(
                    select(Chunk)
                    .where(Chunk.document_id == document)
                    .order_by(Chunk.page_start)
                    .limit(limit)
                )
            ).scalars()
            for c in rows:
                pages = (
                    f"p{c.page_start}"
                    if c.page_start == c.page_end
                    else f"p{c.page_start}-{c.page_end}"
                )
                typer.secho(
                    f"\n─── {pages}  {c.token_count} tok  {c.content_type}  "
                    f"{' > '.join(c.section_path)}",
                    fg=typer.colors.CYAN,
                )
                typer.echo(c.text if full else c.text[:600] + ("…" if len(c.text) > 600 else ""))

    asyncio.run(_run())


if __name__ == "__main__":
    app()
