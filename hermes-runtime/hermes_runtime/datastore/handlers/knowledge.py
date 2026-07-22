"""Datastore handlers for ``toee_knowledge_ops`` (ADR-0003/0087/0145).

The Supervisor Admin ``/admin/knowledge`` master-detail (ADR-0087) authors the six
Required Operational Policy Slots (ADR-0003) with a draft -> pending_eval ->
published lifecycle, separate draft/published text, owner/review metadata, and a
published-version history for rollback. ADR-0145 cuts this over from the in-memory
``KnowledgeStore`` (the behavioral source of truth) onto a dedicated
``workbench_policy_slot`` (+ ``workbench_policy_slot_history``) table that mirrors
its ``PolicySlot`` shape field-for-field. Writes are Supervisor governance: each is
fail-closed on an attributed actor and appends a Workbench Audit Log row.

ADR-0145 left ``submit`` decoupled from any publish step; ADR-0146 connects them:
promoting a ``policy_publish`` eval run now publishes the matching authoring slot
(``eval_review._publish_authoring_slot``), pushing the prior ``published_text`` onto
``workbench_policy_slot_history`` so :func:`_rollback_published_policy` has data. The
old ``knowledge_version`` publish path is retired (promotion is runId-keyed now).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from psycopg.rows import dict_row

from toee_hermes.errors import ToolDriverError

from ._common import insert_audit, read_string, serialize_row

if TYPE_CHECKING:  # pragma: no cover - typing only
    from toee_hermes.tool_gate import ToolExecutionContext

# The wire-safe PolicySlot read model the BFF maps onto camelCase (ADR-0145).
_SLOT_COLUMNS = (
    "slot_id, title, status, draft_text, published_text, owner, review_date, has_gap_prompt"
)


def _require_actor(context: "ToolExecutionContext") -> str:
    """The acting Supervisor Admin for a governed knowledge write, or a denial.

    KnowledgeOps mutations are actor-attributed governance (ADR-0029/0087/0141):
    the actor rides ``ToolExecutionContext.user_id``, asserted by the BFF under the
    shared bearer. Trusting an absent actor would write the mutation *and* a
    NULL-actor audit row while returning success. Fail closed so every knowledge
    write handler is protected at once. (Mirrors ``accounts._require_actor``.)
    """
    actor = context.user_id
    if not actor:
        raise ToolDriverError(
            "policy_blocked", "A governed knowledge write requires an attributed actor."
        )
    return actor


def _optional_str(params: dict[str, Any], *keys: str) -> Optional[str]:
    """First *provided* string among ``keys`` (snake-first), keeping ``""``.

    Unlike ``read_string`` (which drops empty strings), this distinguishes an
    explicitly-provided empty string from an absent key, so ``saveDraft`` parity
    holds: sending ``draftText: ""`` clears the draft, while omitting it leaves the
    stored value untouched (``COALESCE(NULL, col)``).
    """
    for key in keys:
        value = params.get(key)
        if isinstance(value, str):
            return value
    return None


def _slot_row(conn, slot_id: str) -> Any:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT {_SLOT_COLUMNS} FROM workbench_policy_slot WHERE slot_id = %s",
            (slot_id,),
        )
        return serialize_row(cur.fetchone())


def _get_policy_slots(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    # listSlots() parity: every Required Operational Policy Slot, in the fixed
    # ADR-0003 list order (sort_order). A read -> no actor required, no audit.
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT {_SLOT_COLUMNS} FROM workbench_policy_slot ORDER BY sort_order"
        )
        rows = cur.fetchall()
    return {"slots": [serialize_row(row) for row in rows]}


def _update_policy_slot(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    # saveDraft parity: patch only the provided fields and flip empty/gap -> draft
    # when the resulting draft text is non-empty, atomically in one UPDATE. An
    # unknown slot id is not_found (BFF -> 404), store-path parity.
    actor = _require_actor(context)
    slot_id = read_string(params, "slot_id", "slotId", "slot")
    if slot_id is None:
        raise ToolDriverError("unexpected_error", "slot_id is required.")
    fields = {
        "slot_id": slot_id,
        "draft_text": _optional_str(params, "draft_text", "draftText"),
        "owner": _optional_str(params, "owner"),
        "review_date": _optional_str(params, "review_date", "reviewDate"),
    }
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            UPDATE workbench_policy_slot SET
                draft_text = COALESCE(%(draft_text)s, draft_text),
                owner = COALESCE(%(owner)s, owner),
                review_date = COALESCE(%(review_date)s, review_date),
                status = CASE
                    WHEN COALESCE(%(draft_text)s, draft_text) IS NOT NULL
                         AND length(COALESCE(%(draft_text)s, draft_text)) > 0
                         AND status IN ('empty', 'gap')
                    THEN 'draft'
                    ELSE status
                END,
                updated_at = now()
            WHERE slot_id = %(slot_id)s
            RETURNING {_SLOT_COLUMNS}
            """,
            fields,
        )
        row = cur.fetchone()
    if row is None:
        raise ToolDriverError("not_found", "slot not found")
    insert_audit(
        conn,
        profile=context.profile,
        account_id=actor,
        action="update_policy_slot",
        target_type="policy_slot",
        target_id=slot_id,
        details={"status": row["status"]},
    )
    return {"slot": serialize_row(row)}


