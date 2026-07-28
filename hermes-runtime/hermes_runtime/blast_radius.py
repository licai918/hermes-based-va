"""Blast radius: the ledger join, the decide-path hook, and D21's re-scan (S10, FR-12).

The Postgres half of :mod:`toee_hermes.blast_radius`, which owns the vocabulary
and the answer's shape. It lives beside ``injection_ledger`` and
``entry_effectiveness`` because all three are queries over S09's ledger, not
handlers -- ``handlers/review_item.py`` calls :func:`affected_cases` for the
admin read, and ``handlers/semantic_lexicon.py`` / ``handlers/memory.py`` call
:func:`record_blast_radius` on their decide paths.

**Two joins, because the ledger has two kinds of row (D4).** The external turn
writes ``turn_ref = event_id`` and ``case_or_binding_ref = binding_key``; the
copilot draft writes a synthetic ``turn_ref`` and ``case_or_binding_ref =
case_id``. So the copilot row IS the case, and the external row reaches its case
through ``agent_turn_context`` -> the turn's SMS session. Exactly one branch can
resolve for any given row (a ``copilot_turn_*`` ref is never an ``event_id``, a
binding key is never a ``case_*`` id), so ``COALESCE`` is a join, not a guess.

**Grouped by case, never by ``case_or_binding_ref``.** Two independent reasons,
both from D4 and both real:

* A draft turn has no durable identity, so its ``turn_ref`` never repeats and the
  ledger's composite primary key cannot dedupe a re-drafted case. Without the
  GROUP BY, one case that was drafted three times reads as three affected cases.
* ``case_or_binding_ref`` is deliberately NOT re-pointed when a provisional
  binding is verified -- that turn genuinely happened under the provisional key
  and rewriting it would falsify history. Grouping on it would therefore split
  ONE customer into two, and the "N open cases touched" count would be wrong in
  the direction that matters. Grouping on the CASE is immune: both turns resolve
  to the same case rows regardless of which key they were recorded under.

**The window is a filter, not a default.** ``since`` narrows to injections at or
after a timestamp -- FR-12's "which turns did it touch *since I changed it*".
Omitted, the answer covers the whole retained ledger
(``injection_ledger.PRUNE_WINDOW_SECONDS``).

**Nothing here writes to a case (NFR-3).** Cases are read for their status and
never touched; the only write is a propose-only ``review_item`` through the
store's own governed action.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

from psycopg.rows import dict_row

from toee_hermes.blast_radius import (
    BLAST_RADIUS_KIND,
    REASON_UNSCANNED_INJECTION,
    blast_radius_evidence,
    blast_radius_result,
    blast_radius_subject_ref,
    unscanned_subject_ref,
)
from toee_hermes.drivers.mock.memory import scan_memory_write
from toee_hermes.errors import ToolDriverError

from .injection_ledger import LAYER_L4

logger = logging.getLogger(__name__)

# One row per (turn, layer, entry) in; one row per CASE out. `turn_count` is the
# ledger rows that resolved to this case, so a case drafted twice reads as two
# turns and one case -- which is what actually happened.
_AFFECTED_CASES_SQL = """
WITH touched AS (
    SELECT
        l.injected_at,
        COALESCE(copilot.id, external.id) AS case_id
    FROM injection_ledger l
    -- Copilot draft turn: case_or_binding_ref IS the case id.
    LEFT JOIN cases copilot ON copilot.id = l.case_or_binding_ref
    -- External turn: turn_ref is the durable event id (ADR-0107); its case is
    -- the one that was current on that turn's SMS session. Picking the LATEST
    -- case opened at or before the injection -- rather than every case that
    -- ever shared the session -- is what stops one turn from being attributed
    -- to a case that was already resolved when it happened.
    LEFT JOIN agent_turn_context atc ON atc.event_id = l.turn_ref
    LEFT JOIN LATERAL (
        SELECT c2.id
        FROM cases c2
        WHERE c2.sms_session_id = atc.sms_session_id
          AND c2.opened_at <= l.injected_at
        ORDER BY c2.opened_at DESC
        LIMIT 1
    ) external ON TRUE
    WHERE l.layer = %(layer)s
      AND l.entry_ref = %(entry_ref)s
      AND (%(since)s::timestamptz IS NULL OR l.injected_at >= %(since)s)
)
SELECT c.id, c.status, c.channel, c.contact_reason, c.summary,
       c.opened_at, c.last_activity_at, c.resolved_at,
       count(*) AS turn_count,
       max(t.injected_at) AS last_injected_at
