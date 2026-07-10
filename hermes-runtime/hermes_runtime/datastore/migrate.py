"""Raw-SQL migration runner for the Toee Business Datastore (ADR-0140, ADR-0142).

Plain ``.sql`` files in ``hermes-runtime/migrations/`` are applied in lexical
order; applied versions are tracked in a ``schema_migrations`` table so re-runs
are no-ops (idempotent). Raw SQL keeps migrations Cloud SQL-portable for the
deferred cloud slice — no ORM, no migration framework.

Run against the configured database::

    uv run python -m hermes_runtime.datastore.migrate
"""

from __future__ import annotations

import os
from collections.abc import Collection
from pathlib import Path

# hermes-runtime/hermes_runtime/datastore/migrate.py -> hermes-runtime/migrations
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

# LOCAL DEV ONLY seeds (ADR-0142): demo accounts + cases. The migrate() entrypoint
# excludes these by default so they never reach a cloud/prod database; local dev
# opts in with HERMES_APPLY_DEV_SEED=1 (see docs/ops/local-e2e.md).
DEV_ONLY_MIGRATIONS = frozenset({"0005_dev_bootstrap"})
_APPLY_DEV_SEED_ENV = "HERMES_APPLY_DEV_SEED"


def migrate_exclusions() -> frozenset[str]:
    """Migrations migrate() skips by default: the dev seed unless opted in."""
    if os.environ.get(_APPLY_DEV_SEED_ENV, "").strip().lower() in {"1", "true", "yes"}:
        return frozenset()
    return DEV_ONLY_MIGRATIONS


def discover_migrations(
    migrations_dir: Path = MIGRATIONS_DIR, *, exclude: Collection[str] = ()
) -> list[tuple[str, str]]:
    """Return ``[(version, sql)]`` for every ``*.sql`` file, sorted by version.

    ``exclude`` drops migrations by version (file stem) — the test harness uses it
    to skip the local-dev-only ``0005_dev_bootstrap`` seed in isolated schemas.
    """
    files = sorted(migrations_dir.glob("*.sql"))
    return [
        (path.stem, path.read_text(encoding="utf-8"))
        for path in files
        if path.stem not in exclude
    ]


def _ensure_bookkeeping(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def run_migrations(
    conn, migrations_dir: Path = MIGRATIONS_DIR, *, exclude: Collection[str] = ()
) -> list[str]:
    """Apply pending migrations on an open connection; return versions applied.

    Each migration runs in its own transaction (Postgres has transactional DDL),
    so a partial failure rolls back cleanly and leaves ``schema_migrations``
    accurate. The caller controls the connection (and therefore the search_path),
    which lets tests target a throwaway schema. ``exclude`` skips migrations by
    version (see :func:`discover_migrations`).
    """
    with conn.cursor() as cur:
        _ensure_bookkeeping(cur)
        conn.commit()
        cur.execute("SELECT version FROM schema_migrations")
        already_applied = {row[0] for row in cur.fetchall()}

    applied: list[str] = []
    for version, sql in discover_migrations(migrations_dir, exclude=exclude):
        if version in already_applied:
            continue
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s)", (version,)
            )
        conn.commit()
        applied.append(version)
    return applied


def migrate(url: str | None = None, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Connect to ``url`` (or the configured default) and apply pending migrations.

    Excludes LOCAL-DEV-ONLY seeds (:data:`DEV_ONLY_MIGRATIONS`) unless the caller
    opted in via ``HERMES_APPLY_DEV_SEED`` — so a cloud/prod migrate never seeds
    demo data (ADR-0142).
    """
    import psycopg

    from .config import database_url

    dsn = url or database_url()
    with psycopg.connect(dsn) as conn:
        return run_migrations(conn, migrations_dir, exclude=migrate_exclusions())


def main() -> None:
    applied = migrate()
    if applied:
        print("applied migrations: " + ", ".join(applied))
    else:
        print("no pending migrations")


if __name__ == "__main__":
    main()
