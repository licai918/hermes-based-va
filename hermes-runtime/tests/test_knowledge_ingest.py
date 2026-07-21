"""Tests for the Shopify-corpus ingestion job (FR-2, NFR-3, S07).

Static tests (chunking, boundary heuristics, CLI printing) always run. Live-DB
tests run against the docker-compose Postgres, isolated in a throwaway schema
via ``temp_knowledge_schema_conn`` (knowledge DB) and the real business DSN for
the policy-slot read path, and **skip** (not fail) when Postgres is
unreachable -- mirrors test_knowledge_migrate.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_runtime.knowledge.ingest import (
    check_boundaries,
    chunk_corpus,
    chunk_text,
    ingest,
    load_corpus,
    main,
)
from hermes_runtime.knowledge.migrate import run_migrations

# hermes-runtime/tests/test_knowledge_ingest.py -> repo-root/workspace/...
REAL_CORPUS_PATH = (
    Path(__file__).resolve().parents[2]
    / "workspace" / "0.0.3" / "knowledge-spike" / "probe" / "corpus.json"
)


def _fake_embed(texts):
    # Deterministic, no model load: proves the seam + the BYTEA round trip
    # without depending on fastembed being importable.
    return [f"vec:{text[:12]}".encode("utf-8") for text in texts]


# --- chunker (static) --------------------------------------------------


def test_chunk_text_splits_on_word_boundary_near_the_size_limit() -> None:
    text = "aaaa " * 200  # far longer than one chunk
    chunks = chunk_text(text, size=20)
    assert chunks  # produced something
    assert all(len(c) <= 20 or " " not in c for c in chunks)  # never splits mid-word
    assert " ".join(chunks) == " ".join(text.split())  # no words lost or reordered


def test_chunk_text_preserves_order() -> None:
    text = "one two three four five six seven eight nine ten"
    chunks = chunk_text(text, size=15)
    assert "".join(chunks).replace(" ", "") == "".join(text.split())
    # first chunk starts with "one", last ends with "ten"
    assert chunks[0].startswith("one")
    assert chunks[-1].endswith("ten")


def test_chunk_text_empty_or_whitespace_returns_no_chunks() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n\t  ") == []
    assert chunk_text(None) == []  # type: ignore[arg-type]


def test_chunk_corpus_flattens_docs_into_ordered_chunk_rows() -> None:
    docs = [
        {"page_id": "p1", "page_type": "page", "title": "P1", "url": "https://x/p1", "text": "hello world"},
        {"page_id": "p2", "page_type": "policy", "title": "P2", "url": None, "text": "a " * 400},
    ]
    rows = chunk_corpus(docs, size=600)
    assert rows[0] == {
        "page_id": "p1", "page_type": "page", "title": "P1", "url": "https://x/p1",
        "chunk_index": 0, "chunk_text": "hello world",
    }
    p2_rows = [r for r in rows if r["page_id"] == "p2"]
    assert len(p2_rows) > 1  # "a " * 400 is 800 chars, must split
    assert [r["chunk_index"] for r in p2_rows] == list(range(len(p2_rows)))  # ordered


def test_chunk_corpus_on_the_real_pull_artifact_matches_the_spike_count() -> None:
    # Regression on the operator pull-artifact contract: the spike proved
    # 27 docs -> 167 chunks (see knowledge_migrations/0001_knowledge_chunk.sql).
    docs = load_corpus(REAL_CORPUS_PATH)
    assert len(docs) == 27
    rows = chunk_corpus(docs)
    assert len(rows) == 167


# --- boundary check (static) --------------------------------------------


def test_boundary_check_excludes_policy_duplicate_from_index() -> None:
    slot_text = "We are open Monday to Friday, 9am to 5pm. Closed on statutory holidays."
    rows = [
        {"page_id": "p1", "page_type": "page", "title": "T", "url": None,
         "chunk_index": 0, "chunk_text": "We are open Monday to Friday, 9am to 5pm."},
        {"page_id": "p2", "page_type": "page", "title": "T2", "url": None,
         "chunk_index": 0, "chunk_text": "Tires are rotated every 10,000 km."},
    ]
    report, indexable = check_boundaries(rows, [slot_text])
    reasons = {(item["page_id"], item["reason"]) for item in report}
    assert ("p1", "policy_duplicate") in reasons
    assert [r["page_id"] for r in indexable] == ["p2"]  # duplicate excluded, other kept


def test_boundary_check_flags_price_and_stock_patterns_but_keeps_them_indexed() -> None:
    rows = [
        {"page_id": "p1", "page_type": "page", "title": "T", "url": None,
         "chunk_index": 0, "chunk_text": "Our all-season tires start at $89.99 each."},
        {"page_id": "p2", "page_type": "page", "title": "T2", "url": None,
         "chunk_index": 0, "chunk_text": "We currently have 12 in stock at this location."},
        {"page_id": "p3", "page_type": "page", "title": "T3", "url": None,
         "chunk_index": 0, "chunk_text": "Warranty covers workmanship and materials defects."},
    ]
    report, indexable = check_boundaries(rows, [])
    flagged_ids = {item["page_id"] for item in report}
    assert flagged_ids == {"p1", "p2"}
    assert {r["page_id"] for r in indexable} == {"p1", "p2", "p3"}  # nothing excluded


def test_boundary_check_handles_empty_slots_gracefully() -> None:
    rows = [{"page_id": "p1", "page_type": "page", "title": "T", "url": None,
             "chunk_index": 0, "chunk_text": "Nothing special here."}]
    report, indexable = check_boundaries(rows, [])
    assert report == []
    assert indexable == rows


# --- policy-slot read seam (static + live) ------------------------------


def test_read_policy_slot_texts_returns_empty_without_connecting_when_backend_is_mock(
    monkeypatch,
) -> None:
    import psycopg

    from hermes_runtime.knowledge.ingest import _read_policy_slot_texts

    monkeypatch.delenv("TOOL_BACKEND", raising=False)

    def _boom(*args, **kwargs):
        raise AssertionError("must not connect when TOOL_BACKEND is not datastore")

    monkeypatch.setattr(psycopg, "connect", _boom)
    assert _read_policy_slot_texts() == []


def test_read_policy_slot_texts_reads_published_text_from_the_business_db(monkeypatch) -> None:
    import psycopg

    from hermes_runtime.datastore.config import database_url
    from hermes_runtime.knowledge.ingest import _read_policy_slot_texts

    try:
        conn = psycopg.connect(database_url(), connect_timeout=2)
    except Exception as exc:
        pytest.skip(f"Postgres unavailable at DATABASE_URL: {type(exc).__name__}: {exc}")

    marker = "TEST-MARKER: business hours are 9 to 5, Mon-Fri."
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE workbench_policy_slot SET published_text = %s WHERE slot_id = 'business-hours'",
                (marker,),
            )
        conn.commit()

        monkeypatch.setenv("TOOL_BACKEND", "datastore")
        texts = _read_policy_slot_texts()
        assert marker in texts
    except psycopg.errors.UndefinedTable:
        pytest.skip("workbench_policy_slot not migrated on this Postgres")
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE workbench_policy_slot SET published_text = NULL WHERE slot_id = 'business-hours'"
            )
        conn.commit()
        conn.close()


# --- ingest pipeline (live DB) -------------------------------------------


def test_ingest_populates_chunks_with_round_tripped_embedding_bytes(
    temp_knowledge_schema_conn, tmp_path
) -> None:
    conn, _schema = temp_knowledge_schema_conn
    run_migrations(conn)

    docs = [
        {"page_id": "doc-a", "page_type": "page", "title": "A", "url": "https://x/a", "text": "hello world"},
        {"page_id": "doc-b", "page_type": "policy", "title": "B", "url": None, "text": "b " * 400},
    ]
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(docs), encoding="utf-8")

    result = ingest(corpus_path, embed_fn=_fake_embed, conn=conn, policy_slot_texts=[])

    expected_rows = chunk_corpus(docs)
    assert result["doc_count"] == 2
    assert result["chunk_count"] == len(expected_rows)
    assert result["flagged_count"] == 0

    with conn.cursor() as cur:
        cur.execute("SELECT chunk_text, embedding FROM knowledge_chunk ORDER BY id")
        rows = cur.fetchall()
    assert len(rows) == len(expected_rows)
    for chunk_text_value, embedding in rows:
        assert bytes(embedding) == _fake_embed([chunk_text_value])[0]


def test_ingest_is_idempotent_truncate_and_reload(temp_knowledge_schema_conn, tmp_path) -> None:
    conn, _schema = temp_knowledge_schema_conn
    run_migrations(conn)

    docs = [{"page_id": "doc-a", "page_type": "page", "title": "A", "url": None, "text": "hello world " * 5}]
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(docs), encoding="utf-8")

    result1 = ingest(corpus_path, embed_fn=_fake_embed, conn=conn, policy_slot_texts=[])
    result2 = ingest(corpus_path, embed_fn=_fake_embed, conn=conn, policy_slot_texts=[])

    assert result1["chunk_count"] == result2["chunk_count"] > 0
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM knowledge_chunk")
        assert cur.fetchone()[0] == result2["chunk_count"]


def test_ingest_excludes_policy_duplicates_but_still_indexes_live_fact_chunks(
    temp_knowledge_schema_conn, tmp_path
) -> None:
    conn, _schema = temp_knowledge_schema_conn
    run_migrations(conn)

    dup_text = "We are open Monday to Friday, 9am to 5pm."
    docs = [
        {"page_id": "doc-hours", "page_type": "page", "title": "Hours", "url": None, "text": dup_text},
        {"page_id": "doc-price", "page_type": "page", "title": "Price", "url": None,
         "text": "Our tires start at $59.99 and we have 8 in stock."},
    ]
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(docs), encoding="utf-8")

    slot_text = "We are open Monday to Friday, 9am to 5pm. Closed on statutory holidays."
    result = ingest(corpus_path, embed_fn=_fake_embed, conn=conn, policy_slot_texts=[slot_text])

    reasons = {item["reason"] for item in result["report"]}
    assert "policy_duplicate" in reasons
    assert "live_fact_pattern" in reasons

    with conn.cursor() as cur:
        cur.execute("SELECT page_id FROM knowledge_chunk")
        indexed_page_ids = {row[0] for row in cur.fetchall()}
    assert "doc-hours" not in indexed_page_ids  # excluded
    assert "doc-price" in indexed_page_ids  # flagged but still indexed


def test_ingest_with_the_real_local_embedder_loads_and_produces_384_dim_vectors(
    temp_knowledge_schema_conn, tmp_path
) -> None:
    # One live test exercises the real fastembed model (cached from the spike,
    # loads in well under a second -- see the S07 report).
    try:
        import fastembed  # noqa: F401
    except ImportError:
        pytest.skip("fastembed not installed")

    conn, _schema = temp_knowledge_schema_conn
    run_migrations(conn)

    docs = [{"page_id": "doc-a", "page_type": "page", "title": "A", "url": None, "text": "Toee Tire warranty covers workmanship defects."}]
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(docs), encoding="utf-8")

    result = ingest(corpus_path, conn=conn, policy_slot_texts=[])  # embed_fn=None -> real model
    assert result["chunk_count"] == 1

    with conn.cursor() as cur:
        cur.execute("SELECT embedding FROM knowledge_chunk")
        (embedding,) = cur.fetchone()
    assert len(bytes(embedding)) == 384 * 4  # float32 * 384 dims


# --- CLI (static) ---------------------------------------------------------


def test_cli_main_prints_counts_and_boundary_report(monkeypatch, capsys) -> None:
    import hermes_runtime.knowledge.ingest as ingest_module

    fake_result = {
        "doc_count": 2,
        "chunk_count": 3,
        "flagged_count": 1,
        "report": [
            {"page_id": "p1", "chunk_index": 0, "chunk_text": "flagged text", "reason": "live_fact_pattern"}
        ],
    }
    monkeypatch.setattr(ingest_module, "ingest", lambda path: fake_result)
    monkeypatch.setattr("sys.argv", ["ingest.py", "corpus.json"])

    main()

    out = capsys.readouterr().out
    assert "3 chunks" in out
    assert "2 docs" in out
    assert "live_fact_pattern" in out
    assert "p1" in out


def test_cli_main_requires_a_corpus_path_argument(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["ingest.py"])
    with pytest.raises(SystemExit):
        main()