FROM touched t
JOIN cases c ON c.id = t.case_id
GROUP BY c.id, c.status, c.channel, c.contact_reason, c.summary,
         c.opened_at, c.last_activity_at, c.resolved_at
ORDER BY max(t.injected_at) DESC, c.id
"""


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def affected_cases(conn, *, layer: str, entry_ref: str, since=None) -> list[dict[str, Any]]:
    """Every CASE this entry's injections reached, newest first, one row each.

    Read-only, and scoped by all three coordinates: an entry under a different
    layer, a different entry on the same case, and an injection before ``since``
    are each excluded by their own predicate rather than by luck.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            _AFFECTED_CASES_SQL,
            {"layer": layer, "entry_ref": entry_ref, "since": since},
        )
        rows = cur.fetchall()
    return [
        {
            **row,
            "opened_at": _iso(row["opened_at"]),
            "last_activity_at": _iso(row["last_activity_at"]),
            "resolved_at": _iso(row["resolved_at"]),
            "last_injected_at": _iso(row["last_injected_at"]),
        }
        for row in rows
    ]


def measure_and_emit(
    conn,
    context,
    *,
    layer: str,
    entry_ref: str,
    reason: str,
    subject_ref: str,
    since=None,
    emit_when_no_open_cases: bool,
) -> Optional[dict[str, Any]]:
    """Measure the blast radius and PROPOSE a review item. Returns the item, or ``None``.

    Emits through ``propose_review_item`` -- the store's own governed action,
    reached through its registry fragment exactly as S25's aggregator does --
    never a raw INSERT, so the emission gets the store's gate, its write scan and
    its open-set idempotence for free (NFR-3: propose-only, nothing decided).

    ``emit_when_no_open_cases`` is the one real difference between this module's
    two callers, so it is a parameter rather than a convention. A decide path
    raising "0 open cases touched by retired entry X -- review?" is noise, and
    the sweeps that would produce it run on every admin edit. D21's re-scan is
    the opposite: the finding IS the stored value, and it renders into every
    future turn for that binding whether or not it has reached a case yet, so an
    empty radius must still surface.
    """
    # Deferred: handlers/review_item.py imports the L6 and L7 handler modules,
    # and handlers/semantic_lexicon.py imports THIS module -- at module scope
    # that is an import cycle. The aggregator's _emit does the same.
    from .datastore.handlers.review_item import review_item_handlers

    result = blast_radius_result(
        affected_cases(conn, layer=layer, entry_ref=entry_ref, since=since),
        layer=layer,
        entry_ref=entry_ref,
        since=since,
    )
    if not result["open_cases"] and not emit_when_no_open_cases:
        return None
    return review_item_handlers()["toee_review_inbox"]["propose_review_item"](
        conn,
        {
            "kind": BLAST_RADIUS_KIND,
            "subject_ref": subject_ref,
            "evidence": blast_radius_evidence(result, reason=reason),
        },
        context,
    )


def record_blast_radius(conn, context, *, layer: str, entry_ref: str, reason: str) -> None:
    """The decide paths' hook: retire/edit/clear -> "who did I already answer with it?"

    Best-effort by construction, and the SAVEPOINT is what makes that true rather
    than aspirational. Catching an exception in Python does not un-abort a
    Postgres transaction: without the nested ``conn.transaction()`` a failure in
    here would poison the surrounding transaction and the admin's retire would
    fail at COMMIT anyway -- a governance decision lost to a bookkeeping error.
    Inside the savepoint, a failure rolls back only what this function did.

    It is still ONE transaction with the decision it follows, which is
    deliberate: an item claiming an entry was retired, on a retire that then
    rolled back, would be a review queue describing something that never
    happened.
    """
    try:
        with conn.transaction():
            measure_and_emit(
                conn,
                context,
                layer=layer,
                entry_ref=entry_ref,
                reason=reason,
                subject_ref=blast_radius_subject_ref(layer, entry_ref),
                emit_when_no_open_cases=False,
            )
    except Exception as exc:
        # Exception TYPE only, never str(exc): the message could echo
        # store-supplied content into the log (record_injection's posture).
        logger.warning(
            "blast-radius item not raised for layer=%s reason=%s error_type=%s; "
            "the decision itself is unaffected",
            layer,
            reason,
            type(exc).__name__,
        )


# --- D21: the one-time re-scan of L4 values written before S08 ---------------


