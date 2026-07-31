"""The Postgres half of S13's write-time advisories (0.0.5 S13, FR-18).

The DECISION lives in :mod:`toee_hermes.write_advisories` -- pure, store-less,
and shared by both twins (NFR-7). This module is only the read: it fetches the
candidate rows a Postgres-backed propose can compare against and hands them over.
Same split as ``blast_radius`` / ``lexicon_hits``, and the same reason: the
comparison rules must not be able to differ between the mock and the database.

**The two queries below are the whole cross-layer surface, and they name exactly
two tables.** ``semantic_lexicon`` (L7) and ``agent_experience`` (L6) are the two
SHARED, operational-only layers. ``customer_memory_slot`` (L4) is deliberately
absent: it is per-customer PII by design, and an advisory that told an admin
reading a shared-layer proposal "this resembles something in a customer's
memory" would have moved that customer's data across the boundary NFR-6 exists
to hold. ``test_the_candidate_queries_never_reach_outside_the_shared_layers``
pins it, so adding a join here fails a test rather than passing review.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

# ponytail: no WHERE and no LIMIT -- the confirmed filter lives in the shared
# resolver (one place, and a test can pin it), and both tables are small by
# construction: L7 is an admin-curated vocabulary and L6 is short operational
# notes. Push a `WHERE status = 'confirmed'` down the day either table outgrows a
# few thousand rows; the resolver's own filter makes that a pure optimization.
_L7_CANDIDATE_SQL = "SELECT id, domain, surface_form, status FROM semantic_lexicon"
_L6_CANDIDATE_SQL = "SELECT id, content, status FROM agent_experience"

CANDIDATE_SQL: tuple[str, ...] = (_L7_CANDIDATE_SQL, _L6_CANDIDATE_SQL)


def candidate_rows(conn) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(lexicon rows, experience rows)`` -- the only rows an advisory sees."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_L7_CANDIDATE_SQL)
        lexicon = cur.fetchall()
        cur.execute(_L6_CANDIDATE_SQL)
        experience = cur.fetchall()
    return lexicon, experience


def annotations_for(
    conn,
    build: Callable[[list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]],
) -> dict[str, Any]:
    """``build(lexicon_rows, experience_rows)``, or ``{}`` if anything goes wrong.

    NFR-3 is the reason for the swallow: an advisory INFORMS the human writing,
    so it must never be able to fail the write it is describing. A proposal that
    could not be annotated is a proposal, not an error.

    ponytail: a plain ``try``, not a SAVEPOINT. The failures this actually
    catches are Python-level -- a malformed row reaching the comparison -- and
    those leave the caller's transaction healthy. A SQL-level failure would
    poison it, but every SQL-level failure reachable here (table missing, column
    missing, connection dead) also dooms the INSERT that follows, so a savepoint
    would buy nothing but its own footgun: ``conn.transaction()`` COMMITS rather
    than releasing when it is the outermost block, and this read is often the
    first statement of the request. Wrap it the day a statement timeout on these
    two SELECTs is actually observed.
    """
    try:
        return build(*candidate_rows(conn))
    except Exception as exc:  # noqa: BLE001 - advisory: never fail the propose
        logger.warning(
            "Write-time advisories skipped (error_type=%s); the proposal is "
            "stored unannotated",
            type(exc).__name__,
        )
        return {}


__all__ = ["CANDIDATE_SQL", "annotations_for", "candidate_rows"]
