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

from typing import TYPE_CHECKING, Any

from psycopg import errors as psycopg_errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from toee_hermes.drivers.mock.semantic_lexicon import (
    duplicate_entry_error,
    read_lexicon_proposal,
)

from ._common import insert_audit, new_id, serialize_row

if TYPE_CHECKING:  # pragma: no cover - typing only
    from toee_hermes.tool_gate import ToolExecutionContext

_ENTRY_COLUMNS = (
    "id, domain, entry_kind, surface_form, canonical_form, status, provenance, "
    "evidence, proposer_context, pii_redacted, decider_account_id, decided_at, "
    "hit_count, created_at, updated_at"
)


def _propose_lexicon_entry(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    # Validation + D2's split write scan + the framework-derived provenance all
    # run BEFORE the INSERT, so rejected content never reaches the table.
    fields = read_lexicon_proposal(params, context)
    entry_id = new_id("lex")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO semantic_lexicon
                    (id, domain, entry_kind, surface_form, canonical_form, status,
                     provenance, evidence, proposer_context, pii_redacted)
                VALUES (%s, %s, %s, %s, %s, 'proposed', %s, %s, %s, %s)
                """,
                (
                    entry_id,
                    fields["domain"],
                    fields["entry_kind"],
                    fields["surface_form"],
                    fields["canonical_form"],
                    fields["provenance"],
                    fields["evidence"],
                    Jsonb(fields["proposer_context"] or {}),
                    fields["pii_redacted"],
                ),
            )
    except psycopg_errors.UniqueViolation:
        # UNIQUE(domain, surface_form) -- a governed `conflict`, the same class
        # and message the mock twin raises, mapped to 409 by the workbench BFF.
        raise duplicate_entry_error(fields["domain"], fields["surface_form"]) from None
    insert_audit(
        conn,
        profile=context.profile,
        account_id=context.user_id,
        action="lexicon_entry_proposed",
        target_type="semantic_lexicon",
        target_id=entry_id,
        details={
            "domain": fields["domain"],
            "entry_kind": fields["entry_kind"],
            "surface_form": fields["surface_form"],
            "provenance": fields["provenance"],
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


def _list_lexicon_entries(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    """Admin-only read of every ``semantic_lexicon`` row (FR-1).

    Never registered as an LLM-callable tool (``_AGENT_EXCLUDED_ACTIONS``, the
    ``list_agent_experience`` precedent) -- reached only from the admin BFF's
    deterministic ``tools:dispatch`` call. S02 extends this into the review
    queue with filters; this slice is the unfiltered read.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT {_ENTRY_COLUMNS} FROM semantic_lexicon ORDER BY created_at DESC"
        )
        rows = cur.fetchall()
    return {"entries": [serialize_row(r) for r in rows]}


def semantic_lexicon_handlers() -> dict[str, dict[str, Any]]:
    """Registry fragment for the L7 Semantic Lexicon datastore tool."""
    return {
        "toee_semantic_lexicon": {
            "propose_lexicon_entry": _propose_lexicon_entry,
            "list_lexicon_entries": _list_lexicon_entries,
        }
    }
