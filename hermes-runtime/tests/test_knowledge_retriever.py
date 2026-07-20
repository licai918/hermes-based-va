"""Tests for the hybrid FTS + embedding retriever (FR-3, S08).

Pure-math tests (RRF fusion, cosine ranking) always run. Live-DB tests run
against the docker-compose Postgres, isolated in a throwaway schema via
``temp_knowledge_schema_conn`` (mirrors test_knowledge_ingest.py) -- **skip**
(not fail) when Postgres is unreachable.
"""

from __future__ import annotations

import numpy as np
import pytest

from hermes_runtime.knowledge.migrate import run_migrations
from hermes_runtime.knowledge.retriever import RetrievedChunk, _cosine_ranking, _rrf_fuse, retrieve


def _vec(*components: float) -> bytes:
    # Same byte contract as the S07 writer: float32, native byte order.
    return np.asarray(components, dtype=np.float32).tobytes()


# --- RRF fusion arithmetic (pure) ---------------------------------------


def test_rrf_fuse_pins_the_arithmetic_a_doc_1st_and_3rd_beats_4th_and_2nd() -> None:
    # doc_a: #1 lexical, #3 semantic. doc_b: #4 lexical, #2 semantic.
    fts_ranking = [1, 9, 9, 2]  # doc_a(id=1) rank 1, doc_b(id=2) rank 4
    embed_ranking = [9, 2, 1, 9]  # doc_b(id=2) rank 2, doc_a(id=1) rank 3
    scores = _rrf_fuse([fts_ranking, embed_ranking])

    expected_a = 1.0 / (60 + 1) + 1.0 / (60 + 3)
    expected_b = 1.0 / (60 + 4) + 1.0 / (60 + 2)
    assert scores[1] == pytest.approx(expected_a)
    assert scores[2] == pytest.approx(expected_b)
    assert scores[1] > scores[2]  # doc_a (1st+3rd) beats doc_b (4th+2nd)


def test_rrf_fuse_a_doc_absent_from_one_ranking_still_scores_from_the_other() -> None:
    fts_ranking = [1, 2]
    embed_ranking: list[int] = []  # doc never appears semantically (e.g. no embedding)
    scores = _rrf_fuse([fts_ranking, embed_ranking])
    assert scores == {1: pytest.approx(1.0 / 61), 2: pytest.approx(1.0 / 62)}


def test_rrf_fuse_empty_rankings_produce_no_scores() -> None:
    assert _rrf_fuse([[], []]) == {}


# --- cosine ranking (pure) ----------------------------------------------


def test_cosine_ranking_orders_by_similarity_best_first() -> None:
    ids = [1, 2, 3]
    vectors = {1: _vec(1, 0), 2: _vec(0.3, 0.95), 3: _vec(0, 1)}
    query = np.asarray([0, 1], dtype=np.float32)  # aligned with id 3, then 2, then 1
    assert _cosine_ranking(ids, vectors, query) == [3, 2, 1]


def test_cosine_ranking_skips_rows_with_no_embedding() -> None:
    ids = [1, 2]
    vectors = {1: _vec(1, 0), 2: None}
    query = np.asarray([1, 0], dtype=np.float32)
    assert _cosine_ranking(ids, vectors, query) == [1]


def test_cosine_ranking_all_null_returns_empty() -> None:
    assert _cosine_ranking([1, 2], {1: None, 2: None}, np.asarray([1.0], dtype=np.float32)) == []


# --- retrieve() (live DB) -------------------------------------------------


def _insert_chunk(conn, *, page_id, page_type, title, url, chunk_index, chunk_text, embedding):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO knowledge_chunk"
            " (page_id, page_type, title, url, chunk_index, chunk_text, embedding)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (page_id, page_type, title, url, chunk_index, chunk_text, embedding),
        )
        return cur.fetchone()[0]


def test_retrieve_returns_empty_list_cleanly_when_the_table_is_empty(temp_knowledge_schema_conn) -> None:
    conn, _schema = temp_knowledge_schema_conn
    run_migrations(conn)
    conn.commit()

    def _boom(_query):
        raise AssertionError("must not embed a query when the table is empty")

    assert retrieve("anything", conn=conn, embed_query_fn=_boom) == []


