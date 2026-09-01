"""Verify the backing services are reachable *and are the ones we think they are*.

Container healthchecks are not sufficient. `pg_isready` reports healthy without
authenticating, and a host process occupying the mapped port will answer instead of the
container — that combination silently pointed the app at a different database entirely
(plan/ISSUES.md I-020). This connects the way the application does, with the credentials
the application uses, and asserts identity.

Run by `make dev`. Exits non-zero on failure.
"""

import asyncio
import sys

from recitai.config import settings
from recitai.constants import EMBEDDING_DIM

PROBE_COLLECTION = "_service_check_probe"


async def check_postgres() -> str | None:
    import asyncpg

    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    try:
        conn = await asyncpg.connect(dsn, timeout=10)
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return f"postgres unreachable at {dsn}: {type(exc).__name__}: {exc}"
    try:
        user, db = await conn.fetchrow("SELECT current_user, current_database()")
        version = await conn.fetchval("SHOW server_version")
    finally:
        await conn.close()
    if (user, db) != ("recitai", "recitai"):
        return f"connected to the wrong database: {user}@{db} (expected recitai@recitai)"
    print(f"  postgres OK  {user}@{db}, server {version}")
    return None


async def check_qdrant() -> str | None:
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

    client = AsyncQdrantClient(url=settings.qdrant_url, timeout=10)
    try:
        if await client.collection_exists(PROBE_COLLECTION):
            await client.delete_collection(PROBE_COLLECTION)
        await client.create_collection(
            PROBE_COLLECTION,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )
        await client.upsert(
            PROBE_COLLECTION,
            points=[PointStruct(id=1, vector=[0.1] * EMBEDDING_DIM, payload={"probe": True})],
        )
        hits = await client.query_points(PROBE_COLLECTION, query=[0.1] * EMBEDDING_DIM, limit=1)
        if not hits.points:
            return "qdrant accepted an upsert but returned no results for it"
        await client.delete_collection(PROBE_COLLECTION)
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return f"qdrant round-trip failed at {settings.qdrant_url}: {type(exc).__name__}: {exc}"
    finally:
        await client.close()
    print(f"  qdrant OK    upsert+search round-trip at dim {EMBEDDING_DIM}")
    return None


async def main() -> int:
    print("checking backing services...")
    failures = [f for f in await asyncio.gather(check_postgres(), check_qdrant()) if f]
    if failures:
        print("\nSERVICE CHECK FAILED", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("services OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
