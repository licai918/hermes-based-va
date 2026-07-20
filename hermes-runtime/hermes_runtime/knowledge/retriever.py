"""Hybrid retrieval over the Toee Knowledge Store (FR-3, S08 -- PRD workspace/0.0.3/PRD.md).

Pure retrieval: no driver/tool wiring (S09), no gating/deadline (S09), no turn
integration (S10). Fuses two independent rankings over ``knowledge_chunk``:

- **Lexical**: Postgres full-text search, ``ts_rank`` over the generated
  ``tsv`` column. Uses the lexeme-OR trick the spike proved necessary
  (``workspace/0.0.3/knowledge-spike/probe/squal.py``): ``plainto_tsquery``
  ANDs every term together, so most multi-word questions match nothing;
  OR-ing the lexemes (match ANY term) lets ``ts_rank`` surface the
  best-covered chunk instead.
- **Semantic**: in-process cosine similarity between the query embedding and
  every chunk's embedding (loaded whole -- 167x384 floats is trivial at this
  corpus size, see ``knowledge_migrations/0001_knowledge_chunk.sql``'s BYTEA
  decision). Same BYTE CONTRACT as the S07 writer: float32, native byte
  order, ``np.frombuffer(blob, dtype=np.float32)``.

The two rankings are fused by **Reciprocal Rank Fusion** (RRF, k=60): each
ranking contributes ``1 / (k + rank)`` to a chunk's score; a chunk absent from
a ranking (e.g. no lexical match) simply contributes 0 from that ranking.

Embedding uses the model's asymmetric QUERY mode (``query_embed``, not
``passage_embed`` -- that's the S07 ingestion side), with the same
``AttributeError`` fallback the spike used
(``workspace/0.0.3/knowledge-spike/probe/squal_embed.py``) for fastembed
versions that only expose the generic ``embed``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

RRF_K = 60

# plainto_tsquery ANDs every term -> most multi-word questions match nothing.
# OR the lexemes (match ANY term) and let ts_rank surface the best-covered
# chunk -- proven in the spike (probe/squal.py's _TSQ trick).
_TSQ = "to_tsquery('english', replace(plainto_tsquery('english', %s)::text, '&', '|'))"
_FTS_SQL = (
    f"SELECT id FROM knowledge_chunk WHERE tsv @@ {_TSQ} ORDER BY ts_rank(tsv, {_TSQ}) DESC, id"
)
_ALL_SQL = "SELECT id, page_id, page_type, title, url, chunk_text, embedding FROM knowledge_chunk ORDER BY id"

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

EmbedQueryFn = Callable[[str], Any]  # returns an array-like of 384 floats


@dataclass(frozen=True)
class RetrievedChunk:
    page_id: str
    page_type: str
    title: str
    url: str | None
    chunk_text: str
    score: float  # fused RRF score
    fts_rank: int | None  # 1-based rank in the lexical ranking, None if no lexical match
    embed_rank: int | None  # 1-based rank in the semantic ranking, None if unembedded


def fastembed_query_embedder(model_name: str = "BAAI/bge-small-en-v1.5") -> EmbedQueryFn:
    """Build the default embedder: local fastembed QUERY embeddings.

    ``query_embed`` (not ``passage_embed``) -- bge's asymmetric convention;
    falls back to ``embed`` + a manual prefix for fastembed versions that
    don't expose ``query_embed`` (mirrors the spike's ``squal_embed.py``).
    """
    from fastembed import TextEmbedding

    model = TextEmbedding(model_name=model_name)

    def embed(query: str) -> np.ndarray:
        try:
            (vector,) = list(model.query_embed([query]))
        except AttributeError:
            (vector,) = list(model.embed([QUERY_PREFIX + query]))
        return np.asarray(vector, dtype=np.float32)

    return embed


# Process-level singleton for the DEFAULT query embedder (FR-7b cold-load
# fix). fastembed's TextEmbedding construction pays onnx session init
# (~800ms+) -- more than the entire KNOWLEDGE_RETRIEVAL_DEADLINE_MS budget
# (driver.py's default 800ms) -- so building a fresh instance on every
# retrieve() call structurally always misses the deadline. This caches the
# model HANDLE (infrastructure), not retrieval results -- S08's "no result
# caching" rule is a different axis (query -> answer) and stays untouched.
_query_embedder_lock = threading.Lock()
_query_embedder_singleton: EmbedQueryFn | None = None


def _singleton_query_embed(query: str) -> np.ndarray:
    """Default (non-injected) query embed path, backed by the process-level
    singleton. Construction AND every embed call are serialized under one
    lock: onnxruntime's ``InferenceSession.run`` is documented thread-safe,
    but fastembed's wrapper state around it isn't, and this is called from
    driver.py's per-request worker threads, so concurrent calls are possible.
    The lock is the safe default -- calls are short once the model is warm.
    """
    global _query_embedder_singleton
    with _query_embedder_lock:
        if _query_embedder_singleton is None:
            _query_embedder_singleton = fastembed_query_embedder()
        return _query_embedder_singleton(query)


def get_query_embedder() -> EmbedQueryFn:
    """Getter for the process-level singleton query embedder.

    Used both as ``retrieve()``'s default embed path and by
    ``warm_knowledge_embedder()`` (driver.py) to prime the SAME cache a
    warmed process's first real query will hit.
    """
    return _singleton_query_embed


def _rrf_fuse(rankings: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    """Reciprocal Rank Fusion over any number of ``[row_id, ...]`` rankings
    (best first). A row absent from a ranking contributes 0 from it."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for position, row_id in enumerate(ranking, start=1):
            scores[row_id] = scores.get(row_id, 0.0) + 1.0 / (k + position)
    return scores


