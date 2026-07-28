"""Postgres handler for ``toee_semantic_lexicon`` (0.0.5 S01, FR-1/FR-3).

L7 "the domain language the business speaks" -- mirrors the L6 governance
skeleton (``handlers/agent_experience.py``) for a NEW governed table in the Toee
Business Datastore (ADR-0140). Proposals persist with ``status='proposed'``
directly: the propose/confirm gate is status-based, so a proposed row is inert
until an admin flips it (S02), and nothing APPLIES a lexicon entry until
S03/S05/S06.

Every validator, the split write scan, and the provenance resolver are imported
from the mock twin's module -- ONE resolver, both twins (NFR-7, the S15/S21
lesson), so the two paths cannot drift on what a governed rejection is or on how
provenance is derived.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from psycopg import errors as psycopg_errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from toee_hermes.drivers.mock.semantic_lexicon import (
    LEXICON_DECISIONS,
    LEXICON_EDITABLE_STATUSES,
    duplicate_entry_error,
    lexicon_provenance_unattributed,
    missing_entry_error,
    not_editable_error,
    read_lexicon_decision,
    read_lexicon_edit,
    read_lexicon_filters,
    read_lexicon_proposal,
    resolve_lexicon_decision_authorization,
    resolve_manual_add_provenance,
)

from ._common import insert_audit, new_id, serialize_row

if TYPE_CHECKING:  # pragma: no cover - typing only
    from toee_hermes.tool_gate import ToolExecutionContext

_ENTRY_COLUMNS = (
    "id, domain, entry_kind, surface_form, canonical_form, status, provenance, "
    "evidence, proposer_context, pii_redacted, decider_account_id, decided_at, "
    "hit_count, created_at, updated_at"
)


def _insert_lexicon_entry(
    conn,
    params: dict[str, Any],
    context: "ToolExecutionContext",
    *,
    status: str,
    decider: Optional[str],
    audit_action: str,
) -> tuple[str, dict[str, Any]]:
    """The shared INSERT behind ``propose_lexicon_entry`` and ``add_lexicon_entry``.

    Both write the same row through the same validation and the same D2 split
    write scan; they differ only in the status the row lands in and whether a
    decider rides along. Being an admin is not an exemption from the injection
    guard -- it is the reason the guard has to be in ONE place.

    ``decided_at`` comes from the same ``now()`` as ``created_at`` for an
    admin-added row: created and decided are one act there.
    """
    # Validation + the split write scan + the framework-derived provenance all
    # run BEFORE the INSERT, so rejected content never reaches the table.
    fields = read_lexicon_proposal(params, context)
    entry_id = new_id("lex")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO semantic_lexicon
                    (id, domain, entry_kind, surface_form, canonical_form, status,
                     provenance, evidence, proposer_context, pii_redacted,
                     decider_account_id, decided_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        CASE WHEN %s::text IS NULL THEN NULL ELSE now() END)
                """,
                (
                    entry_id,
                    fields["domain"],
                    fields["entry_kind"],
                    fields["surface_form"],
                    fields["canonical_form"],
                    status,
                    fields["provenance"],
                    fields["evidence"],
                    Jsonb(fields["proposer_context"] or {}),
                    fields["pii_redacted"],
                    decider,
                    decider,
                ),
            )
    except psycopg_errors.UniqueViolation:
        # UNIQUE(domain, surface_form) -- a governed `conflict`, the same class
        # and message the mock twin raises, mapped to 409 by the workbench BFF.
        raise duplicate_entry_error(fields["domain"], fields["surface_form"]) from None
    insert_audit(
        conn,
        profile=context.profile,
        account_id=decider or context.user_id,
        action=audit_action,
        target_type="semantic_lexicon",
        target_id=entry_id,
        details={
            "domain": fields["domain"],
            "entry_kind": fields["entry_kind"],
            "surface_form": fields["surface_form"],
            "provenance": fields["provenance"],
            "status": status,
            "pii_redacted": fields["pii_redacted"],
            # A WAIVED redaction, named (S01 review finding 2). The keep
            # exemption exists so an entry's own digit-shaped forms survive in
            # its evidence, but a model-supplied surface_form gets no PII scan,
            # so the waiver must not be silent. Spans here equal this entry's
            # own forms -- `surface_form` is already in these details, so this
            # records the fact of the waiver, not a new class of data.
            "pii_keep_exempt": list(fields["pii_keep_exempt"]),
        },
    )
    return entry_id, fields