def _submit_for_eval(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    # submitForEval parity: requires a non-empty draft. The atomic UPDATE only
    # matches a slot that has one; rowcount 0 is disambiguated into not_found (404,
    # unknown slot) vs conflict (409, "slot has no draft to submit").
    actor = _require_actor(context)
    slot_id = read_string(params, "slot_id", "slotId", "slot")
    if slot_id is None:
        raise ToolDriverError("unexpected_error", "slot_id is required.")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            UPDATE workbench_policy_slot
            SET status = 'pending_eval', updated_at = now()
            WHERE slot_id = %s AND draft_text IS NOT NULL AND length(draft_text) > 0
            RETURNING {_SLOT_COLUMNS}
            """,
            (slot_id,),
        )
        row = cur.fetchone()
    if row is None:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM workbench_policy_slot WHERE slot_id = %s", (slot_id,))
            exists = cur.fetchone() is not None
        if not exists:
            raise ToolDriverError("not_found", "slot not found")
        raise ToolDriverError("conflict", "slot has no draft to submit")
    insert_audit(
        conn,
        profile=context.profile,
        account_id=actor,
        action="submit_for_eval",
        target_type="policy_slot",
        target_id=slot_id,
        details={},
    )
    return {"slot": serialize_row(row)}


def _rollback_published_policy(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    # rollbackPublished parity: restore the previous published text from history.
    # Unknown slot -> not_found (404); no prior version -> conflict (409). The pop
    # is a single DELETE ... RETURNING so two concurrent rollbacks can't both claim
    # the same history row.
    actor = _require_actor(context)
    slot_id = read_string(params, "slot_id", "slotId", "slot")
    if slot_id is None:
        raise ToolDriverError("unexpected_error", "slot_id is required.")
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM workbench_policy_slot WHERE slot_id = %s", (slot_id,))
        if cur.fetchone() is None:
            raise ToolDriverError("not_found", "slot not found")
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM workbench_policy_slot_history
            WHERE id = (
                SELECT id FROM workbench_policy_slot_history
                WHERE slot_id = %s
                ORDER BY archived_at DESC, id DESC
                LIMIT 1
            )
            RETURNING published_text
            """,
            (slot_id,),
        )
        popped = cur.fetchone()
    if popped is None:
        raise ToolDriverError("conflict", "slot has no previous published version")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE workbench_policy_slot"
            " SET published_text = %s, status = 'published', updated_at = now()"
            " WHERE slot_id = %s",
            (popped[0], slot_id),
        )
    insert_audit(
        conn,
        profile=context.profile,
        account_id=actor,
        action="rollback_published_policy",
        target_type="policy_slot",
        target_id=slot_id,
        details={},
    )
    return {"slot": _slot_row(conn, slot_id)}


# The eval publish-gate that promotion now drives lives on workbench_policy_slot
# (ADR-0146): a promoted policy_publish eval run publishes the matching authoring
# slot via eval_review._publish_authoring_slot, pushing the prior published text to
# workbench_policy_slot_history. The old knowledge_version publish path
# (publish_pending_slot/_latest_version/_require_known_slot) is retired — promotion
# is runId-keyed now (ADR-0146 resolves ADR-0145 divergences #1/#2).


# --- corpus status (S11, FR-6) -----------------------------------------------
# Unlike every write above, this read is CROSS-DATABASE: workbench_policy_slot
# lives on the business datastore (the ``conn`` the registry hands the handler),
# but the corpus itself (``knowledge_chunk``) lives on the SEPARATE toee_knowledge
# database (S-ISO isolation invariant, hermes_runtime/knowledge/config.py). So
# _get_corpus_status ignores the business ``conn`` and opens its own short-lived
# read-only connection to the knowledge DSN.


def _corpus_status_from_conn(kconn) -> Any:
    """Doc/chunk counts + last-ingest time + per-type breakdown from an OPEN
    connection to the knowledge database. Pure read (no writes, no commit) --
    the injectable core so tests can point it at a throwaway knowledge schema
    (mirrors the S08 retriever's ``retrieve(conn=...)`` seam)."""
    with kconn.cursor() as cur:
        cur.execute(
            "SELECT count(*), count(DISTINCT page_id), max(created_at) FROM knowledge_chunk"
        )
        chunk_count, doc_count, last_ingest_at = cur.fetchone()
        cur.execute(
            "SELECT page_type, count(*) FROM knowledge_chunk"
            " GROUP BY page_type ORDER BY page_type"
        )
        by_type = cur.fetchall()
    return {
        "doc_count": doc_count or 0,
        "chunk_count": chunk_count or 0,
        "last_ingest_at": last_ingest_at.isoformat() if last_ingest_at else None,
        "by_type": [{"page_type": pt, "count": n} for pt, n in by_type],
    }


