"""Postgres-backed GatewayStore (ADR-0107/0115/0140).

Persists accepted inbound turns into the Toee Business Datastore so Workbench
(Tier B) reads the same customer_thread / sms_session / message_turn / cases
rows the dispatch servers use. Wired when ``TOOL_BACKEND=datastore`` (same axis
as the per-profile dispatch servers, ADR-0142).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Optional

import psycopg
from psycopg.types.json import Jsonb

from toee_hermes.drivers.mock.memory import MEMORY_SOURCE_MERGED_PROVISIONAL
from toee_hermes.gateway.agent_turn import AgentTurnContext, build_agent_turn_context
from toee_hermes.gateway.ingress import SessionIdentitySnapshot
from toee_hermes.gateway.pipeline import InboundDecision

from .datastore.config import database_url
from .datastore.handlers._common import new_id

_SMS_CHANNEL = "sms"
# Dev substrate: one provider conversation maps to one SMS session (ADR-0115).
_SESSION_TTL = "24 hours"


def _thread_id(from_phone: str) -> str:
    return f"customer_thread:sms:{from_phone}"


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
            conn = psycopg.connect(self._dsn)
            try:
                yield conn
            finally:
                conn.close()

    def is_duplicate(self, event_id: str) -> bool:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM agent_turn_context WHERE event_id = %s LIMIT 1",
                    (event_id,),
                )
                return cur.fetchone() is not None

    def persist_accepted_inbound(
        self, decision: InboundDecision
    ) -> tuple[AgentTurnContext, bool]:
        event = decision.event
        if not decision.enqueue or event is None:
            raise ValueError(
                "persist_accepted_inbound requires an accepted (enqueue) decision; "
                f"got action={decision.action!r}."
            )

        thread_id = _thread_id(event.from_phone)
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
                        (thread_id, _SMS_CHANNEL, event.from_phone, thread_shopify_id),
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
                        VALUES (%s, %s, %s, 'inbound', 'customer', %s, FALSE)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (turn_id, session_id, thread_id, event.body),
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
                                _SMS_CHANNEL,
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

                    _ensure_open_case(
                        cur,
                        thread_id=thread_id,
                        session_id=session_id,
                        preview=event.body,
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
                           c.inbound_message_turn_id, t.channel_identity,
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
                    cur.execute(
                        """
                        INSERT INTO message_turn
                            (id, sms_session_id, customer_thread_id, direction,
                             author, body, auto_handled)
                        VALUES (%s, %s, %s, 'outbound', 'hermes', %s, FALSE)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (turn_id, session_id, thread_id, body),
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


def _ensure_open_case(
    cur,
    *,
    thread_id: str,
    session_id: str,
    preview: str,
) -> None:
    """Open a Follow-up Case when none exists so Tier B Workbench shows the thread."""
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
        VALUES (%s, 'sms', %s, %s, 'open', %s, 'normal')
        """,
        (case_id, thread_id, session_id, summary),
    )
