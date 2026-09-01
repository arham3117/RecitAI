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


@app.command()
def topics(course_id: uuid.UUID = typer.Option(..., "--course", "-c")) -> None:
    """Print the topic tree — should read like the actual syllabus (§10 VERIFY)."""

    async def _run() -> None:
        from recitai.retrieval.topic_map import topic_tree

        tree = await topic_tree(course_id)
        if not tree:
            typer.secho("no topics — run 'recitai map-topics' first", fg=typer.colors.YELLOW)
            return
        for unit, children in tree:
            typer.secho(f"\n{unit.name}  ({unit.chunk_count} chunks)", fg=typer.colors.CYAN)
            for child in children:
                typer.echo(f"  ├─ {child.name}  ({child.chunk_count})")

    asyncio.run(_run())


@app.command("map-topics")
def map_topics(course_id: uuid.UUID = typer.Option(..., "--course", "-c")) -> None:
    """Build the topic tree from chunk section paths (§10 task 2)."""

    async def _run() -> None:
        from recitai.retrieval.topic_map import build_topic_map

        created = await build_topic_map(course_id)
        typer.echo(f"{len(created)} topics mapped")

    asyncio.run(_run())


@app.command()
def search(
    course_id: uuid.UUID = typer.Option(..., "--course", "-c"),
    q: str = typer.Option(..., "--q", help="Query text"),
    k: int = typer.Option(5, "--k"),
) -> None:
    """Path B similarity search. Never used to choose chunks for generation."""

    async def _run() -> None:
        from recitai.retrieval.search import search as run_search

        client = OllamaClient()
        store = VectorStore()
        try:
            hits = await run_search(q, client, store, course_id=course_id, limit=k)
        finally:
            await client.aclose()
            await store.aclose()
        for h in hits:
            path = " > ".join(h.section_path)
            typer.echo(f"{h.score:.3f}  p{h.page_start}-{h.page_end}  {path}")

    asyncio.run(_run())


@app.command()
def sample(
    course_id: uuid.UUID = typer.Option(..., "--course", "-c"),
    n: int = typer.Option(20, "--n"),
    topic: list[uuid.UUID] = typer.Option([], "--topic", help="Restrict to these topics"),
    seed: int = typer.Option(None, "--seed", help="Fixed seed makes output reproducible"),
) -> None:
    """Path A coverage sampling — what quiz generation actually uses (§3.3)."""

    async def _run() -> None:
        from recitai.retrieval.resolver import Scope
        from recitai.retrieval.sampler import sample_chunks

        scope = Scope(course_id=course_id, topic_ids=list(topic))
        chunks, report = await sample_chunks(scope, n, seed=seed)
        for c in chunks:
            path = " > ".join(c.section_path)
            typer.echo(
                f"p{c.page_start}-{c.page_end}  {c.token_count:>4}tok  "
                f"used={c.quiz_usage_count}  {path}"
            )
        typer.secho(
            f"\n{report.delivered}/{report.requested} chunks   "
            f"topics {report.topics_covered}/{report.topics_in_scope} "
            f"({report.coverage:.0%} coverage)",
            fg=typer.colors.CYAN,
        )
        if report.shortfall_reason:
            typer.secho(f"shortfall: {report.shortfall_reason}", fg=typer.colors.YELLOW)

    asyncio.run(_run())


if __name__ == "__main__":
    app()
