"""S10 / FR-4 / R5: provisional->verified Customer Memory merge, at the store level.

The merge unit of work (:meth:`PostgresGatewayStore.merge_provisional_memory`) is
the first writer of ``customer_memory_merge_audit`` (ADR-0112). These tests prove
the R5 three-state against real Postgres (throwaway-schema ``datastore`` fixture):

- (a) no-conflict merge moves provisional slots onto the verified key and deletes
  the provisional copies;
- (b) on slot conflict the VERIFIED value wins and the provisional value is recorded
  in ``customer_memory_merge_audit.details``;
- (c) nothing to merge (the trigger's "ambiguous / no provisional rows" case) is an
  idempotent no-op that writes no audit row.

Plus the RK-5 idempotency guarantees: a repeat merge and two genuinely concurrent
merges each produce EXACTLY ONE audit row and never double-apply (the merge locks
the provisional rows ``FOR UPDATE``; the first deletes them so the second sees an
empty set). And a guard that the synchronous ack path
(:meth:`persist_accepted_inbound`) never merges.
"""

from __future__ import annotations

import threading

from hermes_runtime.datastore.config import database_url
from hermes_runtime.postgres_gateway_store import PostgresGatewayStore
from toee_hermes.drivers.mock.memory import (
    MEMORY_SOURCE_MERGED_PROVISIONAL,
    MEMORY_SOURCE_VALUES,
)

_PROV = "provisional:sms:+14165550111"
_VERIFIED = "gid://shopify/Customer/5001"


def _seed_slot(cur, binding_key, kind, slot, value, source, evidence=None) -> None:
    cur.execute(
        """
        INSERT INTO customer_memory_slot
            (id, binding_key, binding_kind, slot_name, slot_value, source, evidence)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (f"mem_{binding_key}_{slot}", binding_key, kind, slot, value, source, evidence),
    )


def _slots(cur, binding_key) -> dict[str, tuple[str, str, str]]:
    cur.execute(
        "SELECT slot_name, slot_value, source, evidence FROM customer_memory_slot "
        "WHERE binding_key = %s",
        (binding_key,),
    )
    return {name: (value, source, evidence) for name, value, source, evidence in cur.fetchall()}


def _audit_rows(cur, provisional_key):
    cur.execute(
        "SELECT provisional_key, verified_key, details FROM customer_memory_merge_audit "
        "WHERE provisional_key = %s",
        (provisional_key,),
    )
    return cur.fetchall()


def test_merge_no_conflict_moves_provisional_and_deletes(datastore) -> None:
    """R5(a): no verified slot conflicts -> both provisional slots migrate onto the
    verified key (source merged_provisional, evidence carried), provisional deleted,
    one audit row whose details record the moved slots."""
    _, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)
    with conn.cursor() as cur:
        _seed_slot(cur, _PROV, "provisional", "contact_time_preference", "mornings",
                   "customer_explicit", "call me in the mornings")
        _seed_slot(cur, _PROV, "provisional", "channel_preference", "sms",
                   "customer_explicit")

    result = store.merge_provisional_memory(_PROV, _VERIFIED)

    with conn.cursor() as cur:
        verified = _slots(cur, _VERIFIED)
        assert verified["contact_time_preference"] == (
            "mornings", "merged_provisional", "call me in the mornings",
        )
        assert verified["channel_preference"] == ("sms", "merged_provisional", None)
        assert _slots(cur, _PROV) == {}  # provisional copies removed
        audit = _audit_rows(cur, _PROV)
        assert len(audit) == 1
        prov_key, ver_key, details = audit[0]
        assert (prov_key, ver_key) == (_PROV, _VERIFIED)
        assert sorted(details["moved"]) == ["channel_preference", "contact_time_preference"]
        assert details["overridden"] == {}
    assert sorted(result["moved"]) == ["channel_preference", "contact_time_preference"]


def test_merge_writes_source_from_the_shared_memory_source_enum(datastore) -> None:
    """Standards fix #2 (drift guard): the merge SQL's ``source`` column must come
    from the SAME ``MEMORY_SOURCE_VALUES`` enum every other write path is checked
    against (``test_customer_memory_write_source.py``), not a scattered SQL
    literal that could silently drift out of sync with it -- e.g. a typo'd
    ``'merge_provisional'`` would still "work" (writes and reads round-trip fine)
    while quietly breaking anything that filters/validates on the real enum."""
    _, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)
    with conn.cursor() as cur:
        _seed_slot(cur, _PROV, "provisional", "channel_preference", "sms",
                   "customer_explicit")

    store.merge_provisional_memory(_PROV, _VERIFIED)

    with conn.cursor() as cur:
        _, source, _ = _slots(cur, _VERIFIED)["channel_preference"]
    assert source == MEMORY_SOURCE_MERGED_PROVISIONAL
    assert source in MEMORY_SOURCE_VALUES


def test_merge_writes_null_actor(datastore) -> None:
    """§6.1 matrix / R2: a provisional->verified merge writes no actor (null),
    same as an AI-draft row -- the merge INSERT never sets ``actor_account_id``,
    so Postgres's own column default (NULL, no DEFAULT clause) fills it; this pins
    that behavior against a future edit to the merge SQL's column list."""
    _, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)
    with conn.cursor() as cur:
        _seed_slot(cur, _PROV, "provisional", "channel_preference", "sms",
                   "customer_explicit")

    store.merge_provisional_memory(_PROV, _VERIFIED)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT actor_account_id FROM customer_memory_slot "
            "WHERE binding_key = %s AND slot_name = %s",
            (_VERIFIED, "channel_preference"),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] is None


