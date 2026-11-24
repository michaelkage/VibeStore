from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path

import asyncpg

from app.config import get_settings

_MIGRATION_NAME = re.compile(r"^[0-9]{3}_[a-z0-9_]+\.sql$")
_LOCK_KEY = "vibestore_schema_migrations"


def _database_dsn() -> str:
    value = get_settings().database_url
    if value.startswith("postgresql+asyncpg://"):
        return value.replace("postgresql+asyncpg://", "postgresql://", 1)
    return value


async def apply_migrations() -> list[str]:
    migration_dir = Path(__file__).resolve().parent.parent / "migrations"
    files = sorted(migration_dir.glob("*.sql"))
    if not files:
        raise RuntimeError(f"No SQL migrations found in {migration_dir}")
    for path in files:
        if not _MIGRATION_NAME.fullmatch(path.name):
            raise RuntimeError(f"Invalid migration filename: {path.name}")

    connection = await asyncpg.connect(_database_dsn())
    applied_now: list[str] = []
    try:
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await connection.execute(
            "SELECT pg_advisory_lock(hashtext($1))",
            _LOCK_KEY,
        )
        try:
            for path in files:
                source = path.read_text(encoding="utf-8")
                checksum = hashlib.sha256(source.encode("utf-8")).hexdigest()
                existing = await connection.fetchrow(
                    "SELECT checksum FROM schema_migrations WHERE version = $1",
                    path.name,
                )
                if existing is not None:
                    if existing["checksum"] != checksum:
                        raise RuntimeError(
                            f"Applied migration {path.name} has changed; "
                            "create a new migration instead of editing history"
                        )
                    continue

                async with connection.transaction():
                    await connection.execute(source)
                    await connection.execute(
                        """
                        INSERT INTO schema_migrations (version, checksum)
                        VALUES ($1, $2)
                        """,
                        path.name,
                        checksum,
                    )
                applied_now.append(path.name)
        finally:
            await connection.execute(
                "SELECT pg_advisory_unlock(hashtext($1))",
                _LOCK_KEY,
            )
    finally:
        await connection.close()
    return applied_now


async def main() -> None:
    applied = await apply_migrations()
    if applied:
        print("Applied migrations: " + ", ".join(applied))
    else:
        print("Database schema is already up to date.")


if __name__ == "__main__":
    asyncio.run(main())
