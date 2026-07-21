"""Unit tests for the knowledge-store DSN seam (FR-1, PRD §7.4).

Mirrors ``hermes_runtime/datastore/config.py``'s lazy resolution pattern, but
for the SEPARATE ``toee_knowledge`` database -- these never touch a real
Postgres connection, they only check env-var resolution logic.
"""

from __future__ import annotations

from hermes_runtime.knowledge.config import (
    DEFAULT_KNOWLEDGE_DATABASE_URL,
    knowledge_database_url,
)


def test_default_dsn_points_at_toee_knowledge_not_business_db(monkeypatch) -> None:
    monkeypatch.delenv("KNOWLEDGE_DATABASE_URL", raising=False)
    url = knowledge_database_url()
    assert url == DEFAULT_KNOWLEDGE_DATABASE_URL
    assert url == "postgresql://toee:toee@localhost:5432/toee_knowledge"
    assert "toee_va" not in url  # S-ISO: never defaults to the business DB


def test_env_var_overrides_default(monkeypatch) -> None:
    monkeypatch.setenv(
        "KNOWLEDGE_DATABASE_URL", "postgresql://x:y@otherhost:5432/toee_knowledge_test"
    )
    assert knowledge_database_url() == "postgresql://x:y@otherhost:5432/toee_knowledge_test"


def test_blank_env_var_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_DATABASE_URL", "   ")
    assert knowledge_database_url() == DEFAULT_KNOWLEDGE_DATABASE_URL


def test_resolving_the_dsn_makes_no_connection_attempt(monkeypatch) -> None:
    # Lazy seam: reading the DSN must never import/touch psycopg. Fail loudly if
    # it ever tries to connect.
    import sys

    import psycopg

    def _boom(*args, **kwargs):
        raise AssertionError("knowledge_database_url() must not connect to Postgres")

    monkeypatch.setattr(psycopg, "connect", _boom)
    monkeypatch.delenv("KNOWLEDGE_DATABASE_URL", raising=False)

    # Force a fresh import of the config module to prove it has no import-time
    # or call-time connection side effect.
    sys.modules.pop("hermes_runtime.knowledge.config", None)
    from hermes_runtime.knowledge.config import knowledge_database_url as fresh_url

    assert fresh_url() == DEFAULT_KNOWLEDGE_DATABASE_URL
