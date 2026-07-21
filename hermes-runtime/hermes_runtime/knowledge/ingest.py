"""Corpus -> chunk -> embed -> index ingestion for the Toee Knowledge Store
(FR-2, NFR-3, S07 -- PRD workspace/0.0.3/PRD.md).

**Two-stage ingestion.** This module is Stage B only.

Stage A (pull -- an OPERATOR step, not code in this module): an operator runs
the Shopify connector (read-only; products/orders/PII excluded) and writes a
pull artifact -- a JSON file of ``[{page_id, page_type, title, url, text}]``
objects, one per page/blog-article/shop-policy, HTML already reduced to plain
text. ``page_type`` is one of ``page`` | ``article`` | ``policy``. The pull
artifact format IS the contract between the two stages; the real reference
artifact is ``workspace/0.0.3/knowledge-spike/probe/corpus.json`` (27 real
Toee Tire docs). Nothing in this module talks to Shopify.

Stage B (this module): given a pull-artifact path, chunk each doc's text
(~600-char word-boundary chunks, same algorithm as the spike's
``probe/ingest.py`` -- proven at 27 docs -> 167 chunks), run a boundary check
(NFR-3 / audit finding 3, see :func:`check_boundaries`), embed the chunks that
pass, and load them into ``knowledge_chunk`` in the separate ``toee_knowledge``
database (idempotent: TRUNCATE + reload, scoped to the knowledge DB connection
only -- the business database is never touched here).

Embedding: fastembed's ``BAAI/bge-small-en-v1.5`` (384-dim), using
``passage_embed`` -- bge's asymmetric convention where corpus passages and
search queries get different treatment; the query side (``query_embed``) is
S08's retrieval concern, not this ingestion job's. Vectors are serialized as
raw **float32, native byte order** (little-endian on every real deployment
target) via ``numpy.ndarray.astype(np.float32).tobytes()``; the inverse read
is ``np.frombuffer(blob, dtype=np.float32)``. The embedder is an injected seam
(``embed_fn``) so tests can supply a deterministic fake instead of loading the
real model.

CLI::

    python -m hermes_runtime.knowledge.ingest <corpus.json>

Runs ``ensure_database`` + ``migrate`` first (idempotent), so a fresh machine
ingests in one command.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

CHUNK_SIZE = 600  # ~chars per chunk, word-boundary -- matches probe/ingest.py

EmbedFn = Callable[[Sequence[str]], list[bytes]]

# --- boundary-check heuristics (NFR-3 / audit finding 3) -------------------
# Simple regex patterns, not ML: a $-amount or "CAD N" (price-like), or an
# "N in stock" / "N units available/left" phrase (stock-count-like). Either
# marks a chunk as embedding a live fact -- flagged for human review but still
# indexed (only a verbatim policy-slot duplicate is excluded).
_PRICE_RE = re.compile(r"\$\s?\d+(?:\.\d{2})?|\bCAD\$?\s?\d+(?:\.\d{2})?\b", re.IGNORECASE)
_STOCK_RE = re.compile(
    r"\b\d+\s+(?:in stock|units?\s+(?:in stock|available|left)|left in stock)\b",
    re.IGNORECASE,
)


def chunk_text(text: str, size: int = CHUNK_SIZE) -> list[str]:
    """Split ``text`` into ~``size``-char, word-boundary chunks, in order.

    Identical algorithm to the spike's ``probe/ingest.py`` ``chunks()`` --
    proven on the real 27-doc corpus (167 chunks). Empty/whitespace-only (or
    ``None``) text returns ``[]``.
    """
    out: list[str] = []
    cur = ""
    for word in (text or "").split():
        if cur and len(cur) + 1 + len(word) > size:
            out.append(cur)
            cur = word
        else:
            cur = (cur + " " + word).strip()
    if cur:
        out.append(cur)
    return out


def load_corpus(path: str | Path) -> list[dict[str, Any]]:
    """Read the operator-produced pull artifact (Stage A's output)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def chunk_corpus(docs: list[dict[str, Any]], size: int = CHUNK_SIZE) -> list[dict[str, Any]]:
    """Flatten pull-artifact docs into ordered ``knowledge_chunk`` row dicts."""
    rows: list[dict[str, Any]] = []
    for doc in docs:
        for index, text in enumerate(chunk_text(doc.get("text", ""), size)):
            if text.strip():
                rows.append(
                    {
                        "page_id": doc["page_id"],
                        "page_type": doc["page_type"],
                        "title": doc["title"],
                        "url": doc.get("url"),
                        "chunk_index": index,
                        "chunk_text": text,
                    }
                )
    return rows


def check_boundaries(
    rows: list[dict[str, Any]], policy_slot_texts: Sequence[str] = ()
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Flag boundary-violating chunks (audit finding 3 / NFR-3).

    Returns ``(report, indexable_rows)``:

    - ``report``: every flagged chunk (row dict + ``"reason"``), one of
      ``"policy_duplicate"`` (the chunk verbatim-duplicates a governed
      operational-policy slot's published text) or ``"live_fact_pattern"``
      (a price- or stock-count-like phrase).
    - ``indexable_rows``: ``rows`` minus the ``policy_duplicate`` ones --
      those alone are excluded from indexing; ``live_fact_pattern`` chunks are
      reported for human review but still indexed.

    ``policy_slot_texts`` may be empty (slots unauthored yet, or
    ``TOOL_BACKEND`` isn't ``datastore``) -- handled gracefully: nothing can
    match, so no chunk is ever flagged ``policy_duplicate``.
    """
    # ponytail: naive substring containment, no normalization/fuzzy match --
    # fine while slots are empty/short-paragraph governed text (today: empty).
    # Upgrade to normalized (casefold/whitespace-collapsed) or fuzzy comparison
    # if a short published slot ever produces false-positive containment hits
    # against unrelated long chunks.
    normalized_slots = [slot.strip() for slot in policy_slot_texts if slot and slot.strip()]

    report: list[dict[str, Any]] = []
    indexable: list[dict[str, Any]] = []
    for row in rows:
        stripped = row["chunk_text"].strip()
        is_policy_duplicate = bool(stripped) and any(
            stripped in slot or slot in stripped for slot in normalized_slots
        )
        if is_policy_duplicate:
            report.append({**row, "reason": "policy_duplicate"})
            continue  # excluded from indexable_rows

        matches = _PRICE_RE.findall(row["chunk_text"]) + _STOCK_RE.findall(row["chunk_text"])
        if matches:
            report.append({**row, "reason": "live_fact_pattern", "matches": matches})
        indexable.append(row)
    return report, indexable


def _read_policy_slot_texts() -> list[str]:
    """Non-empty published Required Operational Policy Slot texts, or ``[]``.

    The slots live in ``workbench_policy_slot`` in the BUSINESS datastore
    (``toee_va``), a separate database from the knowledge store (S-ISO) --
    read directly here rather than through the tool-dispatch surface, since
    this is an offline ingestion job, not a turn. Only reads when
    ``TOOL_BACKEND=datastore`` (mirrors ``tool_backend.memory_enabled()``'s
    gating pattern); returns ``[]`` on a mock/unset backend, an unreachable
    Postgres, or a not-yet-migrated table -- the boundary check must never
    block ingestion.
    """
    from hermes_runtime.tool_backend import resolve_tool_backend

    if resolve_tool_backend() != "datastore":
        return []
    try:
        import psycopg

        from hermes_runtime.datastore.config import database_url

        with psycopg.connect(database_url(), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT published_text FROM workbench_policy_slot"
                    " WHERE published_text IS NOT NULL AND length(published_text) > 0"
                )
                return [row[0] for row in cur.fetchall()]
    except Exception:
        return []


def fastembed_passage_embedder(model_name: str = "BAAI/bge-small-en-v1.5") -> EmbedFn:
    """Build the default embedder: local fastembed passage embeddings.

    ``passage_embed`` (not ``query_embed``) -- chunks are corpus passages,
    bge's asymmetric convention. Serializes each vector as float32, native
    byte order (see module docstring for the exact inverse read).
    """
    import numpy as np
    from fastembed import TextEmbedding

    model = TextEmbedding(model_name=model_name)

    def embed(texts: Sequence[str]) -> list[bytes]:
        return [np.asarray(vector, dtype=np.float32).tobytes() for vector in model.passage_embed(list(texts))]

    return embed


def ingest(
    corpus_path: str | Path,
    *,
    embed_fn: EmbedFn | None = None,
    conn: Any = None,
    dsn: str | None = None,
    policy_slot_texts: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Run the full pull-artifact -> chunk -> boundary-check -> embed -> index
    pipeline once.

    Idempotent: TRUNCATEs ``knowledge_chunk`` (on ``conn``/the knowledge DSN
    only -- never the business database) before reloading, so re-running
    produces the identical corpus (FR-2).

    Seams for testing: ``embed_fn`` (default: the real fastembed model, built
    lazily so tests that supply a fake never import it); ``conn`` (default:
    open a fresh connection, self-provisioning via ``migrate`` -- tests pass a
    throwaway-schema connection instead); ``policy_slot_texts`` (default:
    read live from the business datastore -- tests pass a fixed list).

    Returns ``{"doc_count", "chunk_count", "flagged_count", "report"}``, where
    ``chunk_count`` is the number of rows actually indexed (excludes
    ``policy_duplicate`` chunks) and ``report`` is the full boundary-check
    report (printable; see :func:`check_boundaries`).
    """
    docs = load_corpus(corpus_path)
    rows = chunk_corpus(docs)

    slots = policy_slot_texts if policy_slot_texts is not None else _read_policy_slot_texts()
    report, indexable_rows = check_boundaries(rows, slots)

    vectors: list[bytes] = []
    if indexable_rows:
        active_embed_fn = embed_fn or fastembed_passage_embedder()
        vectors = active_embed_fn([row["chunk_text"] for row in indexable_rows])

    import psycopg

    from .config import knowledge_database_url
    from .migrate import migrate as migrate_knowledge_db

    owns_conn = conn is None
    if owns_conn:
        target_dsn = dsn or knowledge_database_url()
        migrate_knowledge_db(target_dsn)  # ensure_database + apply migrations, idempotent
        conn = psycopg.connect(target_dsn)

    try:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE knowledge_chunk RESTART IDENTITY")
            cur.executemany(
                "INSERT INTO knowledge_chunk"
                " (page_id, page_type, title, url, chunk_index, chunk_text, embedding)"
                " VALUES (%(page_id)s, %(page_type)s, %(title)s, %(url)s,"
                " %(chunk_index)s, %(chunk_text)s, %(embedding)s)",
                [{**row, "embedding": vector} for row, vector in zip(indexable_rows, vectors)],
            )
        conn.commit()
    finally:
        if owns_conn:
            conn.close()

    return {
        "doc_count": len(docs),
        "chunk_count": len(indexable_rows),
        "flagged_count": len(report),
        "report": report,
    }


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python -m hermes_runtime.knowledge.ingest <corpus.json>")
    result = ingest(sys.argv[1])
    print(f"ingested {result['chunk_count']} chunks from {result['doc_count']} docs")
    if result["report"]:
        print(f"boundary report: {result['flagged_count']} flagged")
        for item in result["report"]:
            print(f"  [{item['reason']}] {item['page_id']}#{item['chunk_index']}: {item['chunk_text'][:80]!r}")
    else:
        print("boundary report: clean (0 flagged)")


if __name__ == "__main__":
    main()
