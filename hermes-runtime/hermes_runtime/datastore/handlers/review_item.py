"""Postgres handler for ``toee_review_inbox`` (0.0.5 S15, FR-22).

The unified review inbox's own store. Mirrors the L7 governance skeleton
(``handlers/semantic_lexicon.py``) for a NEW governed table in the Toee Business
Datastore (ADR-0140) -- see ``migrations/0022_review_item.sql`` for why the table
exists at all.

Every validator, vocabulary and gate is imported from the mock twin's module --
ONE resolver, both twins (NFR-7, the S15-0.0.4/S21-0.0.4 lesson), so the two
paths cannot drift on what a governed rejection is.

Re-classify dispatches to the L6 and L7 handler fragments' OWN governed actions
rather than reimplementing either, which is what FR-22's "no new decision
primitives" means in practice -- and it is the same wiring the mock twin gets by
being handed those fragments. Both writes ride the single transaction
``PostgresDriver.execute`` opens, so a target that collides on
``UNIQUE(domain, surface_form)`` rolls the source's rejection back with it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from toee_hermes.blast_radius import blast_radius_result, read_blast_radius_query
from toee_hermes.drivers.mock.review_item import (
    REVIEW_ITEM_STATUS_OPEN,
    missing_item_error,
    read_annotation_request,
    read_reclassification,
    read_review_item_decision,
    read_review_item_emission,
    read_review_item_filters,
    reclassification_result,
    reclassified_target_params,
    require_pending_source,
    resolve_review_item_emitter,
)
from toee_hermes.errors import ToolDriverError

from .agent_experience import agent_experience_handlers
from .semantic_lexicon import semantic_lexicon_handlers
from ._common import insert_audit, new_id, serialize_row

if TYPE_CHECKING:  # pragma: no cover - typing only
    from toee_hermes.tool_gate import ToolExecutionContext

_ITEM_COLUMNS = (
    "id, kind, subject_ref, evidence, annotations, status, "
    "decider_account_id, decided_at, created_at, updated_at"
)


def _propose_review_item(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    """The EMISSION seam S10 / S20 / S25 write through. Propose-only, no actor.

    ``ON CONFLICT DO NOTHING`` against the partial unique index
    (``review_item_open_subject_idx``) is the idempotence: a scheduled sweep that
    re-raises a still-open subject gets the existing row back rather than a
    second copy, and no second audit row. Once the item has been decided the
    index no longer covers it, so the same subject CAN be raised again -- which
    is the intended behaviour, not a leak (see the migration).
    """
    resolve_review_item_emitter(context)
    fields = read_review_item_emission(params)
    item_id = new_id("rvw")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            INSERT INTO review_item (id, kind, subject_ref, evidence)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING {_ITEM_COLUMNS}
            """,
            (
                item_id,
                fields["kind"],
                fields["subject_ref"],
                Jsonb(fields["evidence"]),
            ),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                f"""
                SELECT {_ITEM_COLUMNS} FROM review_item
                WHERE kind = %s AND subject_ref = %s AND status = %s
                """,
                (fields["kind"], fields["subject_ref"], REVIEW_ITEM_STATUS_OPEN),
            )
            existing = cur.fetchone()
            if existing is None:
                # The insert conflicted with a row this transaction then could
                # not see. Reported rather than swallowed: silently returning
                # "nothing happened" would let an emitter believe it had raised
                # an item it had not.
                raise ToolDriverError(
                    "conflict",
                    f'review_item emission for "{fields["kind"]}" / '
                    f'"{fields["subject_ref"]}" conflicted with a row that is no '
                    "longer open; retry.",
                )
            return {**serialize_row(existing), "proposed": False}
    insert_audit(
        conn,
        profile=context.profile,
        # An emission carries whatever actor its caller had -- usually none, and
        # that is correct: the audit row records that a SWEEP raised this, and
        # inventing an account for it would be worse than a NULL.
        account_id=context.user_id,
        action="review_item_proposed",
        target_type="review_item",
        target_id=item_id,
        details={"kind": fields["kind"], "subject_ref": fields["subject_ref"]},
    )
    return {**serialize_row(row), "proposed": True}


def _list_review_items(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    """Admin-only read of the ``review_item`` store (FR-22).

    Never registered as an LLM-callable tool (``_AGENT_EXCLUDED_ACTIONS``, the
    ``list_agent_experience`` precedent). ``open_count`` is the inbox badge for
    THIS store's share of the queue and is deliberately computed unfiltered: the
    badge answers "how many decisions are waiting", not "how many rows the
    current filter happens to show".
    """
    status, kind = read_review_item_filters(params)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT {_ITEM_COLUMNS} FROM review_item
            WHERE (%s::text IS NULL OR status = %s)
              AND (%s::text IS NULL OR kind = %s)
            ORDER BY created_at DESC
            """,
            (status, status, kind, kind),
        )
        rows = cur.fetchall()
        cur.execute(
            "SELECT count(*) AS open FROM review_item WHERE status = %s",
            (REVIEW_ITEM_STATUS_OPEN,),
        )
        open_count = cur.fetchone()["open"]
    return {"items": [serialize_row(r) for r in rows], "open_count": open_count}


def _decide_review_item(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    """Acknowledge or dismiss ONE row of this store, attributed and audited.

    ``UPDATE ... WHERE status = 'open'`` is the idempotency floor, exactly the
    ``_decide_lexicon_entry`` shape: a redelivered decision finds the row already
    decided and is a safe no-op that neither re-attributes it nor writes a second
    audit row. The actor gate runs inside ``read_review_item_decision``, BEFORE
    the row lookup, so a missing actor is ``policy_blocked`` regardless of ``id``.
    """
    item_id, decision, audit_action, decider = read_review_item_decision(
        params, context
    )
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            UPDATE review_item
            SET status = %s, decider_account_id = %s, decided_at = now(),
                updated_at = now()
            WHERE id = %s AND status = %s
            RETURNING {_ITEM_COLUMNS}
            """,
            (decision, decider, item_id, REVIEW_ITEM_STATUS_OPEN),
        )
        row = cur.fetchone()
    if row is None:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"SELECT {_ITEM_COLUMNS} FROM review_item WHERE id = %s", (item_id,)
            )
            existing = cur.fetchone()
        if existing is None:
            raise missing_item_error(item_id)
        return serialize_row(existing)
    insert_audit(
        conn,
        profile=context.profile,
        account_id=decider,
        action=audit_action,
        target_type="review_item",
        target_id=item_id,
        details={"status": decision},
    )
    return serialize_row(row)


