"""Reconcile the vector store against Postgres.

Postgres is the source of truth for what a passage *is*; Qdrant only holds an embedding
of it. Deleting a course cascades through Postgres but Qdrant knows nothing about that,
so a vector can outlive its row — and an orphaned vector is worse than a missing one: it
is a passage that no longer exists but is still retrievable by chat and explanations,
which quietly violates I2 (closed world).

`DELETE /courses/{id}` clears vectors before rows precisely so this cannot happen going
forward. This script exists for what the API cannot reach: vectors whose course row was
removed some other way, before that endpoint existed.

    uv run python ../scripts/reconcile_vectors.py            # report only
    uv run python ../scripts/reconcile_vectors.py --fix      # delete the orphans
"""

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select  # noqa: E402

from recitai.db.models import Chunk, Course  # noqa: E402
from recitai.db.session import session_scope  # noqa: E402
from recitai.retrieval.vector_store import VectorStore  # noqa: E402


async def main(fix: bool) -> int:
    async with session_scope() as session:
        rows = {str(cid) for cid in (await session.execute(select(Chunk.id))).scalars()}
        courses = {str(cid) for cid in (await session.execute(select(Course.id))).scalars()}

    # Uploaded files live in a directory named for their course and are not covered by any
    # cascade either, so a deleted course can leave its slides on disk.
    from recitai.config import settings

    root = Path(settings.materials_dir)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[1] / root
    uploads = root / "uploads"
    stray = (
        sorted(d for d in uploads.iterdir() if d.is_dir() and d.name not in courses)
        if uploads.exists()
        else []
    )

    store = VectorStore()
    try:
        points: list[str] = []
        offset = None
        while True:
            batch, offset = await store._client.scroll(
                store.collection, limit=256, offset=offset, with_payload=False, with_vectors=False
            )
            points.extend(str(p.id) for p in batch)
            if offset is None:
                break

        orphans = sorted(set(points) - rows)
        missing = sorted(rows - set(points))

        print(f"postgres chunks : {len(rows)}")
        print(f"qdrant points   : {len(points)}")
        print(f"orphans         : {len(orphans)}  (vector with no row — retrievable but deleted)")
        print(f"missing vectors : {len(missing)}  (row with no vector — invisible to search)")
        print(f"stray uploads   : {len(stray)}  (files for a course that no longer exists)")

        for oid in orphans:
            print(f"  orphan {oid}")
        for mid in missing:
            print(f"  missing {mid}")
        for d in stray:
            print(f"  stray   {d.name}/  ({', '.join(f.name for f in d.iterdir())})")

        if stray and fix:
            import shutil

            for d in stray:
                shutil.rmtree(d, ignore_errors=True)
            print(f"removed {len(stray)} stray upload folder(s)")

        if orphans and fix:
            await store._client.delete(
                store.collection, points_selector=[uuid.UUID(o) for o in orphans]
            )
            print(f"\ndeleted {len(orphans)} orphaned vector(s)")
        elif orphans or stray:
            print("\nre-run with --fix to clean up")

        # A missing vector cannot be repaired here — it needs the text re-embedded, which
        # is what `make ingest F=... --force` does.
        return 1 if (missing or ((orphans or stray) and not fix)) else 0
    finally:
        await store.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main("--fix" in sys.argv)))
