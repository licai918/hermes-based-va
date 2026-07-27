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

**Not gated on the injection axis (D4.1).** The slice text says "gate on the
same axes the injections themselves are gated on" AND "never on the
record/replay path", and those are different axes -- ``eval_record`` DOES render
a scenario's memory preset, so the first clause would write rows during record
and break the replay gate. The gate here is the EVAL axis, spelled the way the
existing eval-neutral emit (``tool_backend.record_memory_injection_metric``)
spells it: :func:`~hermes_runtime.tool_backend.memory_enabled`, i.e. "this
deployment has a business datastore". The eval record/replay path runs
``TOOL_BACKEND=mock``, so it is excluded by the same predicate that answers
"is there a table to write to". Nothing was injected -> nothing is written, as a
second, independent skip.

**Never stalls or fails a turn (NFR-5).** :func:`record_injection` is
fire-and-forget: it never touches ``{final_response, messages}`` and swallows
every exception to a WARN (exception TYPE only -- never ``str(exc)``, which
could echo store-supplied content), exactly like the memory read's swallow.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence

from toee_hermes.plugin.profiles import INTERNAL

from .tool_backend import _gateway_store, memory_enabled

logger = logging.getLogger(__name__)

# The memory layers that can reach a prompt. Values are the `layer` column.
LAYER_L4 = "l4"  # Customer Memory preference slots (per-customer, PII)
LAYER_L6 = "l6"  # confirmed agent-experience notes (shared, operational)
LAYER_L7 = "l7"  # semantic lexicon entries -- additive when S06 renders them

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

    Mirrors ``hooks._render_memory`` / ``_render_experience`` skip-for-skip: a
    slot with no name and an entry with no content are dropped by the renderer,
    so a ref for either would claim an injection that never happened -- and a
    false claim is precisely what S26's per-entry score cannot survive.

    ``binding_key`` is required for L4 refs: without it there is no stable
    natural key, so those slots are omitted rather than recorded under a ref
    nothing can join back to. (In practice memory is only ever loaded once a
    binding key resolved, so this is belt not braces.)

    ``lexicon`` is the L7 seat, wired when S06 renders that block; today every
    caller leaves it ``None`` and it contributes nothing.
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
    """Fire-and-forget: record this turn's injected entries. Never raises.

    Called from the two LIVE turn paths only. ``store`` is the gateway store the
    turn already holds (tests inject one); ``None`` builds the default. A store
    without ``record_injection_ledger`` -- the scenario-scoped stores the eval
    record paths bind -- is a no-op, mirroring
    :func:`~hermes_runtime.tool_backend.load_confirmed_experience`'s posture.
    """
    rows = list(entries)
    if not rows or not turn_ref:
        return
    if not memory_enabled():
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

    deleted = prune_injection_ledger(conn, window_seconds=window_seconds)
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
            "run_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    conn.commit()
    logger.info(
        "injection_ledger prune: %s row(s) older than %ss deleted", deleted, window_seconds
    )