def _reclassify_proposal(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    """FR-22's Re-classify: reject-in-source + propose-in-target, ONE action.

    Three audit rows come out of it, and all three are the point: the source
    layer's own ``agent_experience_rejected``, the target layer's own
    ``lexicon_entry_proposed``, and a ``review_item_reclassified`` row that is the
    only place the two ids are linked. That link cannot live on the L7 row
    itself -- see ``reclassified_target_params`` for why a Postgres id in a
    PII-scanned field is a breadcrumb that gets mangled two times in five.

    ``FOR UPDATE`` locks the source before its status is checked, so two admins
    re-classifying the same proposal cannot both pass ``require_pending_source``.
    """
    source_kind, target_kind, source_id, actor = read_reclassification(params, context)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id, status, content, proposer_context FROM agent_experience "
            "WHERE id = %s FOR UPDATE",
            (source_id,),
        )
        source_row = require_pending_source(serialize_row(cur.fetchone()), source_id)

    # The layers' OWN governed actions, reached through their registry fragments
    # rather than by importing private handlers -- the same shape the mock twin
    # is handed. Each writes its own attribution, scan and audit row.
    rejected = agent_experience_handlers()["toee_agent_experience"][
        "reject_experience"
    ](conn, {"id": source_id}, context)
    target = semantic_lexicon_handlers()["toee_semantic_lexicon"][
        "propose_lexicon_entry"
    ](conn, reclassified_target_params(params, source_row), context)

    result = reclassification_result(source_kind, target_kind, rejected, target)
    insert_audit(
        conn,
        profile=context.profile,
        account_id=actor,
        action="review_item_reclassified",
        target_type="agent_experience",
        target_id=source_id,
        details=result["reclassified"],
    )
    return result


def _get_blast_radius(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    """Admin-only read: which turns/cases did this entry reach? (0.0.5 S10, FR-12).

    Never registered as an LLM-callable tool (``_AGENT_EXCLUDED_ACTIONS``, the
    ``get_memory_audit`` precedent) -- it reports across CUSTOMERS, which is not
    a view any live turn may reach.

    It sits on this tool rather than on the three layer tools because the answer
    is layer-generic (one ledger query serves L4 slots, L6 notes and L7 entries)
    and because the ``blast_radius`` review item it justifies lives in this
    store. The item carries counts; this carries the case list, live -- see
    :mod:`toee_hermes.blast_radius` for why the item deliberately does not
    freeze one.
    """
    from ...blast_radius import affected_cases

    layer, entry_ref, since = read_blast_radius_query(params)
    return blast_radius_result(
        affected_cases(conn, layer=layer, entry_ref=entry_ref, since=since),
        layer=layer,
        entry_ref=entry_ref,
        since=since,
    )


def _annotate_inbox_item(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    """Re-run copilot triage over ONE inbox item (0.0.5 S16, FR-23).

    The on-demand half of FR-23, behind the inbox's per-item button. Its twin is
    the scheduled ``copilot_triage`` job, and both go through the SAME
    :func:`~hermes_runtime.copilot_triage.annotate_one` -- there is exactly one
    code path in the system that writes an annotation, which is what makes "the
    annotation write is the only write" checkable rather than asserted.

    Synchronous rather than an enqueue, the ``reprobe_now`` precedent (0.0.4
    S17): an admin pressing "Re-triage" wants the note refreshed NOW rather than
    on the next scheduled cycle, and the response carries the fresh annotation so
    the row can re-render without a poll.

    Never registered as an LLM-callable tool (``_AGENT_EXCLUDED_ACTIONS``), and
    for a sharper reason than the sibling reads: this action is the seam that
    puts stored queue text in front of a model, so the model on the far side of
    it must not be able to reach back through the tool surface. D24 records why
    the eval suite could not be the instrument here.
    """
    from ...copilot_triage import annotate_one

    kind, item_id, _table = read_annotation_request(params)
    return annotate_one(conn, kind=kind, item_id=item_id, context=context)


def review_item_handlers() -> dict[str, dict[str, Any]]:
    """Registry fragment for the unified review inbox's datastore tool."""
    return {
        "toee_review_inbox": {
            "propose_review_item": _propose_review_item,
            "list_review_items": _list_review_items,
            "decide_review_item": _decide_review_item,
            "reclassify_proposal": _reclassify_proposal,
            "get_blast_radius": _get_blast_radius,
            "annotate_inbox_item": _annotate_inbox_item,
        }
    }


__all__ = ["review_item_handlers"]