def test_merge_conflict_keeps_verified_and_shadows_provisional(datastore) -> None:
    """R5(b): a slot present on BOTH keys -> the verified value is kept untouched and
    the provisional value is recorded in details.overridden; a non-conflicting slot
    still migrates."""
    _, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)
    with conn.cursor() as cur:
        # conflict slot
        _seed_slot(cur, _PROV, "provisional", "channel_preference", "email",
                   "customer_explicit", "email is better")
        _seed_slot(cur, _VERIFIED, "verified", "channel_preference", "sms",
                   "customer_explicit", "text me")
        # non-conflicting slot rides along
        _seed_slot(cur, _PROV, "provisional", "contact_time_preference", "mornings",
                   "customer_explicit")

    store.merge_provisional_memory(_PROV, _VERIFIED)

    with conn.cursor() as cur:
        verified = _slots(cur, _VERIFIED)
        # verified value wins, its source/evidence untouched (not merged_provisional)
        assert verified["channel_preference"] == ("sms", "customer_explicit", "text me")
        # the non-conflicting slot migrated
        assert verified["contact_time_preference"] == ("mornings", "merged_provisional", None)
        assert _slots(cur, _PROV) == {}
        audit = _audit_rows(cur, _PROV)
        assert len(audit) == 1
        _, _, details = audit[0]
        assert details["overridden"] == {"channel_preference": "email"}
        assert details["moved"] == ["contact_time_preference"]


def test_merge_with_no_provisional_rows_is_noop_no_audit(datastore) -> None:
    """R5(c) / trigger no-op: nothing provisional to merge -> returns None, writes no
    audit row, leaves the verified slot intact."""
    _, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)
    with conn.cursor() as cur:
        _seed_slot(cur, _VERIFIED, "verified", "channel_preference", "sms", "customer_explicit")

    result = store.merge_provisional_memory(_PROV, _VERIFIED)

    assert result is None
    with conn.cursor() as cur:
        assert _audit_rows(cur, _PROV) == []
        assert _slots(cur, _VERIFIED)["channel_preference"] == ("sms", "customer_explicit", None)


