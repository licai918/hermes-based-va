"""Injection provenance ledger: which memory entries reached which turn (S09, FR-11).

The write half of migration ``0030_injection_ledger``. Two things it is NOT:

**Not inside ``render_injection`` (D4.2).** That function is pure and store-less
and lives in the plugin package with three callers -- the two live turn paths and
``eval_record``. Putting DB I/O in or around it is a layering violation that
drags a database dependency into the eval-record path. The two LIVE callers
(``openrouter.run_turn``, ``copilot_turn.run_turn``) call
:func:`record_injection` themselves, with an explicit list of injected entry
refs built by :func:`injected_entry_refs`; ``eval_record`` does not call it at
all.

**Gated PER LAYER, on the flag that layer's injection rode (D4.1).** The slice
text says "gate on the same axes the injections themselves are gated on" AND
"never on the record/replay path", and D4.1 resolved the apparent conflict in
favour of the eval axis. One BLANKET eval-axis gate was the wrong reading of it:
L6 injection rides ``AGENT_EXPERIENCE_*_INJECTION`` while
:func:`~hermes_runtime.tool_backend.memory_enabled` rides ``TOOL_BACKEND``, so a
deployment injecting confirmed learnings with the memory backend off recorded
nothing at all -- an empty ledger for exactly the entries S10 and S26 exist to
follow. :data:`_LAYER_GATES` gates each row on its own layer's flag instead, and
D4.1 still holds because EVERY one of those flags is off on the eval
record/replay path (that is the same L6 default-off that pins eval determinism
for the injection itself). Two further, independent skips: nothing injected ->
nothing written, and a store with no ledger writer -> nothing written.

**Never fails a turn, and never precedes one (NFR-5).** :func:`record_injection`
never touches ``{final_response, messages}`` and swallows every exception to a
WARN (exception TYPE only -- never ``str(exc)``, which could echo store-supplied
content), exactly like the memory read's swallow. The write itself is a
synchronous INSERT + commit, so both callers make it AFTER the model call
returns: in front of it, it was a database round-trip on the reply path (the
thing NFR-5 forbids) and it recorded turns that then failed. "Fire-and-forget"
here means best-effort and unobserved by the turn -- not asynchronous.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence

from toee_hermes.plugin.profiles import INTERNAL

from .tool_backend import (
    _gateway_store,
    agent_experience_external_injection_enabled,
    agent_experience_injection_enabled,
    lexicon_external_injection_enabled,
    lexicon_injection_enabled,
    memory_enabled,
)

logger = logging.getLogger(__name__)

# The memory layers that can reach a prompt. Values are the `layer` column, and
# the set the table's CHECK constraint enforces (migration 0031) -- a typo'd
# layer is otherwise a permanently unjoinable row nothing ever notices.
LAYER_L4 = "l4"  # Customer Memory preference slots (per-customer, PII)
LAYER_L6 = "l6"  # confirmed agent-experience notes (shared, operational)
LAYER_L7 = "l7"  # semantic lexicon entries (0.0.5 S06 renders the glossary)
LAYERS = (LAYER_L4, LAYER_L6, LAYER_L7)


def _l6_injection_enabled() -> bool:
    """Either L6 injection axis -- the external one or the copilot one.

    An L6 ref only exists because one of the two turn paths actually rendered a
    confirmed entry, and each path gated that render on its OWN flag; so the
    per-path exactness is already carried by the ref list, and this disjunction
    is exact for every row that can reach it.
    """
    return agent_experience_external_injection_enabled() or agent_experience_injection_enabled()


def _l7_injection_enabled() -> bool:
    """Either L7 injection axis -- the external one or the copilot one.

    Same disjunction, same reasoning as :func:`_l6_injection_enabled`: an L7 ref
    only exists because one of the two turn paths actually rendered a confirmed
    lexicon entry, and each path gated that render on its OWN flag.
    """
    return lexicon_external_injection_enabled() or lexicon_injection_enabled()


# Each layer's ledger row rides the same flag that layer's INJECTION rode (D4.1
# as CORRECTED). Registering L7 against a global flag here -- `memory_enabled`,
# the default this dict used to fall through to -- would reproduce for L7 exactly
# the hole the L6 fix closed: a deployment with lexicon injection on and the
# memory backend off would render the glossary and record nothing.
_LAYER_GATES = {
    LAYER_L4: memory_enabled,
    LAYER_L6: _l6_injection_enabled,
    LAYER_L7: _l7_injection_enabled,
}

# ponytail: 180 days. The ledger's readers are S10's blast radius ("which open
# cases did this entry touch?") and S26's effectiveness join, and both want more
# history than the judge-sampling horizon (honored_rate.DEFAULT_WINDOW_SECONDS,
# 7 days) so a score can still be attributed weeks later. Widen it if S26 ever
# wants a longer trend; the only cost is table size.
PRUNE_WINDOW_SECONDS = 180 * 24 * 60 * 60

# S20's zero-hit window lives HERE, next to the prune window, on purpose (D12).
# S20 calls an entry "zero-hit" from ledger-derived usage; if the ledger were
# pruned FIRST, garbage collection would manufacture retirement candidates for
# entries that are actively in use -- a memory-loss actuator driven by a GC
# artifact. One module owning both constants makes the relation
# `PRUNE_WINDOW_SECONDS >= ZERO_HIT_WINDOW_SECONDS` (asserted in
# tests/test_injection_ledger.py) impossible to break by editing one file.
# S20 imports this rather than declaring its own.
ZERO_HIT_WINDOW_SECONDS = 90 * 24 * 60 * 60

# The prune's "last run" record, on the same surface the retention sweep uses
# (a `workbench_audit_log` row, read exactly like `get_retention_status` reads
# `retention_sweep`) -- no new sweep-state table for three numbers.
PRUNE_AUDIT_ACTION = "injection_ledger_prune"


def injected_entry_refs(
    *,
    binding_key: Optional[str],
    memory: Optional[Sequence[Mapping[str, Any]]],
    experience: Optional[Sequence[Mapping[str, Any]]] = None,
    lexicon: Optional[Sequence[Mapping[str, Any]]] = None,
) -> list[tuple[str, str]]:
    """The ``(layer, entry_ref)`` pairs ``render_injection`` actually rendered.

    Follows ``hooks._render_memory`` / ``_render_experience``: a slot with no
    name and an entry with no content are dropped by the renderer, so a ref for
    either would claim an injection that never happened -- and a false claim is
    precisely what S26's per-entry score cannot survive.

    Not byte-for-byte identical in one direction, deliberately: the renderer
    skips a slot only when ``slot`` is ``None``, while this also skips ``""``.
    Aligning them costs more than the mismatch: matching the renderer would emit
    ``binding_key + ":"``, a ref that joins to nothing, and making the renderer
    skip ``""`` would edit an eval-pinned prompt (NFR-4) for a row
    ``customer_memory_slot`` cannot hold anyway. The residual is one direction
    only -- the ledger can UNDER-claim an injection, never over-claim it.

    ``binding_key`` is required for L4 refs: without it there is no stable
    natural key, so those slots are omitted rather than recorded under a ref
    nothing can join back to. (In practice memory is only ever loaded once a
    binding key resolved, so this is belt not braces.)

    ``lexicon`` is the L7 seat, live since 0.0.5 S06: both turn paths pass the
    confirmed glossary they rendered. A row with no ``id`` is dropped for the
    same reason as the other two -- an unjoinable ref.
    """
    refs: list[tuple[str, str]] = []
    if binding_key:
        for slot in memory or ():
            slot_name = slot.get("slot")
            if slot_name:
                refs.append((LAYER_L4, f"{binding_key}:{slot_name}"))
    for entry in experience or ():
        entry_id = entry.get("id")
        if entry_id and entry.get("content"):
            refs.append((LAYER_L6, str(entry_id)))
    for entry in lexicon or ():
        entry_id = entry.get("id")
        if entry_id:
            refs.append((LAYER_L7, str(entry_id)))
    return refs


def record_injection(
    store: Optional[Any],
    *,
    turn_ref: Optional[str],
    case_or_binding_ref: Optional[str],
    entries: Iterable[tuple[str, str]],
) -> None:
    """Best-effort: record this turn's injected entries. Never raises.

    Called from the two LIVE turn paths only, and only AFTER the model call has
    returned -- the write is a synchronous INSERT + commit, so it must not sit in
    front of the reply (NFR-5), and a turn that never produced a reply has no
    injection to record. ``store`` is the gateway store the turn already holds
    (tests inject one); ``None`` builds the default. A store without
    ``record_injection_ledger`` -- the scenario-scoped stores the eval record
    paths bind -- is a no-op, mirroring
    :func:`~hermes_runtime.tool_backend.load_confirmed_experience`'s posture.

    Rows are filtered PER LAYER by :data:`_LAYER_GATES`, so an L6 row lands on a
    deployment that injects confirmed learnings with the memory backend off, and
    an L4 row still needs that backend.
    """
    rows = [
        (layer, entry_ref)
        for layer, entry_ref in entries
        if _LAYER_GATES.get(layer, memory_enabled)()
    ]
    if not rows or not turn_ref:
        return
    try:
        resolved_store = store if store is not None else _gateway_store()
        writer = getattr(resolved_store, "record_injection_ledger", None)
        if writer is None:
            return
        writer(
            turn_ref=turn_ref,
            case_or_binding_ref=case_or_binding_ref,
            entries=rows,
        )
    except Exception as exc:
        # ponytail: swallow so a ledger hiccup can never fail or delay a reply
        # (NFR-5). The turn's result is already independent of this call; this
        # keeps the WARN from being silent. Exception TYPE only, never str(exc).
        logger.warning(
            "Injection ledger write failed turn_ref=%s rows=%s error_type=%s; "
            "the turn is unaffected",
            turn_ref,
            len(rows),
            type(exc).__name__,
        )


# --- retention: the windowed prune (0.0.4 S04 scheduled-worker pattern) --------


def prune_injection_ledger(conn, *, window_seconds: int = PRUNE_WINDOW_SECONDS) -> int:
    """Delete ledger rows older than the window on a CALLER-OWNED connection.

    Returns the row count. No commit -- the caller owns the transaction, so the
    DELETE and its audit row land together (the retention sweep's discipline).
    """
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM injection_ledger WHERE injected_at < now() - make_interval(secs => %s)",
            (window_seconds,),
        )
        return cur.rowcount


def run_injection_ledger_prune_job(
    payload: Mapping[str, Any],
    *,
    conn: Optional[Any] = None,
    window_seconds: int = PRUNE_WINDOW_SECONDS,
) -> None:
    """The ``injection_ledger_prune`` job body: age the ledger out, record the run.

    ``conn`` is injectable for tests (an isolated-schema connection); production
    takes a pooled connection, matching ``honored_rate``. A failure propagates so
    the job retries and eventually dead-letters -- unlike the per-turn WRITE,
    nobody is waiting on this and a silently-skipped prune is unbounded growth.
    """
    del payload  # scheduled job; the (schedule_window, window_start) payload is unused.
    if conn is not None:
        _prune_and_audit(conn, window_seconds)
        return
    from .datastore.config import database_url
    from .datastore.pool import get_database_pool

    with get_database_pool(database_url()).connection() as pooled:
        _prune_and_audit(pooled, window_seconds)


def _prune_and_audit(conn, window_seconds: int) -> None:
    from .datastore.handlers._common import insert_audit
    from .entry_effectiveness import refresh_entry_effectiveness

    deleted = prune_injection_ledger(conn, window_seconds=window_seconds)
    # S26 (FR-31): recompute the per-entry aggregate derived from this table, in
    # the SAME transaction and AFTER the prune -- so the effectiveness numbers are
    # over exactly the rows that survive, never over a window that was already
    # garbage-collected. It rides this tick rather than a job of its own because
    # this job already owns the ledger's lifecycle, and because the judge job
    # (the other candidate) SKIPS entirely without an API key, which would leave
    # usage frozen on a deployment that is still serving turns.
    entries = refresh_entry_effectiveness(conn)
    insert_audit(
        conn,
        # Unattended, exactly like a scheduled retention sweep: the only profile
        # the admin memory surfaces run under, and no attributed actor.
        profile=INTERNAL,
        account_id=None,
        action=PRUNE_AUDIT_ACTION,
        target_type="injection_ledger",
        target_id=None,
        details={
            "deleted": deleted,
            "window_seconds": window_seconds,
            "effectiveness_entries": entries,
            "run_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    conn.commit()
    logger.info(
        "injection_ledger prune: %s row(s) older than %ss deleted; "
        "entry_effectiveness recomputed over %s entries",
        deleted,
        window_seconds,
        entries,
    )
