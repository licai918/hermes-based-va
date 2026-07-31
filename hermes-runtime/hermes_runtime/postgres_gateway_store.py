"""Postgres-backed GatewayStore (ADR-0107/0115/0140).

Persists accepted inbound turns into the Toee Business Datastore so Workbench
(Tier B) reads the same customer_thread / sms_session / message_turn / cases
rows the dispatch servers use. Wired when ``TOOL_BACKEND=datastore`` (same axis
as the per-profile dispatch servers, ADR-0142).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Optional, Sequence

import psycopg
from psycopg.types.json import Jsonb

from toee_hermes.drivers.mock.memory import MEMORY_SOURCE_MERGED_PROVISIONAL
from toee_hermes.gateway.agent_turn import (
    AgentJobPayload,
    AgentTurnContext,
    build_agent_turn_context,
)
from toee_hermes.gateway.ingress import SessionIdentitySnapshot
from toee_hermes.gateway.normalize import is_email_channel
from toee_hermes.gateway.pipeline import InboundDecision

from .datastore.config import database_url
from .datastore.handlers._common import customer_thread_id, new_id
from .datastore.pool import get_database_pool
from .job_queue import AGENT_TURN_JOB_TYPE, insert_job
from .tool_backend import LEXICON_GLOSSARY_LIMIT

_SMS_CHANNEL = "sms"
_EMAIL_CHANNEL = "email"
# Dev substrate: one conversation maps to one session (ADR-0115).
_SESSION_TTL = "24 hours"

# S25 (FR-25): the confirmed-L6-injection read cap. Confirmed learnings are shared
# operational guidance prepended to every gated turn; cap the count so the prompt
# can't grow unbounded as the store accumulates. Newest-confirmed first (ADR-0152).
_CONFIRMED_EXPERIENCE_LIMIT = 20

# The confirmed-glossary read, shared by both selection strategies (S26) so the
# two can only ever differ in HOW MANY rows come back and in what order -- never
# in which columns the renderer and the ledger see. `hit_count` rides along for
# the health score; every other consumer ignores the extra key.
_CONFIRMED_LEXICON_COLUMNS = (
    "id",
    "domain",
    "entry_kind",
    "surface_form",
    "canonical_form",
    "status",
    "hit_count",
)
_CONFIRMED_LEXICON_SQL = """
SELECT id, domain, entry_kind, surface_form, canonical_form, status, hit_count
FROM semantic_lexicon
WHERE status = 'confirmed'
ORDER BY decided_at DESC NULLS LAST, created_at DESC
"""


def _channel_column(channel: str) -> str:
    """Map the ingress channel to the persisted channel vocabulary (S17).

    ``customer_thread`` / ``session_identity_snapshot`` / ``cases`` / ``identity_link``
    all use ``sms`` | ``email`` (CaseChannel), not the ingress ``simpletexting_sms`` |
    ``simulated_email``. Keeping the column value ``email`` is what makes the copilot
    case view label an email ingress correctly and an Email Sender Match resolve.
    """
    return _EMAIL_CHANNEL if is_email_channel(channel) else _SMS_CHANNEL


def _thread_id(channel: str, from_identity: str) -> str:
    return customer_thread_id(channel, from_identity)


def _session_id(thread_id: str, conversation_id: str) -> str:
    return f"sms_session:{thread_id}:{conversation_id}"


def _turn_id(session_id: str, event_id: str) -> str:
    return f"message_turn:{session_id}:{event_id}"


def _snapshot_to_json(snapshot: SessionIdentitySnapshot) -> dict[str, Any]:
    data: dict[str, Any] = {
        "outcome": snapshot.outcome,
        "resolved_at": snapshot.resolved_at,
    }
    if snapshot.shopify_customer_id:
        data["shopify_customer_id"] = snapshot.shopify_customer_id
    if snapshot.shopify_customer_ids:
        data["shopify_customer_ids"] = list(snapshot.shopify_customer_ids)
    if snapshot.display_name:
        data["company_name"] = snapshot.display_name
    return data


def _snapshot_from_json(data: object, *, fallback_at: str) -> Optional[SessionIdentitySnapshot]:
    if not isinstance(data, dict):
        return None
    outcome = data.get("outcome")
    if not isinstance(outcome, str):
        return None
    resolved_at = data.get("resolved_at") if isinstance(data.get("resolved_at"), str) else fallback_at
    if outcome == "verified_customer":
        shopify_id = data.get("shopify_customer_id")
        display_name = data.get("company_name")
        if not isinstance(display_name, str):
            display_name = data.get("display_name")
        return SessionIdentitySnapshot(
            outcome=outcome,
            resolved_at=resolved_at,
            shopify_customer_id=shopify_id if isinstance(shopify_id, str) else None,
            display_name=display_name if isinstance(display_name, str) else None,
        )
    if outcome == "ambiguous_phone_match":
        ids = data.get("shopify_customer_ids")
        return SessionIdentitySnapshot(
            outcome=outcome,
            resolved_at=resolved_at,
            shopify_customer_ids=list(ids) if isinstance(ids, list) else None,
        )
    return SessionIdentitySnapshot(outcome="unmatched_caller", resolved_at=resolved_at)


class PostgresGatewayStore:
    """Durable GatewayStore backed by the Toee Business Datastore (ADR-0140)."""

    def __init__(
        self,
        *,
        connection: Optional[psycopg.Connection] = None,
        dsn: Optional[str] = None,
    ) -> None:
        if connection is None and dsn is None:
            dsn = database_url()
        self._connection = connection
        self._dsn = dsn

    @contextmanager
    def _connect(self) -> Iterator[psycopg.Connection]:
        if self._connection is not None:
            yield self._connection
        else:
            with get_database_pool(self._dsn).connection() as conn:
                yield conn

    def claim_event(self, event_id: str) -> bool:
        """Atomically claim an event that persists no context; True if first claim.

        ``ON CONFLICT DO NOTHING ... RETURNING`` makes this a compare-and-set, so
        concurrent replays of the same opt-out yield exactly one claim (ADR-0016).
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO inbound_event_claim (event_id) VALUES (%s) "
                    "ON CONFLICT (event_id) DO NOTHING RETURNING event_id",
                    (event_id,),
                )
                claimed = cur.fetchone() is not None
            conn.commit()
            return claimed

    def is_duplicate(self, event_id: str) -> bool:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM agent_turn_context WHERE event_id = %s "
                    "UNION ALL "
                    "SELECT 1 FROM inbound_event_claim WHERE event_id = %s LIMIT 1",
                    (event_id, event_id),
                )
                return cur.fetchone() is not None

    def persist_accepted_inbound(
        self, decision: InboundDecision
    ) -> tuple[AgentTurnContext, bool]:
        """Persist the accepted inbound turn **and its turn job** in one transaction.

        US3 ("a message that arrives while the service crashes runs when it
        returns") is a transaction boundary question, not a retry question. The
        provider gets its 200 the moment this returns; if the ``job`` row were a
        second unit of work, a crash in between would leave a persisted context
        nobody will ever act on -- and the redelivery that was supposed to save it
        never reaches this method, because ``is_duplicate`` sees the context and
        the pipeline short-circuits to ``action="duplicate"`` upstream. So the job
        is written here, inside the same transaction as the ``agent_turn_context``
        row that gates it: either both rows exist or neither does.

        The ``job`` table's SQL still lives in ``job_queue.py``
        (:func:`~hermes_runtime.job_queue.insert_job`) -- this store supplies its
        cursor, never a statement.
        """
        event = decision.event
        if not decision.enqueue or event is None:
            raise ValueError(
                "persist_accepted_inbound requires an accepted (enqueue) decision; "
                f"got action={decision.action!r}."
            )

        channel_col = _channel_column(event.channel)
        thread_id = _thread_id(event.channel, event.from_phone)
        session_id = _session_id(thread_id, event.conversation_id)
        turn_id = _turn_id(session_id, event.event_id)
        body_ref = turn_id

        snapshot = decision.snapshot
        thread_shopify_id: Optional[str] = None
        if snapshot is not None and snapshot.outcome == "verified_customer":
            thread_shopify_id = snapshot.shopify_customer_id

        context_id = new_id("agent_ctx")
        snapshot_id = f"snap:{event.event_id}"

        with self._connect() as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO customer_thread
                            (id, channel, channel_identity, shopify_customer_id,
                             last_interaction_at)
                        VALUES (%s, %s, %s, %s, now())
                        ON CONFLICT (channel, channel_identity) DO UPDATE SET
                            shopify_customer_id = COALESCE(
                                EXCLUDED.shopify_customer_id,
                                customer_thread.shopify_customer_id
                            ),
                            last_interaction_at = now(),
                            updated_at = now()
                        RETURNING id
                        """,
                        (thread_id, channel_col, event.from_phone, thread_shopify_id),
                    )
                    thread_id = cur.fetchone()[0]

                    cur.execute(
                        f"""
                        INSERT INTO sms_session
                            (id, customer_thread_id, opened_at, expires_at)
                        VALUES (%s, %s, now(), now() + interval '{_SESSION_TTL}')
                        ON CONFLICT (id) DO UPDATE SET
                            expires_at = GREATEST(
                                sms_session.expires_at,
                                now() + interval '{_SESSION_TTL}'
                            )
                        """,
                        (session_id, thread_id),
                    )

                    cur.execute(
                        """
                        INSERT INTO message_turn
                            (id, sms_session_id, customer_thread_id, direction,
                             author, body, auto_handled)
                        VALUES (%s, %s, %s, 'inbound', 'customer', %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            turn_id,
                            session_id,
                            thread_id,
                            event.body,
                            not _escalation_case_open(cur, thread_id),
                        ),
                    )

                    if snapshot is not None:
                        cur.execute(
                            """
                            INSERT INTO session_identity_snapshot
                                (id, event_id, channel, channel_identity, match_result)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (id) DO NOTHING
                            """,
                            (
                                snapshot_id,
                                event.event_id,
                                channel_col,
                                event.from_phone,
                                Jsonb(_snapshot_to_json(snapshot)),
                            ),
                        )

                    cur.execute(
                        """
                        INSERT INTO agent_turn_context
                            (id, event_id, customer_thread_id, sms_session_id,
                             inbound_message_turn_id)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (event_id) DO NOTHING
                        RETURNING event_id
                        """,
                        (context_id, event.event_id, thread_id, session_id, turn_id),
                    )
                    created = cur.fetchone() is not None

                    if created:
                        # The outbox write. Same transaction, same commit -- the
                        # turn worker can never see a context without its job.
                        insert_job(
                            cur,
                            AgentJobPayload(
                                event_id=event.event_id,
                                conversation_id=event.conversation_id,
                            ),
                            job_type=AGENT_TURN_JOB_TYPE,
                        )

                    _ensure_open_case(
                        cur,
                        thread_id=thread_id,
                        session_id=session_id,
                        preview=event.body,
                        channel=channel_col,
                    )

                conn.commit()
            except Exception:
                conn.rollback()
                raise

        if created:
            return (
                build_agent_turn_context(
                    decision,
                    sms_session_id=session_id,
                    customer_thread_id=thread_id,
                    inbound_body_ref=body_ref,
                ),
                True,
            )

        loaded = self.load_context(event.event_id)
        if loaded is None:
            raise RuntimeError(
                f"agent_turn_context conflict for {event.event_id!r} but row missing"
            )
        return loaded, False

    def load_context(self, event_id: str) -> Optional[AgentTurnContext]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT c.event_id, c.customer_thread_id, c.sms_session_id,
                           c.inbound_message_turn_id, t.channel_identity, t.channel,
                           s.match_result, s.captured_at
                    FROM agent_turn_context c
                    JOIN customer_thread t ON t.id = c.customer_thread_id
                    LEFT JOIN session_identity_snapshot s ON s.event_id = c.event_id
                    WHERE c.event_id = %s
                    """,
                    (event_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None

                (
                    evt_id,
                    thread_id,
                    session_id,
                    turn_id,
                    from_phone,
                    channel,
                    match_result,
                    captured_at,
                ) = row

                # ponytail: conversation_id is the suffix on the session key (contact phone).
                conversation_id = session_id.rsplit(":", 1)[-1]

                snapshot = _snapshot_from_json(
                    match_result,
                    fallback_at=captured_at.isoformat() if captured_at else "",
                )

        return AgentTurnContext(
            event_id=evt_id,
            conversation_id=conversation_id,
            sms_session_id=session_id,
            customer_thread_id=thread_id,
            from_phone=from_phone,
            session_identity_snapshot=snapshot,
            inbound_body_ref=turn_id,
            # S17: the persisted channel vocabulary ("email"|"sms") — is_email_channel
            # recognizes it, so the reloaded email turn binds on the email identity.
            channel=channel,
        )

    def load_inbound_body(self, inbound_body_ref: str) -> Optional[str]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT body FROM message_turn WHERE id = %s",
                    (inbound_body_ref,),
                )
                row = cur.fetchone()
        return row[0] if row else None

    def load_recent_exchange(
        self, sms_session_id: str, *, limit: int
    ) -> list[dict[str, Any]]:
        """The last ``limit`` turns of ONE conversation, oldest first (0.0.5 S04).

        The gateway capture fork's only read. Scoped to the ``sms_session_id``
        rather than the thread on purpose: a confirmed clarification belongs to
        the conversation it happened in, and a session is the narrowest window
        that still contains both halves of "do you mean X?" -> "yes". Widening it
        to the thread would put older, unrelated conversations in front of a model
        for no capture benefit.

        Read on the WORKER, never on the turn (NFR-5). ``ORDER BY created_at DESC
        LIMIT n`` then reversed, so the fork sees the newest window in the order it
        was said; ``id`` breaks a same-timestamp tie deterministically.
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT author, direction, body FROM message_turn "
                    "WHERE sms_session_id = %s "
                    "ORDER BY created_at DESC, id DESC LIMIT %s",
                    (sms_session_id, limit),
                )
                rows = cur.fetchall()
        return [
            {"author": author, "direction": direction, "body": body}
            for author, direction, body in reversed(rows)
        ]

    def load_case_identity(self, case_id: str) -> Optional[dict[str, Any]]:
        """Resolve a case's customer-thread identity for turn-time memory binding (S08).

        The Copilot draft seam is bound to a ``case_id``, not a phone, so its binding
        key is derived here: join the case to its ``customer_thread`` and return an
        identity dict in the S02/S07 shape (``binding_key_from_identity``'s contract)
        — verified on the thread's ``shopify_customer_id``, else provisional on its
        channel identity. Returns ``None`` when the case is unknown or threadless, so
        the read fail-closes to "inject nothing" rather than raising."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT t.channel, t.channel_identity, t.shopify_customer_id
                    FROM cases c
                    JOIN customer_thread t ON t.id = c.customer_thread_id
                    WHERE c.id = %s
                    """,
                    (case_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        channel, channel_identity, shopify_customer_id = row
        if shopify_customer_id:
            return {
                "outcome": "verified_customer",
                "shopify_customer_id": shopify_customer_id,
                "channel": channel,
                "channel_identity": channel_identity,
            }
        return {
            "outcome": "unmatched_caller",
            "channel": channel,
            "channel_identity": channel_identity,
        }

    def load_customer_memory(self, binding_key: str) -> list[dict[str, Any]]:
        """Indexed read of a binding key's preference slots (FR-1), in the
        ``[{"slot": ..., "value": ...}, ...]`` shape ``hooks._render_memory`` expects."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT slot_name, slot_value FROM customer_memory_slot WHERE binding_key = %s",
                    (binding_key,),
                )
                rows = cur.fetchall()
        return [{"slot": name, "value": value} for name, value in rows]

    def load_confirmed_experience(self) -> list[dict[str, Any]]:
        """Bounded read of CONFIRMED ``agent_experience`` entries for injection (S25, FR-25).

        Operational, NOT customer-scoped (unlike :meth:`load_customer_memory`): L6
        learnings are shared team knowledge, so this is keyed by nothing but
        ``status``. Returns ONLY ``status='confirmed'`` rows -- ``proposed``/
        ``rejected`` are never injected into any turn -- newest-confirmed first,
        capped at :data:`_CONFIRMED_EXPERIENCE_LIMIT`. Returns the
        ``[{"content": ..., "kind": ...}, ...]`` shape ``hooks._render_experience``
        expects, plus ``id`` (S09): the provenance ledger's L6 ``entry_ref`` IS the
        entry id, and the renderer ignores the extra key.
        # ponytail: fixed cap is fine at current volume; make it relevance-ranked
        # only if the confirmed set ever outgrows the prompt budget (post-launch
        # real-traffic calibration, FR-27 -- see ADR-0152)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, content, kind FROM agent_experience
                    WHERE status = 'confirmed'
                    ORDER BY decided_at DESC NULLS LAST, created_at DESC
                    LIMIT %s
                    """,
                    (_CONFIRMED_EXPERIENCE_LIMIT,),
                )
                rows = cur.fetchall()
        return [
            {"id": entry_id, "content": content, "kind": kind}
            for entry_id, content, kind in rows
        ]

    def load_confirmed_lexicon(self) -> list[dict[str, Any]]:
        """Bounded read of CONFIRMED ``semantic_lexicon`` entries (0.0.5 S06, FR-6).

        Shared domain language, so — like :meth:`load_confirmed_experience` and
        unlike :meth:`load_customer_memory` — it is keyed by nothing but
        ``status``. Capped at
        :data:`~hermes_runtime.tool_backend.LEXICON_GLOSSARY_LIMIT` (D16: a named
        constant, because S22's knob panel reads it).

        **WHICH entries fill that cap is a knob (0.0.5 S26, FR-6's upgrade
        clause).** ``newest`` — the shipped default — orders by decided-at and
        lets Postgres apply the LIMIT. ``health`` reads every confirmed row plus
        its effectiveness aggregate and ranks in Python, through the SAME
        ``select_ranked_entries`` the console's score comes from, so the number an
        admin sees and the rule that decides what reaches the prompt can never be
        two different formulas.

        Reading every confirmed row in ``health`` mode is deliberate and cheap:
        the confirmed set is small (``lexicon_hits._CONFIRMED_SQL``, the
        deterministic seam's own vocabulary read, already does exactly this), and
        the alternative — an aggregate over ``injection_ledger`` per turn — is the
        reply-path read NFR-5 forbids. ``entry_effectiveness`` is materialized for
        that reason and joins on its primary key.

        ``status`` is in the projection even though the WHERE clause already
        pins it: ``hooks._render_lexicon`` re-checks the field rather than
        trusting its caller, so omitting it here would silently render an empty
        glossary. ``entry_kind`` and ``domain`` are what let the renderer resolve
        a ``default_rule``'s condition at render time; ``id`` is S09's L7
        ``entry_ref``.
        """
        from .entry_effectiveness import (
            entry_effectiveness_for,
            health_for_rows,
            select_ranked_entries,
        )
        from .injection_ledger import LAYER_L7
        from .tool_backend import LEXICON_SELECTION_HEALTH, lexicon_selection_strategy

        ranked = lexicon_selection_strategy() == LEXICON_SELECTION_HEALTH
        # In ranked mode the cap is applied AFTER scoring, so the SQL must not
        # pre-cut the set: pre-cutting by date is exactly the eviction the ranking
        # exists to replace.
        sql = _CONFIRMED_LEXICON_SQL + ("" if ranked else "\nLIMIT %s")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, () if ranked else (LEXICON_GLOSSARY_LIMIT,))
                rows = [
                    dict(zip(_CONFIRMED_LEXICON_COLUMNS, row)) for row in cur.fetchall()
                ]
                if not ranked:
                    return rows
                effectiveness = entry_effectiveness_for(
                    cur, layer=LAYER_L7, entry_refs=[row["id"] for row in rows]
                )
        return select_ranked_entries(
            health_for_rows(rows, effectiveness), limit=LEXICON_GLOSSARY_LIMIT
        )

    def record_injection_ledger(
        self,
        *,
        turn_ref: str,
        case_or_binding_ref: Optional[str],
        entries: Sequence[tuple[str, str]],
    ) -> None:
        """Append this turn's injected ``(layer, entry_ref)`` pairs (S09, FR-11).

        ONE batched insert per turn. ``ON CONFLICT DO NOTHING`` on the
        ``(turn_ref, layer, entry_ref)`` primary key -- the grain -- so a
        redelivered turn cannot double-count an entry into S26's per-entry
        score. Ids and slot NAMES only; no memory value ever reaches this table
        (NFR-6, and the column list has nowhere to put one).

        Reached only through
        :func:`hermes_runtime.injection_ledger.record_injection`, which owns the
        eval gate and swallows any failure -- so a raise here never reaches the
        turn (NFR-5).
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO injection_ledger
                        (turn_ref, layer, entry_ref, case_or_binding_ref)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (turn_ref, layer, entry_ref) DO NOTHING
                    """,
                    [
                        (turn_ref, layer, entry_ref, case_or_binding_ref)
                        for layer, entry_ref in entries
                    ],
                )
            conn.commit()

    def list_channel_identities_for_customer(
        self, shopify_customer_id: str
    ) -> list[tuple[str, str]]:
        """Every channel identity linked to a verified customer (S19, FR-19).

        Mirrors the ``identity_link`` read the ``toee_identity_lookup`` datastore
        handler's ``_match`` uses (``datastore/handlers/identity.py``), just the
        other direction: given a verified ``shopify_customer_id``, which
        ``(channel, channel_identity)`` pairs point at them. A plain, read-only,
        context-safe lookup used internally by the cross-channel provisional
        merge (``openrouter.py._merge_provisional_memory``) to enumerate every
        source key to merge -- never surfaced as a tool action, since it returns
        Identity Graph structure, not customer content (ADR-0151).

        Ordered ``(channel, channel_identity)`` ascending for a deterministic,
        reproducible merge order; the caller decides precedence on top of this
        (this turn's own channel first, ADR-0151).
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT channel, channel_identity FROM identity_link
                    WHERE shopify_customer_id = %s
                    ORDER BY channel, channel_identity
                    """,
                    (shopify_customer_id,),
                )
                return [(row[0], row[1]) for row in cur.fetchall()]

    def merge_provisional_memory(
        self, provisional_key: str, verified_key: str
    ) -> Optional[dict[str, Any]]:
        """Merge a caller's pre-verification provisional slots onto their verified
        record, atomically and idempotently (ADR-0112, FR-4, R5). First writer of
        ``customer_memory_merge_audit``.

        Behavior: move each provisional slot onto ``verified_key`` with
        ``source = merged_provisional``; **on slot conflict the verified value wins**
        and the provisional value is recorded in the audit ``details.overridden``;
        delete the provisional copies; write exactly one audit row. Evidence is
        **carried forward** on a migrated slot (the verbatim customer phrase is the
        slot's real provenance, and FR-3 wants every write to carry it); a conflicting
        slot is not inserted, so the verified slot's own evidence is left intact.

        **It also re-points the injection provenance ledger (S09, D4.3).** The
        binding key itself changes here, so the L4 ``entry_ref`` built from it
        (``binding_key || ':' || slot_name``) would otherwise be orphaned by
        verification -- see :func:`_repoint_injection_ledger`. Same transaction:
        the slots and their provenance move together or not at all.

        Idempotency (RK-5): the provisional rows are locked ``FOR UPDATE`` as the
        first statement, so two concurrent/repeat merges serialize here — the first
        deletes the rows, the second's lock re-check then finds an empty set and is a
        no-op. Exactly one audit row per transition, no double-apply, without a
        uniqueness constraint on the audit table. Returns ``None`` when there was
        nothing to merge.
        # ponytail: FOR UPDATE serialization is sufficient at SMS volume; add a
        # unique audit key only if a non-locking merge path ever appears.
        """
        with self._connect() as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT slot_name, slot_value, evidence
                        FROM customer_memory_slot
                        WHERE binding_key = %s
                        ORDER BY slot_name
                        FOR UPDATE
                        """,
                        (provisional_key,),
                    )
                    provisional_rows = cur.fetchall()
                    if not provisional_rows:
                        conn.commit()  # release the lock / snapshot; nothing to merge
                        return None

                    moved: list[str] = []
                    overridden: dict[str, str] = {}
                    for slot_name, slot_value, evidence in provisional_rows:
                        cur.execute(
                            """
                            INSERT INTO customer_memory_slot
                                (id, binding_key, binding_kind, slot_name, slot_value,
                                 source, evidence)
                            VALUES (%s, %s, 'verified', %s, %s, %s, %s)
                            ON CONFLICT (binding_key, slot_name) DO NOTHING
                            RETURNING slot_name
                            """,
                            (
                                new_id("mem"),
                                verified_key,
                                slot_name,
                                slot_value,
                                MEMORY_SOURCE_MERGED_PROVISIONAL,
                                evidence,
                            ),
                        )
                        if cur.fetchone() is not None:
                            moved.append(slot_name)
                        else:
                            overridden[slot_name] = slot_value

                    cur.execute(
                        "DELETE FROM customer_memory_slot WHERE binding_key = %s",
                        (provisional_key,),
                    )

                    _repoint_injection_ledger(
                        cur,
                        provisional_key=provisional_key,
                        verified_key=verified_key,
                        slot_names=[row[0] for row in provisional_rows],
                    )

                    details = {"moved": moved, "overridden": overridden}
                    cur.execute(
                        """
                        INSERT INTO customer_memory_merge_audit
                            (id, provisional_key, verified_key, details)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (new_id("merge"), provisional_key, verified_key, Jsonb(details)),
                    )
                conn.commit()
                return {"moved": moved, "overridden": overridden}
            except Exception:
                conn.rollback()
                raise

    def persist_agent_outbound(self, context: AgentTurnContext, body: str) -> None:
        """Mirror a successful agent SMS reply into message_turn for Workbench (ADR-0082)."""
        if not body.strip():
            return
        session_id = context.sms_session_id
        thread_id = context.customer_thread_id
        if not session_id or not thread_id:
            return
        # Deterministic id keyed by the inbound event so a re-dispatched turn
        # mirrors at most one hermes reply (the gateway sends one reply per turn).
        turn_id = f"{session_id}:{context.event_id}:out"
        with self._connect() as conn:
            try:
                with conn.cursor() as cur:
                    # Decided HERE rather than at inbound, because the escalation
                    # happens DURING the turn: the agent calls toee_case only once
                    # it knows it cannot finish the request itself. At inbound we
                    # would always read "no escalation yet" and mark every turn
                    # auto-handled.
                    auto_handled = not _escalation_case_open(cur, thread_id)
                    cur.execute(
                        """
                        INSERT INTO message_turn
                            (id, sms_session_id, customer_thread_id, direction,
                             author, body, auto_handled)
                        VALUES (%s, %s, %s, 'outbound', 'hermes', %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (turn_id, session_id, thread_id, body, auto_handled),
                    )
                    if not auto_handled and context.inbound_body_ref:
                        # The inbound that TRIGGERED this escalation belongs to the
                        # human-intervention segment too. It was written before the
                        # agent escalated, so it optimistically read auto-handled;
                        # settle the pair now that the turn's outcome is known.
                        # Without this the customer's message reads "auto-handled"
                        # while the reply that escalated it does not -- and
                        # `active_case_segment` (cases.py) would hide the very turn
                        # that opened the case from the case segment.
                        cur.execute(
                            "UPDATE message_turn SET auto_handled = FALSE WHERE id = %s",
                            (context.inbound_body_ref,),
                        )
                    cur.execute(
                        """
                        UPDATE cases SET last_activity_at = now()
                        WHERE customer_thread_id = %s
                          AND status IN ('open', 'in_progress')
                        """,
                        (thread_id,),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise


def _repoint_injection_ledger(
    cur, *, provisional_key: str, verified_key: str, slot_names: Sequence[str]
) -> int:
    """Move this merge's L4 provenance rows onto the verified binding key (S09, D4.3).

    The symmetric other half of what the merge already does to the slots
    themselves. An L4 ``entry_ref`` is ``binding_key || ':' || slot_name``, and
    the merge CHANGES the binding key -- so without this, every ledger row
    written before the customer verified points at a key that no longer names
    anything, and S10's blast radius silently omits those turns while S26 scores
    a prompt whose entries it can no longer resolve. Same cursor, same
    transaction as the slot move: the two cannot half-apply.

    Both moved AND overridden slots re-point: the ledger records which ENTRY
    reached a turn, and after the merge the customer's ``slot_name`` entry IS
    the verified one either way. (An overridden slot's *value* was already free
    to change between the turn and the read -- the ledger never claimed
    otherwise.)

    The ``NOT EXISTS`` guard is deliberate. ``entry_ref`` is part of the ledger's
    primary key, so a turn that somehow already held the verified ref would make
    a bare UPDATE raise a duplicate-key error -- which, inside this transaction,
    would roll back the customer's memory merge. Provenance bookkeeping must
    never do that: the guard leaves the stale row behind instead.
    """
    if not slot_names:
        return 0
    from .injection_ledger import LAYER_L4

    cur.execute(
        """
        UPDATE injection_ledger AS il
        SET entry_ref = %(verified)s || ':' || s.slot_name
        FROM unnest(%(slots)s::text[]) AS s(slot_name)
        WHERE il.layer = %(layer)s
          AND il.entry_ref = %(provisional)s || ':' || s.slot_name
          AND NOT EXISTS (
              SELECT 1 FROM injection_ledger dup
              WHERE dup.turn_ref = il.turn_ref
                AND dup.layer = %(layer)s
                AND dup.entry_ref = %(verified)s || ':' || s.slot_name
          )
        """,
        {
            "verified": verified_key,
            "provisional": provisional_key,
            "slots": list(slot_names),
            "layer": LAYER_L4,
        },
    )
    return cur.rowcount


def _escalation_case_open(cur, thread_id: str) -> bool:
    """Is a human actually needed on this thread right now?

    This is what decides ``message_turn.auto_handled`` -- an **Auto-Handled
    Interaction** is a turn the External Customer Service Profile completes
    "without opening a Human Intervention Case" (CONTEXT.md), and ADR-0037 is
    explicit that such threads must NOT enter the rep work queue.

    The test cannot simply be "does a case exist", because ``_ensure_open_case``
    below opens one on EVERY accepted inbound so Tier B can show the thread.
    That placeholder is deliberately **untriaged** -- it carries no
    ``contact_reason``. A case only becomes a real Human Intervention Case once
    something states WHY a human is needed:

      * the agent escalates and calls ``toee_case`` create_case with a
        contact_reason (it is in the EXTERNAL Profile Tool Allowlist), or
      * an employee triages the placeholder in the Workbench ("Edit reason").

    So ``contact_reason IS NOT NULL`` is the escalation signal, and the
    untriaged placeholder stays out of it. `_ensure_open_case` must therefore
    keep leaving contact_reason NULL -- ``test_gateway_placeholder_case_stays_untriaged``
    pins that, because setting one there would silently mark every conversation
    escalated and empty the auto-handled audit view again.

    ``sales_outreach`` is excluded to match ``_list_auto_handled``, which routes
    those to the separate Sales Outreach Audit View.
    """
    cur.execute(
        """
        SELECT 1 FROM cases
        WHERE customer_thread_id = %s
          AND status IN ('open', 'in_progress')
          AND contact_reason IS NOT NULL
          AND contact_reason <> 'sales_outreach'
        LIMIT 1
        """,
        (thread_id,),
    )
    return cur.fetchone() is not None


def _ensure_open_case(
    cur,
    *,
    thread_id: str,
    session_id: str,
    preview: str,
    channel: str = _SMS_CHANNEL,
) -> None:
    """Open a Follow-up Case when none exists so Tier B Workbench shows the thread.

    Leaves ``contact_reason`` NULL on purpose: an untriaged placeholder, not an
    escalation. See ``_escalation_case_open`` for why that distinction carries
    the whole auto-handled read model.
    """
    cur.execute(
        "SELECT id FROM cases WHERE customer_thread_id = %s AND status IN ('open', 'in_progress') LIMIT 1",
        (thread_id,),
    )
    row = cur.fetchone()
    if row is not None:
        cur.execute(
            "UPDATE cases SET last_activity_at = now(), sms_session_id = %s WHERE id = %s",
            (session_id, row[0]),
        )
        return

    case_id = new_id("case")
    summary = preview[:200] if preview else None
    cur.execute(
        """
        INSERT INTO cases
            (id, channel, customer_thread_id, sms_session_id, status, summary, urgency)
        VALUES (%s, %s, %s, %s, 'open', %s, 'normal')
        """,
        (case_id, channel, thread_id, session_id, summary),
    )