def _flagged(slot_value: Optional[str], evidence: Optional[str]) -> bool:
    """Does this stored row trip L4's OWN write scan (S08's ``scan_memory_write``)?

    The same resolver the write path calls, not a second copy of the pattern
    list: a re-scan that could disagree with the guard it is auditing would be
    worse than no re-scan. Injection leg only, per D2 -- running the PII leg over
    L4 would flag ``leave at back door, call 604-555-1212``, which is a correct
    delivery habit and the exact false positive that split the scanners.
    """
    try:
        scan_memory_write(slot_value or "", evidence)
    except ToolDriverError:
        return True
    return False


def rescan_l4_slot_values(conn, context, *, emit: bool = True) -> dict[str, Any]:
    """D21: re-scan every stored L4 value and PROPOSE a review item per hit.

    S08 wired ``scan_memory_write`` into the L4 write path and hard-rejects --
    which closed the door for NEW writes only. Every slot written before that
    commit entered the store unscanned, is still there, and still renders into
    the prompt on every subsequent turn. S06's render-side fence (``_fence_safe``)
    already stops a stored value from breaking OUT of its block, so what is left
    is the semantic half: a stored ``ignore previous instructions`` has no
    backstop but the fence and the untrusted-data framing around it. Persistence
    is the difference from a live message -- one accepted write replays into
    every future turn for that binding, which is why FR-10 rejects at write time
    instead of trusting the fence.

    **Propose-only, and here that matters more than usual (NFR-3).** A flagged
    value may well be legitimate customer data that merely trips a pattern --
    that false-positive risk is why D2 split the scanners in the first place. So
    nothing is deleted, nothing is masked, and no value is copied anywhere: the
    item carries the slot's coordinates and the fact that it was flagged, and a
    human decides. The value itself CANNOT ride along even if someone wanted it
    to: ``review_item.evidence`` is injection-scanned on the way in, so the very
    pattern that flagged the row would ``policy_blocked`` the emission.

    Every row is scanned, not only the ones predating S08 -- the store carries no
    "scanned at" marker, and a row that post-dates the guard cannot be a hit
    unless the pattern list has since widened, in which case it is a hit worth
    seeing. Re-running is safe: the store's open-set unique index means a
    still-open finding is returned rather than duplicated.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT binding_key, slot_name, slot_value, evidence, created_at "
            "FROM customer_memory_slot ORDER BY created_at"
        )
        rows = cur.fetchall()

    summary: dict[str, Any] = {
        "scanned": len(rows),
        "flagged": 0,
        "emitted": 0,
        "already_open": 0,
        # Slot NAMES and binding KINDS only -- never a binding key and never a
        # value. This summary is printed to a console and returned to a caller.
        "flagged_slots": [],
    }
    for row in rows:
        if not _flagged(row["slot_value"], row["evidence"]):
            continue
        summary["flagged"] += 1
        summary["flagged_slots"].append(row["slot_name"])
        if not emit:
            continue
        entry_ref = f"{row['binding_key']}:{row['slot_name']}"
        item = measure_and_emit(
            conn,
            context,
            layer=LAYER_L4,
            entry_ref=entry_ref,
            reason=REASON_UNSCANNED_INJECTION,
            subject_ref=unscanned_subject_ref(entry_ref),
            emit_when_no_open_cases=True,
        )
        if item is not None and item.get("proposed"):
            summary["emitted"] += 1
        else:
            summary["already_open"] += 1
    return summary


def run_rescan() -> dict[str, Any]:
    """Run D21's re-scan against the configured database, in one transaction."""
    from toee_hermes.plugin.profiles import INTERNAL
    from toee_hermes.tool_gate import ToolExecutionContext

    from .datastore.config import database_url
    from .datastore.pool import get_database_pool

    # INTERNAL with no actor: `resolve_review_item_emitter` asserts the profile
    # and deliberately NOT an actor, because an emission is inert and a sweep has
    # no human at the keyboard. No `dispatch_route` -- that axis exists for L6/L7
    # provenance (D3/D20) and nothing here writes provenance.
    context = ToolExecutionContext(profile=INTERNAL)
    with get_database_pool(database_url()).connection() as conn:
        summary = rescan_l4_slot_values(conn, context)
        conn.commit()
    return summary


def main() -> int:  # pragma: no cover - thin CLI shell
    summary = run_rescan()
    print(f"L4 re-scan (D21): {summary}")
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI shell
    raise SystemExit(main())
