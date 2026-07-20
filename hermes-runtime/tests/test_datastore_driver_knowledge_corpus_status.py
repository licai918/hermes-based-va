"""Tests for ``toee_knowledge_ops.get_corpus_status`` (S11, FR-6).

Unlike every other ``toee_knowledge_ops`` action, this read is CROSS-DATABASE:
the datastore handler registry dispatches with the BUSINESS (``toee_va``)
connection (``PostgresDriver._acquire``), but corpus status lives on the
SEPARATE ``toee_knowledge`` database (S-ISO isolation invariant — see
``hermes_runtime/knowledge/config.py``). So the handler under test here is the
pure, injectable core (:func:`_corpus_status_from_conn`) exercised directly
against a throwaway knowledge schema (``temp_knowledge_schema_conn``,
conftest.py) — the same pattern the S08 retriever tests use for
``retrieve(conn=...)``. The full ``_get_corpus_status(conn, params, context)``
wrapper (which opens its own knowledge DSN connection) is exercised once via
the live ``KNOWLEDGE_DATABASE_URL`` to prove the wiring, and read-only-ness is
asserted by checking no bookkeeping/audit row appears on the connection.
"""

from __future__ import annotations

import pytest

from hermes_runtime.datastore.handlers.knowledge import (
    _corpus_status_from_conn,
    _get_corpus_status,
    knowledge_handlers,
)
from hermes_runtime.knowledge.migrate import run_migrations


def _insert_chunk(conn, *, page_id, page_type, title, url="https://example.test", created_at=None):
    with conn.cursor() as cur:
        if created_at is None:
            cur.execute(
                "INSERT INTO knowledge_chunk"
                " (page_id, page_type, title, url, chunk_index, chunk_text)"
                " VALUES (%s, %s, %s, %s, 0, 'body text')",
                (page_id, page_type, title, url),
            )
        else:
            cur.execute(
                "INSERT INTO knowledge_chunk"
                " (page_id, page_type, title, url, chunk_index, chunk_text, created_at)"
                " VALUES (%s, %s, %s, %s, 0, 'body text', %s)",
                (page_id, page_type, title, url, created_at),
            )
    conn.commit()


def test_registry_exposes_get_corpus_status() -> None:
    registry = knowledge_handlers()
    assert registry["toee_knowledge_ops"]["get_corpus_status"] is _get_corpus_status


def test_empty_corpus_reports_zero_counts_and_no_last_ingest(temp_knowledge_schema_conn) -> None:
    conn, _schema = temp_knowledge_schema_conn
    run_migrations(conn)

    status = _corpus_status_from_conn(conn)

    assert status == {
        "doc_count": 0,
        "chunk_count": 0,
        "last_ingest_at": None,
        "by_type": [],
    }


def test_counts_docs_by_distinct_page_id_and_chunks_by_row(temp_knowledge_schema_conn) -> None:
    conn, _schema = temp_knowledge_schema_conn
    run_migrations(conn)

    # Two chunks of the same doc (page_id p1) + one chunk of a second doc (p2):
    # 2 docs, 3 chunks.
    _insert_chunk(conn, page_id="p1", page_type="policy", title="Returns")
    _insert_chunk(conn, page_id="p1", page_type="policy", title="Returns")
    _insert_chunk(conn, page_id="p2", page_type="faq", title="Shipping FAQ")

    status = _corpus_status_from_conn(conn)

    assert status["doc_count"] == 2
    assert status["chunk_count"] == 3


def test_per_type_breakdown_is_grouped_and_sorted_by_page_type(temp_knowledge_schema_conn) -> None:
    conn, _schema = temp_knowledge_schema_conn
    run_migrations(conn)

    _insert_chunk(conn, page_id="p1", page_type="policy", title="Returns")
    _insert_chunk(conn, page_id="p2", page_type="faq", title="Shipping FAQ")
    _insert_chunk(conn, page_id="p3", page_type="faq", title="Another FAQ")

    status = _corpus_status_from_conn(conn)

    assert status["by_type"] == [
        {"page_type": "faq", "count": 2},
        {"page_type": "policy", "count": 1},
    ]


def test_last_ingest_at_is_the_max_created_at_as_iso_string(temp_knowledge_schema_conn) -> None:
    conn, _schema = temp_knowledge_schema_conn
    run_migrations(conn)

    _insert_chunk(
        conn, page_id="p1", page_type="policy", title="Returns",
        created_at="2026-01-01T00:00:00+00:00",
    )
    _insert_chunk(
        conn, page_id="p2", page_type="policy", title="Newer",
        created_at="2026-06-15T12:30:00+00:00",
    )

    status = _corpus_status_from_conn(conn)

    assert status["last_ingest_at"] == "2026-06-15T12:30:00+00:00"


def test_get_corpus_status_is_read_only_no_audit_row_on_the_business_conn(datastore) -> None:
    # The registry wrapper receives the BUSINESS connection (per PostgresDriver
    # wiring) but must never write to it -- it reaches its own knowledge DSN
    # connection instead. Confirm no audit row lands on the business conn.
    import psycopg

    from hermes_runtime.knowledge.config import knowledge_database_url
    from toee_hermes.execute import execute_tool
    from toee_hermes.tool_gate import ToolExecutionContext

    try:
        psycopg.connect(knowledge_database_url(), connect_timeout=2).close()
    except Exception as exc:
        pytest.skip(f"Postgres unavailable at KNOWLEDGE_DATABASE_URL: {type(exc).__name__}: {exc}")

    driver, conn, _schema = datastore

    result = execute_tool(
        tool="toee_knowledge_ops",
        action="get_corpus_status",
        params={},
        context=ToolExecutionContext(profile="supervisor_admin", user_id="acct_admin"),
        driver=driver,
    )
    assert result.ok is True
    assert set(result.data) == {"doc_count", "chunk_count", "last_ingest_at", "by_type"}
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM workbench_audit_log")
        assert cur.fetchone()[0] == 0
