"""L7 hit accounting + the live-Postgres vocabulary (0.0.5 S05, FR-5 / D6).

The Postgres half of :mod:`toee_hermes.lexicon_seam`. Three jobs, one small
module, because they are the same fact seen from three sides:

* **read** -- ``lexicon_version`` (S02's ``MAX(updated_at)``) and the confirmed
  entries, wired into a :class:`~toee_hermes.lexicon_seam.LexiconVocabulary` so
  the process cache reloads on a governed decision and on nothing else;
* **write** -- one append-only ``lexicon_hit_event`` per applied entry,
  fire-and-forget, taking no lock any turn is waiting on;
* **rollup** -- the scheduled job that folds those events into
  ``semantic_lexicon.hit_count`` and deletes them, in one transaction.

**The rollup must never stamp ``updated_at``, and the UPDATE below deliberately
does not.** The admin console derives its "(edited …)" marker from
``updated_at > coalesce(decided_at, created_at)``, and the process cache keys on
``MAX(updated_at)``. Both rest on one unwritten invariant: **only a content write
moves that column.** A rollup that "helpfully" refreshed it would put a permanent
false "an admin edited this" badge on every hot entry, beside a decider who
edited nothing, and would invalidate the caches this slice and S06 build on every
hit -- a cache and its own defeat. If a freshness stamp is ever wanted here, add a
column; do not borrow that one.
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Iterator, Mapping, Optional, Sequence

from toee_hermes.lexicon_seam import LexiconVocabulary, install_lexicon_vocabulary
from toee_hermes.plugin.profiles import INTERNAL

logger = logging.getLogger(__name__)

# The rollup's "last run" record, on the same surface the retention sweep and the
# injection-ledger prune use (a `workbench_audit_log` row) -- no state table for
# two numbers.
ROLLUP_AUDIT_ACTION = "lexicon_hit_rollup"

# The vocabulary's own read. Only `confirmed` rows leave this query: the seam
# filters again on status (belt and braces -- a reader that forgets is the
# difference between "not approved yet" and "approved"), but the store must not
# hand out a proposal in the first place.
_CONFIRMED_SQL = (
    "SELECT id, domain, entry_kind, surface_form, canonical_form, status "
    "FROM semantic_lexicon WHERE status = 'confirmed'"
)
_CONFIRMED_COLUMNS = (
    "id",
    "domain",
    "entry_kind",
    "surface_form",
    "canonical_form",
    "status",
)

# S02's `lexicon_version`, consumed rather than reinvented (see
# drivers/mock/semantic_lexicon._lexicon_version for why it is table-wide).
_VERSION_SQL = "SELECT max(updated_at) FROM semantic_lexicon"


def lexicon_version(cur) -> Optional[str]:
    """``MAX(updated_at)`` as a comparable string, on a caller-owned cursor."""
    cur.execute(_VERSION_SQL)
    row = cur.fetchone()
    return row[0].isoformat() if row and row[0] is not None else None


def confirmed_lexicon_entries(cur) -> list[dict[str, Any]]:
    """Every confirmed L7 row, on a caller-owned cursor."""
    cur.execute(_CONFIRMED_SQL)
    return [dict(zip(_CONFIRMED_COLUMNS, row)) for row in cur.fetchall()]


def record_lexicon_hits(cur, entry_ids: Sequence[str]) -> None:
    """Append one hit event per applied entry, on a caller-owned cursor.

    APPEND-ONLY (D6). Never an UPDATE of ``semantic_lexicon`` -- see the module
    docstring and migration 0026 for why the counter is not written here.
    """
    rows = [(f"lexhit_{uuid.uuid4().hex}", entry_id) for entry_id in entry_ids]
    if not rows:
        return
    cur.executemany(
        "INSERT INTO lexicon_hit_event (id, entry_id) VALUES (%s, %s)", rows
    )


def roll_up_lexicon_hits(conn) -> tuple[int, int]:
    """Fold pending hit events into ``hit_count``. Returns ``(consumed, updated)``.

    One statement, one transaction: the DELETE and the counter UPDATE cannot
    separate, so a crash either applies both or neither and a retry double-counts
    nothing. No watermark table is needed for the same reason.

    Events naming an entry that no longer exists are consumed and applied to
    nothing -- ``consumed`` counts them, ``updated`` does not.

    **No ``updated_at = now()``.** That omission is the point; see the module
    docstring. It is pinned by ``test_the_rollup_does_not_move_updated_at``.
    No commit -- the caller owns the transaction (the prune job's discipline).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH consumed AS (
                DELETE FROM lexicon_hit_event RETURNING entry_id
            ), totals AS (
                SELECT entry_id, count(*)::int AS hits FROM consumed GROUP BY entry_id
            ), applied AS (
                UPDATE semantic_lexicon AS l
                   SET hit_count = l.hit_count + t.hits
                  FROM totals AS t
                 WHERE l.id = t.entry_id
             RETURNING t.hits
            )
            SELECT
                (SELECT coalesce(sum(hits), 0)::int FROM totals),
                (SELECT count(*)::int FROM applied)
            """
        )
        consumed, updated = cur.fetchone()
    return int(consumed), int(updated)


def run_lexicon_hit_rollup_job(
    payload: Mapping[str, Any], *, conn: Optional[Any] = None
) -> None:
    """The ``lexicon_hit_rollup`` job body: materialize ``hit_count``, record the run.

    ``conn`` is injectable for tests (an isolated-schema connection); production
    takes a pooled connection, matching ``honored_rate`` and the ledger prune. A
    failure propagates so the job retries then dead-letters -- nobody is waiting
    on it, and a silently-skipped rollup is a counter that quietly stops moving
    while two later slices read it as usage.
    """
    del payload  # scheduled job; the (schedule_window, window_start) payload is unused.
    if conn is not None:
        _roll_up_and_audit(conn)
        return
    from .datastore.config import database_url
    from .datastore.pool import get_database_pool

    with get_database_pool(database_url()).connection() as pooled:
        _roll_up_and_audit(pooled)


def _roll_up_and_audit(conn) -> None:
    from .datastore.handlers._common import insert_audit

    consumed, updated = roll_up_lexicon_hits(conn)
    insert_audit(
        conn,
        # Unattended, exactly like the retention sweep and the ledger prune.
        profile=INTERNAL,
        account_id=None,
        action=ROLLUP_AUDIT_ACTION,
        target_type="semantic_lexicon",
        target_id=None,
        details={
            "consumed": consumed,
            "entries_updated": updated,
            "run_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    conn.commit()
    logger.info(
        "lexicon hit rollup: %s event(s) folded into %s entry hit_count(s)",
        consumed,
        updated,
    )


# --- the process vocabulary ---------------------------------------------------


@contextlib.contextmanager
def _connection(conn: Optional[Any]) -> Iterator[Any]:
    """The caller's connection, or a pooled one it owns for the call."""
    if conn is not None:
        yield conn
        return
    from .datastore.config import database_url
    from .datastore.pool import get_database_pool

    with get_database_pool(database_url()).connection() as pooled:
        yield pooled