def test_retrieve_respects_k(temp_knowledge_schema_conn) -> None:
    conn, _schema = temp_knowledge_schema_conn
    run_migrations(conn)
    for i in range(5):
        _insert_chunk(
            conn, page_id=f"doc-{i}", page_type="page", title=f"T{i}", url=None,
            chunk_index=0, chunk_text=f"Tire warranty topic number {i}.", embedding=_vec(1.0, float(i)),
        )
    conn.commit()

    results = retrieve("tire warranty", k=2, conn=conn, embed_query_fn=lambda q: np.asarray([1.0, 0.0], dtype=np.float32))
    assert len(results) == 2
    assert all(isinstance(r, RetrievedChunk) for r in results)


def test_retrieve_populates_provenance_on_every_result(temp_knowledge_schema_conn) -> None:
    conn, _schema = temp_knowledge_schema_conn
    run_migrations(conn)
    _insert_chunk(
        conn, page_id="warranty-info", page_type="policy", title="Warranty Information",
        url="https://toeetire.example/warranty", chunk_index=0,
        chunk_text="Our warranty covers manufacturing defects for two years.",
        embedding=_vec(1.0, 0.0),
    )
    conn.commit()

    [result] = retrieve("warranty defects", k=3, conn=conn, embed_query_fn=lambda q: np.asarray([1.0, 0.0], dtype=np.float32))
    assert result.page_id == "warranty-info"
    assert result.page_type == "policy"
    assert result.title == "Warranty Information"
    assert result.url == "https://toeetire.example/warranty"
    assert "warranty" in result.chunk_text.lower()
    assert result.fts_rank == 1
    assert result.embed_rank == 1


def test_retrieve_byte_contract_round_trip_is_symmetric_with_the_s07_writer(temp_knowledge_schema_conn) -> None:
    # Write the way ingest.py's fastembed_passage_embedder does (astype float32
    # .tobytes()); retrieve must read it back with np.frombuffer(..., float32)
    # and rank a near-identical query vector first.
    conn, _schema = temp_knowledge_schema_conn
    run_migrations(conn)
    close_vec = np.asarray([0.1, 0.2, 0.3, 0.4], dtype=np.float32)
    far_vec = np.asarray([-0.4, -0.3, -0.2, -0.1], dtype=np.float32)
    _insert_chunk(
        conn, page_id="close", page_type="page", title="Close", url=None, chunk_index=0,
        chunk_text="Unrelated filler text about tire rotation schedules and service intervals.",
        embedding=close_vec.tobytes(),
    )
    _insert_chunk(
        conn, page_id="far", page_type="page", title="Far", url=None, chunk_index=0,
        chunk_text="More unrelated filler text about tire rotation schedules and service.",
        embedding=far_vec.tobytes(),
    )
    conn.commit()

    query_vec = np.asarray([0.11, 0.19, 0.29, 0.41], dtype=np.float32)  # near close_vec
    results = retrieve("rotation schedules", k=2, conn=conn, embed_query_fn=lambda q: query_vec)
    assert results[0].page_id == "close"
    assert results[0].embed_rank == 1