def _propose_lexicon_entry(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    entry_id, fields = _insert_lexicon_entry(
        conn,
        params,
        context,
        status="proposed",
        decider=None,
        audit_action="lexicon_entry_proposed",
    )
    return {
        "id": entry_id,
        "domain": fields["domain"],
        "entry_kind": fields["entry_kind"],
        "surface_form": fields["surface_form"],
        "canonical_form": fields["canonical_form"],
        "status": "proposed",
        "provenance": fields["provenance"],
        "pii_redacted": fields["pii_redacted"],
        "pii_keep_exempt": fields["pii_keep_exempt"],
        "proposed": True,
    }


def _add_lexicon_entry(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    """FR-8/US1: an admin adds ``TOEE = TOEE TIRE`` and it is LIVE, no deploy.

    The admin IS the gate, so there is no proposal step: the row lands
    ``confirmed`` with the adding admin as its decider and ``admin_manual``
    provenance -- which, per D20, is only derivable on the deterministic admin
    route with an attributed actor. Both gates run before the INSERT.
    """
    decider = resolve_lexicon_decision_authorization(context)
    resolve_manual_add_provenance(context)
    entry_id, fields = _insert_lexicon_entry(
        conn,
        params,
        context,
        status="confirmed",
        decider=decider,
        audit_action="lexicon_entry_added",
    )
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT {_ENTRY_COLUMNS} FROM semantic_lexicon WHERE id = %s", (entry_id,)
        )
        row = cur.fetchone()
    return {
        **serialize_row(row),
        "pii_keep_exempt": fields["pii_keep_exempt"],
        "added": True,
    }


def _decide_lexicon_entry(
    conn, params: dict[str, Any], context: "ToolExecutionContext", *, action: str
) -> Any:
    """Shared UPDATE for confirm/reject/retire (0.0.5 S02, FR-3 decide side).

    ONE code path for all three governed decisions -- only the row of
    ``LEXICON_DECISIONS`` differs, and that table is imported from the mock
    twin's module, so the two twins cannot drift on which transitions exist
    (NFR-7). The ``resolve_lexicon_decision_authorization`` gate runs BEFORE the
    row lookup, so a missing actor is ``policy_blocked`` regardless of ``id``.

    ``UPDATE ... WHERE status = <from_status>`` is the idempotency floor, exactly
    the ``_decide_experience`` shape: only a row in the expected state
    transitions. A missing id is a governed ``not_found``; a row in any other
    state is a safe no-op returning its current row -- which is also what stops
    ``retire`` from reaching a ``proposed`` entry (a proposal is rejected, never
    retired) and what stops a redelivered decision from re-attributing a row or
    writing a second audit row.
    """
    from_status, to_status, audit_action = LEXICON_DECISIONS[action]
    entry_id, decider = read_lexicon_decision(params, context)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            UPDATE semantic_lexicon
            SET status = %s, decider_account_id = %s, decided_at = now(),
                updated_at = now()
            WHERE id = %s AND status = %s
            RETURNING {_ENTRY_COLUMNS}
            """,
            (to_status, decider, entry_id, from_status),
        )
        row = cur.fetchone()
    if row is None:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"SELECT {_ENTRY_COLUMNS} FROM semantic_lexicon WHERE id = %s",
                (entry_id,),
            )
            existing = cur.fetchone()
        if existing is None:
            raise missing_entry_error(entry_id)
        return serialize_row(existing)
    insert_audit(
        conn,
        profile=context.profile,
        account_id=decider,
        action=audit_action,
        target_type="semantic_lexicon",
        target_id=entry_id,
        details={"status": to_status},
    )
    return serialize_row(row)


def _edit_lexicon_entry(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    """D7: an IN-PLACE UPDATE of the mapping. The entry id is STABLE.

    The either/or the brief once offered is withdrawn, and this is the half that
    matters against a real table: an edited entry is the SAME row. S09's
    ``entry_ref``, S10's blast-radius join and S26's per-entry health score all
    key on the id, and ``hit_count`` is the rollup's accumulated evidence of use
    -- a typo fix must not reset any of them. ``status``/``decider_account_id``/
    ``decided_at`` are untouched too: an edit is not a decision, and WHO edited
    is recorded on the ``old -> new`` audit row rather than by overwriting who
    decided. Retire-then-add stays available as the different admin intent.

    ``UNIQUE(domain, surface_form)`` is respected rather than dodged: an edit
    that moves a surface form onto another row's is the same governed
    ``conflict`` a colliding proposal gets.
    """
    entry_id, editor, changes = read_lexicon_edit(params, context)
    assignments = ", ".join(f"{field} = %s" for field in changes)
    with conn.cursor(row_factory=dict_row) as cur:
        # Lock the row and read the OLD values in the same statement the update
        # will use, so the audit row's `old` cannot be a value some concurrent
        # edit already replaced.
        cur.execute(
            f"SELECT {_ENTRY_COLUMNS} FROM semantic_lexicon WHERE id = %s FOR UPDATE",
            (entry_id,),
        )
        before = cur.fetchone()
        if before is None:
            raise missing_entry_error(entry_id)
        if before["status"] not in LEXICON_EDITABLE_STATUSES:
            raise not_editable_error(entry_id, before["status"])
        try:
            cur.execute(
                f"""
                UPDATE semantic_lexicon
                SET {assignments}, updated_at = now()
                WHERE id = %s
                RETURNING {_ENTRY_COLUMNS}
                """,
                (*changes.values(), entry_id),
            )
        except psycopg_errors.UniqueViolation:
            raise duplicate_entry_error(
                before["domain"], changes.get("surface_form", before["surface_form"])
            ) from None
        row = cur.fetchone()
    insert_audit(
        conn,
        profile=context.profile,
        account_id=editor,
        action="lexicon_entry_edited",
        target_type="semantic_lexicon",
        target_id=entry_id,
        details={
            "old": {field: before[field] for field in changes},
            "new": dict(changes),
        },
    )
    return serialize_row(row)


def _list_lexicon_entries(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    """Admin-only read of the ``semantic_lexicon`` (FR-1/FR-8).

    Never registered as an LLM-callable tool (``_AGENT_EXCLUDED_ACTIONS``, the
    ``list_agent_experience`` precedent) -- reached only from the admin BFF's
    deterministic ``tools:dispatch`` call. S02 EXTENDED this one action with the
    console's queue filters rather than adding a second read, so the queue and
    the CRUD list are the same governed surface.

    ``provenance_unattributed`` is derived per row by the same shared helper the
    mock twin uses: an ``admin_manual`` claim with nobody attached (possible only
    for rows written between S01 and S02, before D20 closed the hole) must not
    render indistinguishably from one a named admin actually made.
    """
    status, domain = read_lexicon_filters(params)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT {_ENTRY_COLUMNS} FROM semantic_lexicon
            WHERE (%s::text IS NULL OR status = %s)
              AND (%s::text IS NULL OR domain = %s)
            ORDER BY created_at DESC
            """,
            (status, status, domain, domain),
        )
        rows = cur.fetchall()
        # MAX(updated_at) over the WHOLE table -- monotonic, filter-independent,
        # and no column to migrate. See the mock twin's _confirmed_set_version.
        cur.execute("SELECT max(updated_at) AS version FROM semantic_lexicon")
        version = cur.fetchone()["version"]
    return {
        "entries": [
            {
                **serialize_row(r),
                "provenance_unattributed": lexicon_provenance_unattributed(r),
            }
            for r in rows
        ],
        "confirmed_set_version": version.isoformat() if version else None,
    }


def semantic_lexicon_handlers() -> dict[str, dict[str, Any]]:
    """Registry fragment for the L7 Semantic Lexicon datastore tool."""
    return {
        "toee_semantic_lexicon": {
            "propose_lexicon_entry": _propose_lexicon_entry,
            "list_lexicon_entries": _list_lexicon_entries,
            "add_lexicon_entry": _add_lexicon_entry,
            "edit_lexicon_entry": _edit_lexicon_entry,
            "confirm_lexicon_entry": lambda conn, p, c: _decide_lexicon_entry(
                conn, p, c, action="confirm_lexicon_entry"
            ),
            "reject_lexicon_entry": lambda conn, p, c: _decide_lexicon_entry(
                conn, p, c, action="reject_lexicon_entry"
            ),
            "retire_lexicon_entry": lambda conn, p, c: _decide_lexicon_entry(
                conn, p, c, action="retire_lexicon_entry"
            ),
        }
    }