def _cosine_ranking(ids: list[int], vectors: dict[int, bytes | None], query_vec: np.ndarray) -> list[int]:
    """Row ids with a non-null embedding, ranked by cosine similarity to
    ``query_vec`` (best first). Rows with no embedding are simply absent."""
    embedded_ids = [i for i in ids if vectors[i] is not None]
    if not embedded_ids:
        return []
    matrix = np.stack([np.frombuffer(bytes(vectors[i]), dtype=np.float32) for i in embedded_ids])
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    q_norm = np.linalg.norm(query_vec) or 1.0
    sims = (matrix / norms) @ (query_vec / q_norm)
    # np.argsort's default quicksort isn't stable -> cosine ties would resolve
    # in unspecified order (same latent nondeterminism as the FTS ts_rank
    # ties above). lexsort's primary key is the LAST arg: -sims (best first),
    # tiebreak ascending id, matching the FTS fix's tiebreak.
    order = np.lexsort((embedded_ids, -sims))
    return [embedded_ids[i] for i in order]


def retrieve(
    query: str,
    *,
    k: int = 3,
    conn: Any = None,
    embed_query_fn: EmbedQueryFn | None = None,
) -> list[RetrievedChunk]:
    """Hybrid FTS + embedding retrieval, fused by RRF, top-``k`` with provenance.

    Seams: ``conn`` (default: lazy-connect via ``knowledge_database_url()``);
    ``embed_query_fn`` (default: the process-level singleton query embedder,
    :func:`get_query_embedder` -- built only if actually needed, tests inject
    a fake and never import fastembed).
    Returns ``[]`` cleanly if ``knowledge_chunk`` is empty. Two SQL round
    trips: one SELECT for all rows + embeddings, one for the FTS ranking.

    # ponytail: no connection pooling (S29 does that); the embedder IS now
    # cached (get_query_embedder), see FR-7b/S10 cold-load fix above.
    """
    import psycopg

    from .config import knowledge_database_url

    owns_conn = conn is None
    if owns_conn:
        conn = psycopg.connect(knowledge_database_url())

    try:
        with conn.cursor() as cur:
            cur.execute(_ALL_SQL)
            all_rows = cur.fetchall()
            if not all_rows:
                return []

            cur.execute(_FTS_SQL, (query, query))
            fts_ranking = [row[0] for row in cur.fetchall()]
    finally:
        if owns_conn:
            conn.close()

    by_id = {row[0]: row for row in all_rows}  # id -> (id, page_id, page_type, title, url, chunk_text, embedding)
    vectors = {row_id: row[6] for row_id, row in by_id.items()}

    embed = embed_query_fn or get_query_embedder()
    query_vec = np.asarray(embed(query), dtype=np.float32)
    embed_ranking = _cosine_ranking(list(by_id.keys()), vectors, query_vec)

    fused = _rrf_fuse([fts_ranking, embed_ranking])
    fts_rank_of = {row_id: pos for pos, row_id in enumerate(fts_ranking, start=1)}
    embed_rank_of = {row_id: pos for pos, row_id in enumerate(embed_ranking, start=1)}

    top_ids = sorted(fused, key=lambda i: fused[i], reverse=True)[:k]
    results: list[RetrievedChunk] = []
    for row_id in top_ids:
        _, page_id, page_type, title, url, chunk_text, _embedding = by_id[row_id]
        results.append(
            RetrievedChunk(
                page_id=page_id,
                page_type=page_type,
                title=title,
                url=url,
                chunk_text=chunk_text,
                score=fused[row_id],
                fts_rank=fts_rank_of.get(row_id),
                embed_rank=embed_rank_of.get(row_id),
            )
        )
    return results