def test_retrieve_hybrid_fusion_end_to_end_against_disagreeing_signals(temp_knowledge_schema_conn) -> None:
    # doc_a matches BOTH query lexemes and is semantically decent (2nd);
    # doc_b matches only ONE lexeme; doc_c matches NO lexeme but is the best
    # semantic match. RRF should not let doc_c's semantic-only #1 win outright.
    conn, _schema = temp_knowledge_schema_conn
    run_migrations(conn)
    _insert_chunk(
        conn, page_id="tire-return", page_type="policy", title="Returns", url=None, chunk_index=0,
        chunk_text="Tire returns are accepted within 30 days for any reason.",
        embedding=_vec(1, 0),
    )
    _insert_chunk(
        conn, page_id="winter-tires", page_type="article", title="Winter", url=None, chunk_index=0,
        chunk_text="Winter tires help with snow and ice traction.",
        embedding=_vec(0.3, 0.95),
    )
    _insert_chunk(
        conn, page_id="warranty", page_type="policy", title="Warranty", url=None, chunk_index=0,
        chunk_text="Our warranty covers manufacturing defects for two years.",
        embedding=_vec(0, 1),
    )
    conn.commit()

    query_vec = np.asarray([0, 1], dtype=np.float32)  # aligns with "warranty" doc
    results = retrieve("tire return policy", k=3, conn=conn, embed_query_fn=lambda q: query_vec)

    by_page = {r.page_id: r for r in results}
    assert set(by_page) == {"tire-return", "winter-tires", "warranty"}
    assert by_page["tire-return"].fts_rank == 1  # best lexical match (both lexemes)
    assert by_page["warranty"].fts_rank is None  # no lexical match at all
    assert by_page["warranty"].embed_rank == 1  # best semantic match
    # RRF fusion: the doc strong on BOTH signals (tire-return) outranks the
    # semantic-only doc (warranty), proving hybrid isn't just embedding-alone.
    assert results[0].page_id == "tire-return"


def test_fts_ranking_orders_ts_rank_ties_by_ascending_id_deterministically(temp_knowledge_schema_conn) -> None:
    # Identical chunk_text -> identical generated tsv -> identical ts_rank for
    # every row (S-LAT's GIN index over `tv` has no title weighting to break
    # the tie). Without a secondary ORDER BY key, Postgres is free to return
    # tied rows in whatever order the query plan happens to produce -- the
    # latent reproducibility gap this test pins down (and the likely cause of
    # the 43%-vs-50% FTS eval discrepancy: tied-rank boundary flips).
    conn, _schema = temp_knowledge_schema_conn
    run_migrations(conn)
    ids = [
        _insert_chunk(
            conn, page_id=f"tie-{i}", page_type="policy", title=f"Tie {i}", url=None,
            chunk_index=0, chunk_text="Warranty warranty warranty coverage details.",
            embedding=_vec(1.0, 0.0),
        )
        for i in range(6)
    ]
    conn.commit()
    assert ids == sorted(ids)  # sanity: BIGSERIAL assigns ascending ids in insert order

    from hermes_runtime.knowledge.retriever import _FTS_SQL

    # Behavioral assertion isn't reliably RED pre-fix: a freshly-inserted,
    # never-updated small table happens to return GIN-index ties in physical
    # (= insertion = ascending id) order on this Postgres/plan, so it passes
    # even without a secondary ORDER BY key -- exactly the "can flip between
    # query plans" fragility the finding warns about. Assert the ORDER BY
    # contract directly so this test actually fails without the fix.
    assert _FTS_SQL.rstrip().lower().endswith("desc, id"), _FTS_SQL

    def _fts_order() -> list[int]:
        with conn.cursor() as cur:
            cur.execute(_FTS_SQL, ("warranty", "warranty"))
            return [row[0] for row in cur.fetchall()]

    orders = [_fts_order() for _ in range(5)]
    assert all(order == ids for order in orders), orders


def test_retrieve_against_the_real_local_embedder_if_installed(temp_knowledge_schema_conn) -> None:
    try:
        import fastembed  # noqa: F401
    except ImportError:
        pytest.skip("fastembed not installed")

    conn, _schema = temp_knowledge_schema_conn
    run_migrations(conn)
    from hermes_runtime.knowledge.ingest import fastembed_passage_embedder

    passage_embed = fastembed_passage_embedder()
    text = "Toee Tire warranty covers workmanship defects for two years."
    (embedding,) = passage_embed([text])
    _insert_chunk(
        conn, page_id="doc-a", page_type="page", title="A", url=None, chunk_index=0,
        chunk_text=text, embedding=embedding,
    )
    conn.commit()

    results = retrieve("what does the warranty cover", k=3, conn=conn)  # embed_query_fn=None -> real model
    assert len(results) == 1
    assert results[0].page_id == "doc-a"
