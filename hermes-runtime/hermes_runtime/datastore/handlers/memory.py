"""Datastore handlers for ``toee_customer_memory`` (ADR-0110-0114).

Persists the fixed four preference slots (ADR-0111) to ``customer_memory_slot``,
bound to the verified Shopify customer id (Session Identity Snapshot, ADR-0043)
or a canonical provisional channel key derived from context, fail-closed when no
channel identity resolves (:func:`resolve_customer_memory_binding`, ADR-0112, PRD
FR-5/S02). Open-ended keys are rejected, never silently stored, and a value over
``MEMORY_VALUE_MAX_LENGTH`` chars is rejected the same way (PRD FR-3). ``source``
is derived from ``context.profile`` by :func:`resolve_memory_write_source`, never
taken from the model-supplied tool params (RK-1); an optional ``evidence`` param
(verbatim customer phrase) is persisted alongside the write for audit, capped at
``MEMORY_EVIDENCE_MAX_LENGTH`` chars the same governed way. The slot enum, both
resolvers, and the value/evidence validators are all imported from the plugin so
the datastore and mock paths share one source of truth: this is security-sensitive
logic that must not drift between the two. The acting employee, when one exists,
is persisted in ``actor_account_id`` (0007 migration, nullable, no backfill) --
taken directly from ``context.user_id``, framework-set by the dispatch route from
the request's asserted actor and never model-supplied: present on a UI correction,
NULL on an AI draft-turn write or a provisional->verified merge (PRD 0.0.2 FR-4/R2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from psycopg.rows import dict_row

from toee_hermes.drivers.mock.memory import (
    ERASE_REAPPEARANCE_WINDOW_DAYS,
    MEMORY_ACTION_ERASED,
    MEMORY_ACTION_PREFERENCE_UPDATED,
    MEMORY_PREFERENCE_SLOTS,
    _read_evidence,
    _require_slot,
    _require_value,
    deletion_success_payload,
    erase_binding_keys,
    is_differing_value_overwrite,
    is_verified_customer_identity,
    resolve_clear_authorization,
    resolve_customer_memory_binding,
    resolve_erase_authorization,
    resolve_memory_write_source,
    scan_memory_write,
)
from toee_hermes.errors import ToolDriverError

from toee_hermes.blast_radius import REASON_SLOT_CLEARED

from ...blast_radius import record_blast_radius
from ...injection_ledger import LAYER_L4
from ._common import (
    METRIC_MEMORY_POLLUTION_REJECTED,
    METRIC_SELF_SERVICE_USAGE,
    insert_audit,
    insert_metric_event,
    new_id,
    serialize_row,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from toee_hermes.tool_gate import ToolExecutionContext


def _upsert_preference(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    slot = _require_slot(params)
    value = _require_value(params)
    evidence = _read_evidence(params)
    # S08 (FR-10): the shared L4 write scan -- the SAME resolver the mock twin
    # calls, injection leg only (see its docstring for why L4 gets no PII leg).
    try:
        scan_memory_write(value, evidence)
    except ToolDriverError:
        # S22 counts rejections as its pollution numerator, so a rejection that
        # leaves no trace is a rejection S22 cannot see. The re-raise below makes
        # PostgresDriver.execute roll this unit of work back, which would take an
        # ordinary insert_metric_event row with it -- so this one is committed on
        # the spot. Safe precisely because the scan runs before ANY write:
        # nothing else is pending, so the commit commits exactly the counter and
        # zero slot rows, which is what a hard reject means.
        insert_metric_event(conn, metric=METRIC_MEMORY_POLLUTION_REJECTED)
        conn.commit()
        raise
    # RK-1: source is framework-derived from context.profile (shared resolver, same
    # as the mock twin), never the model-supplied params — any "source" the caller
    # passed is ignored.
    source = resolve_memory_write_source(context)
    binding_key, binding_kind = resolve_customer_memory_binding(context, params)
    # FR-4/R2: actor is framework-derived from context.user_id -- the dispatch
    # route sets it from the request's asserted actor_account_id (ADR-0141), never
    # a model-supplied param. Present -> a UI correction; absent (None) -> an AI
    # draft-turn write, same presence check resolve_memory_write_source already
    # makes for source (PRD §9).
    actor_account_id = context.user_id
    with conn.cursor() as cur:
        # FR-9 (0.0.5 S07): the prior value and ITS author, read in the SAME
        # transaction/cursor the write below uses, and LOCKED. ``FOR UPDATE``
        # is load-bearing, not decoration: the pool sets no isolation level
        # (datastore/pool.py), so this runs at READ COMMITTED, where an
        # unlocked read lets two writers on the same (binding_key, slot) both
        # see "sms" -- T1 commits "email", T2's ON CONFLICT then re-reads the
        # row underneath itself, writes "phone", and audits old_value="sms".
        # The trail would read sms->email AND sms->phone: a broken chain with
        # one row that is simply untrue, in the table whose whole purpose is
        # being believed. Locking serializes the two so the chain stays honest
        # (test_two_concurrent_overwrites_of_one_slot_record_a_coherent_chain).
        # Contention is one customer's one slot, so the cost is negligible.
        # ponytail: a row that does NOT exist yet cannot be locked, so two
        # concurrent FIRST writes still race -- but neither audits (no prior
        # value), so the outcome is a MISSING transition, never a false one.
        # Upgrade path if that matters: an advisory lock on the binding.
        cur.execute(
            "SELECT slot_value, actor_account_id FROM customer_memory_slot "
            "WHERE binding_key = %s AND slot_name = %s FOR UPDATE",
            (binding_key, slot),
        )
        row = cur.fetchone()
        old_value, old_actor_account_id = row if row else (None, None)
        cur.execute(
            """
            INSERT INTO customer_memory_slot
                (id, binding_key, binding_kind, slot_name, slot_value, source,
                 evidence, actor_account_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (binding_key, slot_name) DO UPDATE SET
                slot_value = EXCLUDED.slot_value,
                source = EXCLUDED.source,
                evidence = EXCLUDED.evidence,
                binding_kind = EXCLUDED.binding_kind,
                actor_account_id = EXCLUDED.actor_account_id,
                updated_at = now(),
                last_interaction_at = now()
            """,
            (new_id("mem"), binding_key, binding_kind, slot, value, source, evidence,
             actor_account_id),
        )
    # FR-9: a genuine overwrite of an EXISTING value records ONE preference_
    # updated audit row carrying old->new -- value-change history becomes
    # auditable (and later rollback-able). The "differing-value overwrite"
    # rule itself lives in the shared plugin module, not inline here: S22
    # counts exactly these rows for its conflict-rate metric and must not
    # re-derive a second, drifting definition of the same rule.
    if is_differing_value_overwrite(old_value, value):
        insert_audit(
            conn,
            profile=context.profile,
            account_id=actor_account_id,
            action=MEMORY_ACTION_PREFERENCE_UPDATED,
            target_type="customer_memory_slot",
            target_id=slot,
            details={
                "slot": slot,
                "binding_key": binding_key,
                "old_value": old_value,
                "new_value": value,
                # Who set the value being replaced. The slot's own
                # actor_account_id is overwritten in place by the ON CONFLICT
                # update above, so without capturing it here the audit trail
                # records WHAT was replaced but never WHO set it -- half of
                # the brief's own "I see WHO changed a preference and what the
                # OLD value was". JSONB, so no migration. NULL (never absent)
                # for an unattributed AI draft-turn / customer_explicit prior
                # write, so "nobody was attributed" reads differently from
                # "this row predates the field".
                "old_actor_account_id": old_actor_account_id,
            },
        )
    return {
        "binding_key": binding_key,
        "slot": slot,
        "value": value,
        "source": source,
        "evidence": evidence,
        "stored": True,
    }


def _clear_preference(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    """Clears one preference slot and records an attributed audit row.

    0.0.3 S20 (FR-20): closes the 0.0.2 PAC-1 caveat -- a clear used to leave
    zero trace (a hard DELETE, no audit row). 0.0.3 S21 (FR-21, NFR-2) EXTENDS
    that same governed ``clear_preference`` action -- still the ONE write
    action, no new write path, no schema change -- to also authorize a
    VERIFIED customer clearing their OWN binding on the EXTERNAL profile.

    Who is authorized (rep/supervisor with an attributed actor, or a verified
    EXTERNAL customer) and the resulting audited ``account_id``/``initiator``
    are resolved by the shared ``resolve_clear_authorization`` -- the SAME
    resolver the mock driver's ``clear_preference`` calls, so this
    security-sensitive gate can't drift between the two twins (see its
    docstring for the full per-profile behavior).
    """
    slot = _require_slot(params)
    account_id, initiator = resolve_clear_authorization(context)

    binding_key, _ = resolve_customer_memory_binding(context, params)
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM customer_memory_slot WHERE binding_key = %s AND slot_name = %s",
            (binding_key, slot),
        )
        deleted = cur.rowcount
    insert_audit(
        conn,
        profile=context.profile,
        account_id=account_id,
        action="preference_cleared",
        target_type="customer_memory_slot",
        target_id=slot,
        details={"slot": slot, "binding_key": binding_key, "initiator": initiator},
    )
    # S21/FR-30: real self-service-usage counter. Only a CUSTOMER-initiated clear
    # that actually removed a slot counts -- gating on rowcount is the once-only
    # fence: a redelivered durable turn that re-runs this clear finds the slot
    # already gone (deletes 0) and emits nothing, so it can't double-count.
    if initiator == "customer" and deleted:
        insert_metric_event(conn, metric=METRIC_SELF_SERVICE_USAGE)
    # 0.0.5 S10 (FR-12): FR-12's "cleared". Gated on the SAME `deleted` rowcount
    # as the counter above -- a clear that removed nothing changed nothing, so
    # there is no blast radius to review.
    #
    # STAFF-initiated only, and that is a decision with two reasons. FR-12's
    # blast radius is about a GOVERNANCE correction ("we removed this, who did we
    # already answer with it?"); a customer exercising FR-21 self-service is
    # routine, and raising a review item every time one says "forget my delivery
    # preference" would manufacture the queue S15's idempotence exists to
    # prevent. It is also the only correct wiring: this action is reachable on
    # the EXTERNAL profile, and `resolve_review_item_emitter` is INTERNAL-only,
    # so an unconditional emission would put a `policy_blocked` inside the
    # customer's own clear.
    if initiator != "customer" and deleted:
        record_blast_radius(
            conn,
            context,
            layer=LAYER_L4,
            entry_ref=f"{binding_key}:{slot}",
            reason=REASON_SLOT_CLEARED,
        )
    return {"binding_key": binding_key, "slot": slot, "cleared": True}


def _linked_channel_identities(cur, shopify_customer_id: str) -> list[tuple[str, str]]:
    """Every ``(channel, channel_identity)`` the Identity Graph links to this
    customer (0.0.5 S11, D10).

    The same read ``PostgresGatewayStore.list_channel_identities_for_customer``
    makes for the cross-channel merge, on the CALLER's cursor so it shares the
    erase's transaction -- a link appearing mid-erase must not produce a binding
    the erase enumerated but did not clear. Read-only on L1; the erase never
    unlinks an identity (that is the org-wide erasure workflow, PRD §6).
    """
    cur.execute(
        """
        SELECT DISTINCT channel, channel_identity FROM identity_link
        WHERE shopify_customer_id = %s
        ORDER BY channel, channel_identity
        """,
        (shopify_customer_id,),
    )
    return [(row[0], row[1]) for row in cur.fetchall()]


def _erase_customer_memory(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    """Erase a customer's WHOLE memory binding (0.0.5 S11, FR-13, US7, PAC-3).

    A governed LOOP over the four ADR-0111 slots, not a new write primitive: the
    same per-slot DELETE and the same ``preference_cleared`` audit row
    :func:`_clear_preference` writes, plus ONE ``memory_erased`` summary row
    carrying the per-slot outcomes -- so a fully populated binding produces the
    ``4+1`` rows the acceptance names, all attributed to the administrator.

    **It clears every binding the customer reaches, not just the verified one
    (D10).** ``merge_provisional_memory`` copies provisional slots from every
    linked channel identity onto the verified key on the next verified turn, so
    an erase that stopped at the verified binding would be silently undone by
    the customer's next SMS -- and FR-14's alert would then fire on the erase's
    own aftermath instead of on a real event. The keys come from the shared
    :func:`erase_binding_keys` (the mock twin calls the same one), fed the
    Identity Graph links this transaction just read.

    **Which stores it touches, and which it deliberately does not.**
    ``customer_memory_slot`` is the only place L4 CONTENT lives -- ``evidence``
    is a column on the same row, so the verbatim customer phrase goes with it.
    ``workbench_audit_log`` is written, not cleared. ``injection_ledger`` and
    ``customer_memory_merge_audit`` carry this binding key but hold PROVENANCE
    (which slot NAME reached which turn; which keys were merged) and no slot
    value at all: PAC-3 asks the erase to leave a complete audit trail, and
    deleting the trail would be the opposite of that -- it would also break
    S10's blast-radius join. ``identity_link`` is read, never written.

    The trailing unscoped-by-slot DELETE is what makes "whole binding" literally
    true: the per-slot loop can only remove slots this build knows about, and
    ``customer_memory_slot`` has no CHECK constraint pinning ``slot_name`` to the
    four. It is still scoped to ONE ``binding_key``, and its rowcount is recorded
    rather than swallowed, so an off-enum row shows up in the summary instead of
    surviving quietly.
    """
    account_id, initiator = resolve_erase_authorization(context)
    binding_key, binding_kind = resolve_customer_memory_binding(context, params)
    with conn.cursor() as cur:
        linked = (
            _linked_channel_identities(cur, binding_key)
            if binding_kind == "verified"
            else []
        )
        keys = erase_binding_keys(context, linked)
        bindings: list[dict[str, Any]] = []
        for key in keys:
            cleared: list[str] = []
            for slot in MEMORY_PREFERENCE_SLOTS:
                cur.execute(
                    "DELETE FROM customer_memory_slot "
                    "WHERE binding_key = %s AND slot_name = %s",
                    (key, slot),
                )
                if cur.rowcount:
                    cleared.append(slot)
            cur.execute(
                "DELETE FROM customer_memory_slot WHERE binding_key = %s", (key,)
            )
            bindings.append(
                {
                    "binding_key": key,
                    "cleared_slots": cleared,
                    "extra_rows_removed": cur.rowcount,
                }
            )

    for entry in bindings:
        key = entry["binding_key"]
        for slot in MEMORY_PREFERENCE_SLOTS:
            insert_audit(
                conn,
                profile=context.profile,
                account_id=account_id,
                action="preference_cleared",
                target_type="customer_memory_slot",
                target_id=slot,
                details={
                    "slot": slot,
                    "binding_key": key,
                    "initiator": initiator,
                    # Distinguishes a slot swept by the whole-binding erase from
                    # a supervisor clearing that one slot on purpose, without
                    # inventing a second audit action the Memory Audit console
                    # and S22's counters would both have to learn.
                    "erase": True,
                },
            )
        insert_audit(
            conn,
            profile=context.profile,
            account_id=account_id,
            action=MEMORY_ACTION_ERASED,
            target_type="customer_memory_slot",
            target_id=key,
            details={
                "binding_key": key,
                "initiator": initiator,
                "cleared_slots": entry["cleared_slots"],
                "extra_rows_removed": entry["extra_rows_removed"],
                # Every key this one erase touched, on every row, so the trail
                # reads whole from whichever binding a supervisor looks at.
                "erased_bindings": keys,
            },
        )

    return {
        "binding_key": binding_key,
        "bindings": bindings,
        "cleared": sum(len(entry["cleared_slots"]) for entry in bindings),
        "erased": True,
    }


def deletion_success_metric(cur) -> dict[str, Any]:
    """FR-14's deletion-success tripwire: cleared-and-STAYED-cleared.

    Deterministic SQL over two existing tables -- no new column, no new counter.
    The anchor is the ``memory_erased`` summary row :func:`_erase_customer_memory`
    writes; the observation is ``customer_memory_slot`` itself. **The store, not
    a return value**: an erase that reported success and left rows behind is
    exactly what this exists to catch, and only the store can say so.

    Any slot row on an erased binding inside
    :data:`ERASE_REAPPEARANCE_WINDOW_DAYS` is flagged, and the timestamp
    comparison classifies it rather than gating it -- ``residue`` (a row the
    erase itself failed to remove) versus ``reappeared`` (a row written
    afterwards, the merge/proposal case FR-14 names). Gating on "written after
    the erase" alone would have waved residue through, which is the half of the
    requirement a return-value check also misses.

    A binding erased twice collapses to ONE row (``GROUP BY``) anchored on the
    latest of its erases, so repeat erases never inflate the denominator. The
    ``MAX`` itself only picks which timestamp the residue/reappeared split is
    measured against -- it is NOT what clears a raised flag; the re-erase clears
    it by deleting the rows the flag was about
    (``test_a_second_erase_clears_the_flag_the_first_one_raised``, which stays
    green with ``MIN`` here, as a bait run confirmed).

    Outside the window nothing is examined at all: a customer stating a
    preference again months later is not an incident, and an alert that never
    expires stops being read.
    """
    cur.execute(
        """
        WITH erased AS (
            SELECT details ->> 'binding_key' AS binding_key,
                   MAX(created_at) AS erased_at
            FROM workbench_audit_log
            WHERE action = %s
              AND details ->> 'binding_key' IS NOT NULL
              AND created_at >= now() - make_interval(days => %s)
            GROUP BY 1
        )
        SELECT e.binding_key, s.slot_name, s.updated_at > e.erased_at
        FROM erased e
        LEFT JOIN customer_memory_slot s ON s.binding_key = e.binding_key
        """,
        (MEMORY_ACTION_ERASED, ERASE_REAPPEARANCE_WINDOW_DAYS),
    )
    rows = cur.fetchall()

    erased_bindings = {binding for binding, _slot, _after in rows}
    flagged: set[str] = set()
    residue: set[str] = set()
    reappeared: set[str] = set()
    flagged_slots: dict[str, int] = {}
    for binding, slot, after_erase in rows:
        if slot is None:  # LEFT JOIN miss: the binding is clean
            continue
        flagged.add(binding)
        (reappeared if after_erase else residue).add(binding)
        flagged_slots[slot] = flagged_slots.get(slot, 0) + 1

    return deletion_success_payload(
        erased_bindings=len(erased_bindings),
        flagged_bindings=len(flagged),
        residue_bindings=len(residue),
        reappeared_bindings=len(reappeared),
        flagged_slots=flagged_slots,
    )


def _get_preferences(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    binding_key, _ = resolve_customer_memory_binding(context, params)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT slot_name, slot_value FROM customer_memory_slot WHERE binding_key = %s",
            (binding_key,),
        )
        rows = cur.fetchall()
    return {
        "binding_key": binding_key,
        "preferences": {name: value for name, value in rows},
    }


def _get_my_memory_summary(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    """Customer-safe self-service summary read (0.0.3 S21, FR-21, NFR-2).

    Verified-only, same gate as the extended ``_clear_preference`` above: an
    EXTERNAL caller who is not a verified customer (unmatched, provisional, or
    ambiguous) gets ZERO data, never able to probe another customer's
    provisional slots by holding their phone/email (fail-closed, US13). Strips
    ALL internal metadata -- slot values only, no source, no actor, no
    timestamps, no binding_key -- reusing ``_get_preferences``' query but never
    its full response shape.

    NOTE: despite the "customer-facing" framing, ``get_my_memory_summary`` is
    also LLM-callable on internal_copilot (it isn't in
    ``_AGENT_EXCLUDED_ACTIONS``, so unexcluded actions ride the shared toolset
    registration onto INTERNAL's tool loop too). Not a gap: INTERNAL already
    has ``get_preferences``, a superset read.
    """
    if not is_verified_customer_identity(context.identity):
        raise ToolDriverError(
            "policy_blocked",
            "Customer Memory self-service requires a verified customer identity.",
        )
    binding_key, _ = resolve_customer_memory_binding(context, params)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT slot_name, slot_value FROM customer_memory_slot WHERE binding_key = %s",
            (binding_key,),
        )
        rows = cur.fetchall()
    return {"preferences": {name: value for name, value in rows}}


def _dismiss_proposal(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    """Audit-only write for a dismissed S14 proposal (0.0.3 S15, FR-16/FR-17).

    Persists no preference slot -- a bad guess can't quietly persist (US17) --
    only a Workbench Audit Log row recording the proposal (slot/value/evidence),
    the deciding employee, and the timestamp (``created_at``), mirroring the
    ``insert_audit`` calls the case handlers already make. Requires an
    attributed actor like every other governed employee decision (ADR-0141):
    a dismissal is always a rep at the keyboard, never the AI draft turn.
    """
    slot = _require_slot(params)
    value = _require_value(params)
    evidence = _read_evidence(params)
    account_id = context.user_id
    if not account_id:
        raise ToolDriverError(
            "policy_blocked",
            "A governed proposal dismissal requires an attributed actor.",
        )
    binding_key, _binding_kind = resolve_customer_memory_binding(context, params)
    insert_audit(
        conn,
        profile=context.profile,
        account_id=account_id,
        action="proposal_dismissed",
        target_type="customer_memory_slot",
        target_id=slot,
        details={"slot": slot, "value": value, "evidence": evidence, "binding_key": binding_key},
    )
    return {"binding_key": binding_key, "slot": slot, "dismissed": True}


def last_injection_at(cur, binding_key: str) -> Any:
    """When this binding's memory last reached a prompt, or ``None`` for never.

    0.0.5 S22 (FR-34a): the one number the per-customer memory-health strip
    cannot compose from reads that already exist. The other three -- slot age,
    correction count and clear history -- are already in the Memory Audit
    payload; this is the ledger's.

    **Scoped by binding, and exactly.** The ledger is org-wide, so without the
    per-binding filter every customer would show the same (latest) timestamp.
    ``entry_ref`` is matched EXACTLY against the four possible slot refs rather
    than by a ``binding_key || ':%'`` prefix, and the difference is real rather
    than stylistic: exact equality needs no LIKE escaping (a binding key is a
    raw phone/email/Shopify id and may contain ``%`` or ``_``) and cannot match
    a longer key that merely starts the same way. ``test_lifecycle_metrics.py``
    runs both prefix variants against the same fixture to show they answer with
    rows this read must not claim.

    The ``layer`` filter is not doing the same work -- an L6/L7 ref is an entry
    id and cannot collide with ``key:slot`` -- it is there so the read rides the
    ledger's ``(layer, entry_ref, injected_at DESC)`` index and so the scope is
    stated rather than relied on.

    Returns an ISO-8601 string (``serialize_row``'s convention) so the value
    crosses the dispatch boundary the same way every other timestamp does.
    Works on a caller-owned cursor of either row factory -- it reads one scalar
    by position out of a one-column row, which ``dict_row`` also yields.
    """
    cur.execute(
        "SELECT max(injected_at) FROM injection_ledger "
        "WHERE layer = %s AND entry_ref = ANY(%s)",
        (LAYER_L4, [f"{binding_key}:{slot}" for slot in MEMORY_PREFERENCE_SLOTS]),
    )
    row = cur.fetchone()
    value = list(row.values())[0] if isinstance(row, dict) else row[0]
    return value.isoformat() if value is not None else None


def _get_memory_audit(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    """Supervisor Memory Audit View read (0.0.3 S20, FR-20).

    "Full write history" is the UNION of two sources, no schema change: (1) the
    current ``customer_memory_slot`` rows -- who wrote what's live now, with
    source/actor/evidence/timestamps; (2) the append-only ``workbench_audit_log``
    trail for this binding (``proposal_dismissed`` from S15, ``preference_cleared``
    from this slice, ``preference_updated`` from 0.0.5 S07 (FR-9, old_value/
    new_value + the replaced value's ``old_actor_account_id`` in ``details``),
    and any future merge-audit row that carries the
    same ``binding_key`` in its ``details`` -- S16 joins accepted proposals into
    the same view later, so this deliberately does not filter any action out).
    Read-only: no write, no schema change. Never registered as an LLM-callable
    tool (see ``_AGENT_EXCLUDED_ACTIONS``) -- reached only from the admin BFF's
    deterministic ``tools:dispatch`` call.
    """
    binding_key, _ = resolve_customer_memory_binding(context, params)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT slot_name, slot_value, source, actor_account_id, evidence,
                   created_at, updated_at
            FROM customer_memory_slot
            WHERE binding_key = %s
            ORDER BY slot_name
            """,
            (binding_key,),
        )
        slots = cur.fetchall()
        cur.execute(
            """
            SELECT a.*, acct.username AS actor_username
            FROM workbench_audit_log a
            LEFT JOIN workbench_account acct ON acct.id = a.account_id
            WHERE a.target_type = 'customer_memory_slot'
              AND a.details ->> 'binding_key' = %s
            ORDER BY a.created_at DESC
            """,
            (binding_key,),
        )
        audit_rows = cur.fetchall()
        # 0.0.5 S22 (FR-34a): the memory-health strip's last-injection recency.
        # Same cursor, same read -- no new table and no second connection on a
        # read the supervisor already waits for.
        injected_at = last_injection_at(cur, binding_key)
    return {
        "binding_key": binding_key,
        "slots": [serialize_row(r) for r in slots],
        "audit": [serialize_row(r) for r in audit_rows],
        "last_injection_at": injected_at,
    }


def memory_handlers() -> dict[str, dict[str, Any]]:
    """Registry fragment for the Customer Memory datastore tool."""
    return {
        "toee_customer_memory": {
            "upsert_preference": _upsert_preference,
            "clear_preference": _clear_preference,
            "erase_customer_memory": _erase_customer_memory,
            "get_preferences": _get_preferences,
            "get_my_memory_summary": _get_my_memory_summary,
            "dismiss_proposal": _dismiss_proposal,
            "get_memory_audit": _get_memory_audit,
        }
    }