def postgres_lexicon_vocabulary(*, conn: Optional[Any] = None) -> LexiconVocabulary:
    """The live-Postgres L7 vocabulary the two product-read twins consult.

    ``conn`` is a test seam (an isolated-schema connection). Production passes
    nothing and each call takes a pooled connection -- the same pool the driver's
    own query on that request uses. Every failure is already swallowed by
    :class:`~toee_hermes.lexicon_seam.LexiconVocabulary`, which serves its last
    good vocabulary (nothing, on a cold process) rather than raising into a turn.
    """
    owns = conn is None

    def _version() -> Optional[str]:
        with _connection(conn) as active:
            with active.cursor() as cur:
                return lexicon_version(cur)

    def _confirmed() -> list[dict[str, Any]]:
        with _connection(conn) as active:
            with active.cursor() as cur:
                return confirmed_lexicon_entries(cur)

    def _hits(entry_ids: Sequence[str]) -> None:
        with _connection(conn) as active:
            with active.cursor() as cur:
                record_lexicon_hits(cur, entry_ids)
            active.commit()

    del owns  # the pool's context manager owns the connection either way
    return LexiconVocabulary(version=_version, confirmed=_confirmed, record_hits=_hits)


def install_postgres_lexicon_vocabulary() -> None:
    """Composition-root hook: point the product-read seams at Postgres.

    Called from the two composition roots beside ``warm_knowledge_embedder``, so
    a deployment wires L7 ONCE and both driver twins (the mock handlers and the
    live ComposioDriver) read the same store -- the NFR-7 requirement, satisfied
    structurally rather than by remembering to pass an argument in two places.

    Gated on :func:`~hermes_runtime.tool_backend.memory_enabled` -- the same
    ``TOOL_BACKEND=datastore`` axis every other governed store rides. On a
    mock/unset deployment nothing is installed, the seam is a no-op, and no turn
    ever attempts a lexicon connection. The eval record/replay path installs
    nothing either, so it stays byte-identical (NFR-4).
    """
    from .tool_backend import memory_enabled

    if not memory_enabled():
        return
    install_lexicon_vocabulary(postgres_lexicon_vocabulary())
    logger.info(
        "L7 semantic lexicon wired into the product-read seam (confirmed entries "
        "only; cache keyed on lexicon_version)"
    )
