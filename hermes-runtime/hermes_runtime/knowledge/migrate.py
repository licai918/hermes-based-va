"""Raw-SQL migration runner for the Toee Knowledge Store (FR-1, PRD §7.4).

Own migration path, separate from the business datastore
(``hermes_runtime/datastore/migrate.py``): plain ``.sql`` files in
``hermes-runtime/knowledge_migrations/`` (own directory, own numbering
starting at 0001 -- not a shared sequence with ``hermes-runtime/migrations/``),
applied in lexical order against the separate ``toee_knowledge`` database via
``KNOWLEDGE_DATABASE_URL``. Applied versions are tracked in this database's own
``schema_migrations`` bookkeeping table (no collision with the business
datastore's table of the same name -- they live in different databases), so
re-runs are no-ops (idempotent).

Run against the configured knowledge database::

    uv run python -m hermes_runtime.knowledge.migrate
"""

from __future__ import annotations

from pathlib import Path

# hermes-runtime/hermes_runtime/knowledge/migrate.py -> hermes-runtime/knowledge_migrations
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "knowledge_migrations"


def discover_migrations(migrations_dir: Path = MIGRATIONS_DIR) -> list[tuple[str, str]]:
    """Return ``[(version, sql)]`` for every ``*.sql`` file, sorted by version."""
    files = sorted(migrations_dir.glob("*.sql"))
    return [(path.stem, path.read_text(encoding="utf-8")) for path in files]


def _ensure_bookkeeping(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def run_migrations(conn, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations on an open connection; return versions applied.

    Each migration runs in its own transaction (Postgres has transactional DDL),
    so a partial failure rolls back cleanly and leaves ``schema_migrations``
    accurate. The caller controls the connection (and therefore the search_path),
    which lets tests target a throwaway schema on the knowledge database.
    """
    with conn.cursor() as cur:
        _ensure_bookkeeping(cur)
        conn.commit()
        cur.execute("SELECT version FROM schema_migrations")
        already_applied = {row[0] for row in cur.fetchall()}

    applied: list[str] = []
    for version, sql in discover_migrations(migrations_dir):
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
    """Connect to ``url`` (or the configured knowledge DSN) and apply pending
    migrations. Never touches the business datastore -- a distinct DSN, a
    distinct connection."""
    import psycopg

    from .config import knowledge_database_url

    dsn = url or knowledge_database_url()
    with psycopg.connect(dsn) as conn:
        return run_migrations(conn, migrations_dir)


def main() -> None:
    applied = migrate()
    if applied:
        print("applied migrations: " + ", ".join(applied))
    else:
        print("no pending migrations")


if __name__ == "__main__":
    main()