def _last_ingest_job(conn) -> Any:
    """The most recent ``ingest`` job's status, for the panel's readback (S04).

    Unlike the corpus counts above this IS a business-database read -- the ``job``
    table lives there -- so it uses the handler's own ``conn``. ``None`` when no
    re-ingest has ever been queued, and ``None`` (not an error) on a database that
    predates migration 0011, so an un-migrated deployment still renders the panel.
    """
    # Local import: job_queue reaches back into datastore.handlers._common for
    # new_id, so a module-level import here would be a cycle.
    from hermes_runtime.job_queue import INGEST_JOB_TYPE

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, status, attempts, last_error, created_at, updated_at"
                " FROM job WHERE type = %s ORDER BY created_at DESC LIMIT 1",
                (INGEST_JOB_TYPE,),
            )
            row = cur.fetchone()
    except Exception:
        return None
    if row is None:
        return None
    job_id, status, attempts, last_error, created_at, updated_at = row
    return {
        "job_id": job_id,
        "status": status,
        "attempts": attempts,
        "last_error": last_error,
        "queued_at": created_at.isoformat() if created_at else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
    }


def _get_corpus_status(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    # A read -> no actor required, no audit (parity with the other knowledge
    # reads above).
    del params, context
    from hermes_runtime.knowledge.pool import get_knowledge_pool

    with get_knowledge_pool().connection() as kconn:
        status = _corpus_status_from_conn(kconn)
    # S04 (FR-11): the re-ingest panel's status readback. Cross-database again --
    # the counts came from toee_knowledge, the job row from the business `conn`.
    status["last_ingest_job"] = _last_ingest_job(conn) if conn is not None else None
    return status


def _enqueue_corpus_reingest(
    conn, params: dict[str, Any], context: "ToolExecutionContext"
) -> Any:
    """Queue an ``ingest`` job for the background worker (0.0.4 S04, FR-11).

    Replaces 0.0.3 S11's display-only stub (the panel printed a CLI command). A
    governed WRITE: it triggers a TRUNCATE-and-reload of the whole corpus, so it
    is dispatchWrite/fail-closed on the acting supervisor and writes a
    ``corpus_reingest_queued`` audit row -- the sibling precedent is
    ``trigger_retention_sweep``'s own audit row.

    ponytail: ``max_attempts=1``. Ingest is a heavy, non-idempotent-in-cost
    TRUNCATE + re-embed of the whole corpus; three automatic attempts would wipe
    and reload it three times over a transient fastembed/OOM failure. A failed
    ingest goes straight to ``dead`` for S05's governed replay instead. Raise it
    only if ingest ever becomes cheap and resumable **and** the lease is solved
    first: an ingest that outlives ``job_queue.DEFAULT_LEASE_SECONDS`` (300 s) is
    reclaimed mid-run, and that is harmless today ONLY because
    ``attempts >= max_attempts`` sends the reclaimed row to ``dead`` (never
    claimable) rather than back to ``failed``. Above 1, a reclaimed-but-still-
    running ingest becomes claimable again and two processes TRUNCATE the corpus
    concurrently -- so chunking ingest into cheap resumable pieces satisfies the
    first half of this condition while leaving that hazard fully intact.
    """
    del params
    from hermes_runtime.job_queue import INGEST_JOB_TYPE, insert_job

    _require_actor(context)
    with conn.cursor() as cur:
        job_id, _created = insert_job(
            cur,
            {"profile": context.profile, "actor_account_id": context.user_id},
            job_type=INGEST_JOB_TYPE,
            max_attempts=1,
        )
    insert_audit(
        conn,
        profile=context.profile,
        account_id=context.user_id,
        action="corpus_reingest_queued",
        target_type="knowledge_chunk",
        target_id=job_id,
        details={"job_id": job_id},
    )
    return {"job_id": job_id, "status": "queued"}


def knowledge_handlers() -> dict[str, dict[str, Any]]:
    """Registry fragment for the knowledge-ops datastore tool."""
    return {
        "toee_knowledge_ops": {
            "get_policy_slots": _get_policy_slots,
            "update_policy_slot": _update_policy_slot,
            "submit_for_eval": _submit_for_eval,
            "rollback_published_policy": _rollback_published_policy,
            "get_corpus_status": _get_corpus_status,
            "enqueue_corpus_reingest": _enqueue_corpus_reingest,
        }
    }