def test_merge_repeat_is_idempotent_one_audit_row(datastore) -> None:
    """RK-5: running the merge twice yields exactly one audit row (the second call
    finds the provisional rows already gone) and does not double-apply."""
    _, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)
    with conn.cursor() as cur:
        _seed_slot(cur, _PROV, "provisional", "contact_time_preference", "mornings",
                   "customer_explicit")

    first = store.merge_provisional_memory(_PROV, _VERIFIED)
    second = store.merge_provisional_memory(_PROV, _VERIFIED)

    assert first is not None
    assert second is None
    with conn.cursor() as cur:
        assert len(_audit_rows(cur, _PROV)) == 1
        assert _slots(cur, _PROV) == {}
        assert _slots(cur, _VERIFIED)["contact_time_preference"][0] == "mornings"


def test_merge_is_idempotent_under_true_concurrency(datastore) -> None:
    """RK-5: two genuinely concurrent merges (separate connections, separate txns,
    released together at a barrier) contend on the ``FOR UPDATE`` lock; exactly one
    wins and writes the single audit row, the other is a no-op."""
    from psycopg import sql

    import psycopg

    _, conn, schema = datastore
    prov = "provisional:sms:+14165550222"
    verified = "gid://shopify/Customer/5002"
    with conn.cursor() as cur:
        _seed_slot(cur, prov, "provisional", "contact_time_preference", "mornings",
                   "customer_explicit")
    conn.commit()  # commit so the worker connections (separate txns) see the seed

    results: list[object] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        c = psycopg.connect(database_url())
        try:
            with c.cursor() as cur:
                cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            c.commit()
            store = PostgresGatewayStore(connection=c)
            barrier.wait()
            results.append(store.merge_provisional_memory(prov, verified))
        except BaseException as exc:  # noqa: BLE001 - surface thread failures to the test
            errors.append(exc)
        finally:
            c.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert results.count(None) == 1  # exactly one worker found nothing to merge
    with conn.cursor() as cur:
        assert len(_audit_rows(cur, prov)) == 1
        assert _slots(cur, prov) == {}
        assert _slots(cur, verified)["contact_time_preference"][0] == "mornings"


def test_ack_path_persist_does_not_merge(datastore) -> None:
    """RK-5 / off-the-ack-path: the synchronous webhook persistence
    (:meth:`persist_accepted_inbound`) must NOT merge -- with provisional slots
    already stored, accepting a verified inbound writes no merge audit row and leaves
    the provisional slots untouched (the merge only runs on the async turn)."""
    from toee_hermes.gateway.ingress import SessionIdentitySnapshot
    from toee_hermes.gateway.normalize import InboundChannelEvent
    from toee_hermes.gateway.pipeline import InboundDecision

    _, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)
    phone = "+14165550333"
    prov = "provisional:sms:+14165550333"
    shopify_id = "gid://shopify/Customer/5003"
    with conn.cursor() as cur:
        _seed_slot(cur, prov, "provisional", "contact_time_preference", "mornings",
                   "customer_explicit")

    decision = InboundDecision(
        status=200,
        action="enqueue",
        stage="accept",
        event=InboundChannelEvent(
            channel="textline_sms",
            provider="textline",
            event_id="evt-ack-nomerge",
            conversation_id="conv-ack-nomerge",
            from_phone=phone,
            body="hi",
            received_at="2026-01-01T00:00:00Z",
            raw_event_type="message.created",
            media_urls=None,
        ),
        snapshot=SessionIdentitySnapshot(
            outcome="verified_customer",
            resolved_at="2026-01-01T00:00:00Z",
            shopify_customer_id=shopify_id,
            display_name="Ack Customer",
        ),
    )

    store.persist_accepted_inbound(decision)

    with conn.cursor() as cur:
        assert _audit_rows(cur, prov) == []
        assert _slots(cur, prov)["contact_time_preference"][0] == "mornings"
