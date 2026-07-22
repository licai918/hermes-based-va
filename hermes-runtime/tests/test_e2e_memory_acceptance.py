"""S13 — E2E acceptance: the §6 memory-activation gate for 0.0.1.

ONE suite proving all four memory layers are live in a real turn, that content
and customer are correct, and that the activation cannot silently revert. Every
assertion obeys the §6.0 proof principles:

  1. Live, not mock — persistence is read back **directly from Postgres** (the
     throwaway ``datastore`` schema), never from a tool's return shape.
  2. Right content — an injected value is byte-compared to what was stored for
     that binding key (not "a block appeared").
  3. Right customer — isolation is proven by a *second* customer who must NOT see
     the first's memory, in both directions.
  4. Dormancy tripwire — the same activation E2E runs with the composite driver
     DISABLED and must assert the dormant state (RED-capable: it passes only while
     dormant and would fail if memory were wrongly active).

The gateway → async turn → datastore path is driven for real (signed webhook →
``persist_accepted_inbound`` → the durable ``PostgresJobQueue`` → the turn
worker's ``run_once`` → the production
``make_openrouter_run_turn``). The model is the only fake: the scripted OpenAI
provider (``_scripted_openai_factory``) makes the turn deterministic, and
``run_agent_turn`` is wrapped so we capture the exact injected user message the
model was handed (RK-8). Skip-if-no-DB via the shared ``datastore`` fixture.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

from starlette.testclient import TestClient

from toee_hermes.drivers.mock import MockDriver, create_all_mock_handlers
from toee_hermes.execute import execute_tool
from toee_hermes.gateway.ingress import SessionIdentitySnapshot
from toee_hermes.gateway.normalize import normalize_e164
from toee_hermes.plugin.profiles import EXTERNAL, INTERNAL
from toee_hermes.tool_gate import ToolExecutionContext

import hermes_runtime.openrouter as openrouter_mod
import hermes_runtime.tool_backend as tool_backend_mod
from hermes_runtime.gateway_app import create_app
from hermes_runtime.job_queue import PostgresJobQueue
from hermes_runtime.live import _scripted_openai_factory
from hermes_runtime.openrouter import (
    OPENROUTER_PRIMARY_MODEL,
    OpenRouterConfig,
    make_openrouter_run_turn,
)
from hermes_runtime.postgres_gateway_store import PostgresGatewayStore
from hermes_runtime.turn_runner import make_gateway_turn_runner
from hermes_runtime.turn_worker import run_once

WEBHOOK_SECRET = "test-simpletexting-url-token"

_CONFIG = OpenRouterConfig(
    base_url="https://openrouter.ai/api/v1",
    api_key="sk-or-test",
    model=OPENROUTER_PRIMARY_MODEL,
)

# Mock Ingress Phone Match seeds (drivers/mock/identity.py): +14165550101 resolves
# to a verified customer with this Shopify id; any unseeded phone is unmatched.
_VERIFIED_PHONE = "+14165550101"
_VERIFIED_ID = "gid://shopify/Customer/1001"
_UNMATCHED_PHONE = "+14165559999"

_VERIFIED_PREF = "text me after 5pm, don't call"
_VERIFIED_SLOT = "contact_time_preference"
_PROVISIONAL_PREF = "leave orders at the loading dock"
_PROVISIONAL_SLOT = "delivery_habit_note"


# --------------------------------------------------------------------------- #
# Webhook helpers (SimpleTexting report shape, URL-token auth — ADR-0021).
# --------------------------------------------------------------------------- #
def _inbound(*, body: str, from_phone: str, event_id: str, conversation_id: str) -> bytes:
    del conversation_id  # SimpleTexting keys the conversation by contact phone
    return json.dumps(
        {
            "reportId": f"rep-{event_id}",
            "webhookId": "wh-1",
            "type": "INCOMING_MESSAGE",
            "values": {
                "messageId": event_id,
                "text": body,
                "accountPhone": "9053378266",
                "contactPhone": from_phone,
                "timestamp": "2026-01-01T00:00:00.000Z",
                "category": "SMS",
            },
        }
    ).encode("utf-8")


def _upsert_call(*, slot: str, value: str) -> dict:
    """A scripted assistant turn requesting one governed memory write."""
    return {
        "tool_calls": [
            {
                "name": "toee_customer_memory__upsert_preference",
                "arguments": {"key": slot, "value": value},
            }
        ]
    }


def _post(client: TestClient, raw: bytes):
    return client.post(
        f"/webhooks/simpletexting?token={WEBHOOK_SECRET}", content=raw
    )


def _capture_injections(monkeypatch) -> list[str]:
    """Wrap ``run_agent_turn`` to record each turn's injected user message.

    Delegates to the REAL agent loop (so scripted tool calls still dispatch through
    governed execution and the write actually lands), while capturing the exact
    prompt handed to the model — the faithful "injection reached the model" probe
    (RK-8). Returns the growing list; one entry per ``run_turn`` (per webhook round).
    """
    real_run_agent_turn = openrouter_mod.run_agent_turn
    captured: list[str] = []

    def wrap(*, user_message: str, **kwargs):
        captured.append(user_message)
        return real_run_agent_turn(user_message=user_message, **kwargs)

    monkeypatch.setattr(openrouter_mod, "run_agent_turn", wrap)
    return captured


def _capture_injection_only(monkeypatch, *, store, context, scripted=None) -> str:
    """Run one production ``run_turn`` and return only the injected user message.

    ``run_agent_turn`` is stubbed, so the injection path (S10 merge + S07 read +
    shared binding derivation + render) runs for real but no agent loop / network
    does — the assertion is on the exact prompt, isolating the read/merge under test.
    """
    captured: dict[str, str] = {}

    def capture(*, user_message: str, **_kwargs) -> dict[str, object]:
        captured["user_message"] = user_message
        return {"final_response": "", "messages": []}

    monkeypatch.setattr(openrouter_mod, "run_agent_turn", capture)
    run_turn = make_openrouter_run_turn(
        config=_CONFIG,
        openai_factory=_scripted_openai_factory(scripted or [{"content": "ok"}]),
        store=store,
    )
    run_turn(context, "Hi again")
    return captured["user_message"]


def _write_preference(driver, *, identity, key, value):
    """Store a preference through the real governed datastore write path.

    Asserts anti-mock at the source: a live governed write attributes
    ``driver.kind = "datastore"`` on its audit record (§6.6 / R4), so 0 writes reach
    the mock store.
    """
    result = execute_tool(
        tool="toee_customer_memory",
        action="upsert_preference",
        params={"key": key, "value": value},
        context=ToolExecutionContext(profile=EXTERNAL, identity=identity),
        driver=driver,
    )
    assert result.ok, result
    assert result.audit.driver == "datastore"  # anti-mock: never the mock store
    return result


class _PersistAndDrain:
    """Wraps the real ``PostgresGatewayStore``: after it persists the turn and its
    job row (one transaction, S02 fix wave 1), run the turn worker's poll inline.

    Production splits those across two processes (0.0.4 S02) — this suite is about
    the four memory layers, not the substrate, so draining inline keeps one signed
    webhook deterministically driving one bound turn while still going through the
    real ``insert_job`` + ``PostgresJobQueue.claim`` + ``run_once`` code path.
    Everything other than the persist delegates untouched.
    """

    def __init__(self, *, store, queue, turn_runner) -> None:
        self._store = store
        self._queue = queue
        self._turn_runner = turn_runner

    def __getattr__(self, name):
        return getattr(self._store, name)

    def persist_accepted_inbound(self, decision):
        persisted = self._store.persist_accepted_inbound(decision)
        assert (
            run_once(
                queue=self._queue,
                store=self._store,
                turn_runner=self._turn_runner,
                worker="test-turn-worker",
            )
            is not None
        )
        return persisted


def _build_app(*, store, conn, run_turn, sent):
    """The real gateway app: mock Ingress Phone Match, Postgres persistence, and the
    durable queue drained inline so a single signed webhook drives the bound turn."""
    turn_runner = make_gateway_turn_runner(
        reply_sender=lambda conv, text: sent.append((conv, text)),
        run_turn=run_turn,
        on_reply_sent=store.persist_agent_outbound,
    )
    return create_app(
        webhook_secret=WEBHOOK_SECRET,
        # Ingress identity resolution is the integration axis (mock here); the memory
        # system-of-record is the datastore axis under test. +14165550101 -> verified.
        driver=MockDriver(create_all_mock_handlers()),
        store=_PersistAndDrain(
            store=store,
            queue=PostgresJobQueue(connection=conn),
            turn_runner=turn_runner,
        ),
        is_duplicate=store.is_duplicate,
    )


# --------------------------------------------------------------------------- #
# §6.1 — All four layers effective in ONE live webhook run.
# --------------------------------------------------------------------------- #
def test_matrix_all_four_layers_live_in_one_run(datastore, monkeypatch, caplog) -> None:
    """§6.1 activation matrix: L1 identity binding, L2 conversation rows, L3 case +
    audit, L4 memory write→persist→inject — plus anti-mock (§6.6) and the §6.4
    observability note. Three webhook rounds against ONE app: a verified customer
    writes then re-enters (L4 round-trip), and an unmatched caller writes (L1 proves
    verified→shopifyCustomerId vs else→provisional:sms:{E.164})."""
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    driver, conn, _ = datastore
    # Route the live turn's toee_customer_memory overlay at the fixture connection so
    # the governed write lands in THIS throwaway schema (else a fresh DSN connection
    # would write the default schema and the read-back would see nothing).
    # select_tool_driver lives behind tool_backend._customer_memory_extra_drivers
    # (Standards fix #1 -- shared with copilot_turn.py instead of two copies).
    monkeypatch.setattr(tool_backend_mod, "select_tool_driver", lambda *_a, **_k: driver)

    store = PostgresGatewayStore(connection=conn)
    sent: list[tuple[str, str]] = []
    captured = _capture_injections(monkeypatch)
    run_turn = make_openrouter_run_turn(
        config=_CONFIG,
        store=store,
        openai_factory=_scripted_openai_factory(
            [
                _upsert_call(slot=_VERIFIED_SLOT, value=_VERIFIED_PREF),  # R1 write
                {"content": "Got it — I'll text you after 5pm."},         # R1 reply
                {"content": "Welcome back, happy to help."},              # R2 reply
                _upsert_call(slot=_PROVISIONAL_SLOT, value=_PROVISIONAL_PREF),  # R3 write
                {"content": "Noted — loading dock it is."},               # R3 reply
            ]
        ),
    )
    app = _build_app(store=store, conn=conn, run_turn=run_turn, sent=sent)
    client = TestClient(app)

    with caplog.at_level(logging.INFO, logger="hermes_runtime.openrouter"):
        # R1 verified: states a durable preference (governed write in a real turn).
        assert _post(
            client,
            _inbound(
                body="Please text me after 5pm, don't call.",
                from_phone=_VERIFIED_PHONE,
                event_id="evt-m1",
                conversation_id="conv-matrix-v",
            ),
        ).status_code == 200
        # R2 verified re-enter: the stored preference must be injected THIS turn.
        assert _post(
            client,
            _inbound(
                body="Hey, it's me again.",
                from_phone=_VERIFIED_PHONE,
                event_id="evt-m2",
                conversation_id="conv-matrix-v",
            ),
        ).status_code == 200
        # R3 unmatched: an unverified caller binds provisionally, never to a shared key.
        assert _post(
            client,
            _inbound(
                body="Leave my orders at the loading dock.",
                from_phone=_UNMATCHED_PHONE,
                event_id="evt-m3",
                conversation_id="conv-matrix-u",
            ),
        ).status_code == 200

    assert len(sent) == 3  # every round completed and replied

    with conn.cursor() as cur:
        # --- L1 Identity Graph: the ingress snapshot + the chosen binding key. -----
        cur.execute(
            "SELECT match_result FROM session_identity_snapshot WHERE event_id = %s",
            ("evt-m1",),
        )
        match_result = cur.fetchone()[0]
        assert match_result["outcome"] == "verified_customer"
        assert match_result["shopify_customer_id"] == _VERIFIED_ID
        cur.execute(
            "SELECT shopify_customer_id FROM customer_thread WHERE channel_identity = %s",
            (_VERIFIED_PHONE,),
        )
        assert cur.fetchone()[0] == _VERIFIED_ID  # verified binding persisted on thread

        # --- L2 Conversation: thread / session / message_turn / agent_turn_context. -
        cur.execute(
            "SELECT customer_thread_id, sms_session_id, inbound_message_turn_id "
            "FROM agent_turn_context WHERE event_id = %s",
            ("evt-m1",),
        )
        thread_id, session_id, turn_id = cur.fetchone()
        assert thread_id and session_id and turn_id
        cur.execute("SELECT 1 FROM customer_thread WHERE id = %s", (thread_id,))
        assert cur.fetchone() is not None
        cur.execute("SELECT 1 FROM sms_session WHERE id = %s", (session_id,))
        assert cur.fetchone() is not None
        cur.execute(
            "SELECT body FROM message_turn WHERE id = %s AND direction = 'inbound'",
            (turn_id,),
        )
        assert cur.fetchone()[0] == "Please text me after 5pm, don't call."

        # --- L4 Customer Memory: the write reached Postgres under the RIGHT key. ----
        cur.execute(
            "SELECT slot_value, source, binding_kind FROM customer_memory_slot "
            "WHERE binding_key = %s AND slot_name = %s",
            (_VERIFIED_ID, _VERIFIED_SLOT),
        )
        row = cur.fetchone()
        assert row == (_VERIFIED_PREF, "customer_explicit", "verified")

        # L1 (else-branch): the unmatched caller bound provisionally, not shared.
        provisional_key = f"provisional:sms:{normalize_e164(_UNMATCHED_PHONE)}"
        cur.execute(
            "SELECT slot_value, binding_kind FROM customer_memory_slot "
            "WHERE binding_key = %s AND slot_name = %s",
            (provisional_key, _PROVISIONAL_SLOT),
        )
        assert cur.fetchone() == (_PROVISIONAL_PREF, "provisional")

        # --- L3 Operational: the follow-up case row exists for the verified thread. -
        cur.execute(
            "SELECT id, status FROM cases WHERE customer_thread_id = %s", (thread_id,)
        )
        case_id, status = cur.fetchone()
        assert status in ("open", "in_progress")

    # L3 governed writes audited: a rep claims the follow-up case (the operational
    # layer's audited governed write) — one workbench_audit_log row, driver.kind
    # datastore (anti-mock). The external SMS turn opens the case; the audited
    # operational mutation is the Copilot/case surface acting on it.
    claim = execute_tool(
        tool="toee_case_manage",
        action="claim_case",
        params={"case_id": case_id},
        context=ToolExecutionContext(profile=INTERNAL, user_id="acct_rep_1"),
        driver=driver,
    )
    assert claim.ok
    assert claim.audit.driver == "datastore"
    with conn.cursor() as cur:
        cur.execute(
            "SELECT profile FROM workbench_audit_log "
            "WHERE action = 'claim_case' AND target_type = 'case' AND target_id = %s",
            (case_id,),
        )
        assert cur.fetchone() == (INTERNAL,)

    # --- L4 content round-trip (§6.0.2): the STORED value appears in R2's injection. -
    assert "Customer Memory" in captured[1]
    assert _VERIFIED_PREF in captured[1]
    # R1 is the first-ever turn: nothing stored yet, so no memory block was injected.
    # (The phrase itself appears in R1's *inbound body* — the customer just said it —
    # so the reliable signal is the absence of the injected Customer Memory header.)
    assert "Customer Memory" not in captured[0]

    # --- §6.4 observability: the turn note carries the binding_key + slot NAMES, and
    # never the value (PII stays out of logs). -------------------------------------
    notes = [
        r.getMessage()
        for r in caplog.records
        if r.name == "hermes_runtime.openrouter" and "Customer Memory turn" in r.getMessage()
    ]
    assert any(
        f"binding_key={_VERIFIED_ID}" in n and _VERIFIED_SLOT in n for n in notes
    )
    assert all(_VERIFIED_PREF not in n for n in notes)  # slot values never logged


# --------------------------------------------------------------------------- #
# R3 / PAC-5 — cross-customer isolation, both directions.
# --------------------------------------------------------------------------- #
def test_cross_customer_isolation_both_directions(datastore, monkeypatch) -> None:
    """Two verified customers, each with their own preference. Each turn injects only
    its OWN memory: A sees A and NOT B; B sees B and NOT A (presence-only-for-owner,
    in both directions — absence-for-A alone is not enough)."""
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    driver, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)

    id_a, pref_a = "gid://shopify/Customer/8001", "call me on my cell, mornings only"
    id_b, pref_b = "gid://shopify/Customer/8002", "email me, never text"
    _write_preference(
        driver,
        identity={"outcome": "verified_customer", "shopify_customer_id": id_a},
        key=_VERIFIED_SLOT,
        value=pref_a,
    )
    _write_preference(
        driver,
        identity={"outcome": "verified_customer", "shopify_customer_id": id_b},
        key="channel_preference",
        value=pref_b,
    )

    def _verified_context(shopify_id: str, phone: str):
        return SimpleNamespace(
            conversation_id=f"conv-{shopify_id[-4:]}",
            sms_session_id=None,
            from_phone=phone,
            session_identity_snapshot=SessionIdentitySnapshot(
                outcome="verified_customer",
                resolved_at="2026-07-13T00:00:00Z",
                shopify_customer_id=shopify_id,
            ),
        )

    msg_a = _capture_injection_only(
        monkeypatch, store=store, context=_verified_context(id_a, "+14165550001")
    )
    msg_b = _capture_injection_only(
        monkeypatch, store=store, context=_verified_context(id_b, "+14165550002")
    )

    assert pref_a in msg_a and pref_b not in msg_a  # A sees only A
    assert pref_b in msg_b and pref_a not in msg_b  # B sees only B


# --------------------------------------------------------------------------- #
# R5 / PAC-3 — provisional → verified merge chain (seamless continuity).
# --------------------------------------------------------------------------- #
def test_provisional_to_verified_merge_chain(datastore, monkeypatch) -> None:
    """An unmatched caller states a preference (bound provisionally). A later turn
    resolves them to a verified customer on the SAME phone: the preference is honored
    under the verified id WITHOUT being re-asked, and the provisional rows are gone —
    all read back from Postgres, plus exactly one merge-audit row (idempotent RK-5)."""
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    driver, conn, _ = datastore
    store = PostgresGatewayStore(connection=conn)

    phone = "+14165550170"
    verified_id = "gid://shopify/Customer/5005"
    provisional_key = f"provisional:sms:{normalize_e164(phone)}"

    # The unmatched caller's turn stores a preference against the channel identity.
    _write_preference(
        driver,
        identity={"channel": "sms", "channel_identity": phone},
        key=_PROVISIONAL_SLOT,
        value=_PROVISIONAL_PREF,
    )

    # A later turn now resolves the SAME phone to a verified customer (identity link):
    # the async turn merges provisional -> verified before injecting.
    verified_context = SimpleNamespace(
        conversation_id="conv-merge",
        sms_session_id=None,
        from_phone=phone,
        session_identity_snapshot=SessionIdentitySnapshot(
            outcome="verified_customer",
            resolved_at="2026-07-13T00:00:00Z",
            shopify_customer_id=verified_id,
        ),
    )
    injected = _capture_injection_only(monkeypatch, store=store, context=verified_context)

    # Honored under the verified id, without re-asking (PAC-3).
    assert _PROVISIONAL_PREF in injected

    with conn.cursor() as cur:
        # The preference now lives under the verified key (source records the merge).
        cur.execute(
            "SELECT slot_value, source FROM customer_memory_slot "
            "WHERE binding_key = %s AND slot_name = %s",
            (verified_id, _PROVISIONAL_SLOT),
        )
        assert cur.fetchone() == (_PROVISIONAL_PREF, "merged_provisional")
        # The provisional copies are gone.
        cur.execute(
            "SELECT count(*) FROM customer_memory_slot WHERE binding_key = %s",
            (provisional_key,),
        )
        assert cur.fetchone()[0] == 0
        # Exactly one merge-audit row for this transition (idempotent).
        cur.execute(
            "SELECT count(*) FROM customer_memory_merge_audit "
            "WHERE provisional_key = %s AND verified_key = %s",
            (provisional_key, verified_id),
        )
        assert cur.fetchone()[0] == 1


# --------------------------------------------------------------------------- #
# §6.0.4 — dormancy tripwire (RED-capable).
# --------------------------------------------------------------------------- #
def test_dormancy_tripwire_is_red_when_driver_disabled(datastore, monkeypatch) -> None:
    """The SAME activation E2E with the composite driver DISABLED (TOOL_BACKEND unset)
    must observe the DORMANT state: the write lands in the ephemeral mock (NO Postgres
    row) and the re-entry injects NO memory.

    RED-capable by construction: these assertions encode dormancy, so they pass ONLY
    while memory is dormant. If the composite driver were wrongly active the write
    would persist (row count 1, not 0) and the re-entry would carry the preference —
    both assertions would FAIL. CI treats a green-when-active flip as the alarm."""
    monkeypatch.delenv("TOOL_BACKEND", raising=False)  # composite driver OFF
    driver, conn, _ = datastore
    # Route the live turn's toee_customer_memory overlay at the fixture connection —
    # mirrors the matrix test's seam above. When correctly dormant this is inert:
    # _customer_memory_extra_drivers() short-circuits on memory_enabled() before ever
    # calling select_tool_driver (both now live in tool_backend.py, Standards fix #1).
    # But if activation regresses (memory wrongly active), this makes the regressed
    # write land in THIS throwaway schema instead of a fresh DSN connection's default
    # `public` schema — so the readback below actually flips RED instead of missing
    # the write entirely and staying falsely green.
    monkeypatch.setattr(tool_backend_mod, "select_tool_driver", lambda *_a, **_k: driver)

    store = PostgresGatewayStore(connection=conn)
    sent: list[tuple[str, str]] = []
    captured = _capture_injections(monkeypatch)
    run_turn = make_openrouter_run_turn(
        config=_CONFIG,
        store=store,
        openai_factory=_scripted_openai_factory(
            [
                _upsert_call(slot=_VERIFIED_SLOT, value=_VERIFIED_PREF),  # R1 write attempt
                {"content": "Okay."},                                     # R1 reply
                {"content": "Welcome back."},                             # R2 reply
            ]
        ),
    )
    app = _build_app(store=store, conn=conn, run_turn=run_turn, sent=sent)
    client = TestClient(app)

    assert _post(
        client,
        _inbound(
            body="Text me after 5pm.",
            from_phone=_VERIFIED_PHONE,
            event_id="evt-dorm-1",
            conversation_id="conv-dorm",
        ),
    ).status_code == 200
    assert _post(
        client,
        _inbound(
            body="It's me again.",
            from_phone=_VERIFIED_PHONE,
            event_id="evt-dorm-2",
            conversation_id="conv-dorm",
        ),
    ).status_code == 200

    assert len(sent) == 2  # dormant memory never blocks a reply (turn still completes)

    # Dormant #1: the write did NOT reach Postgres (it landed in the mock store).
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM customer_memory_slot WHERE binding_key = %s",
            (_VERIFIED_ID,),
        )
        assert cur.fetchone()[0] == 0
    # Dormant #2: the re-entry injected no Customer Memory block.
    assert "Customer Memory" not in captured[1]
    assert _VERIFIED_PREF not in captured[1]


# --------------------------------------------------------------------------- #
# FR-7 — graceful degradation (memory is never a hard dependency of answering).
# --------------------------------------------------------------------------- #
def test_no_datastore_turn_replies_without_memory_artifact(monkeypatch) -> None:
    """A no-DB turn (TOOL_BACKEND unset) completes and replies with NO memory artifact
    and no error — memory is silently unavailable, never a hard dependency. No
    Postgres needed: the disabled gate means the store is never touched."""
    monkeypatch.delenv("TOOL_BACKEND", raising=False)
    captured = _capture_injections(monkeypatch)
    reply = "We stock 225/65R17 — want a payment link?"
    run_turn = make_openrouter_run_turn(
        config=_CONFIG,
        store=None,
        openai_factory=_scripted_openai_factory([{"content": reply}]),
    )
    context = SimpleNamespace(
        conversation_id="conv-nodb",
        sms_session_id=None,
        from_phone=_UNMATCHED_PHONE,
        session_identity_snapshot=None,
    )

    turn = run_turn(context, "Do you have 225/65R17?")

    assert turn["final_response"] == reply       # completed and replied
    assert "Customer Memory" not in captured[0]  # no artifact for a memory-less turn


def test_memory_read_error_still_replies_and_warns(monkeypatch, caplog) -> None:
    """When the memory-store READ raises, the turn still completes and replies: the
    ``_load_turn_memory`` swallow degrades to "no memory injected" and logs a WARNING
    (the swallow is never silent — S11). Memory enabled, so the gate does not skip
    the read; a provisional caller so no merge is attempted (isolates the read)."""
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    # Keep the write overlay off Postgres (no tool call happens anyway); this also
    # avoids resolving a DSN, so the test needs no database. select_tool_driver lives
    # behind tool_backend._customer_memory_extra_drivers (Standards fix #1).
    monkeypatch.setattr(
        tool_backend_mod,
        "select_tool_driver",
        lambda *_a, **_k: MockDriver(create_all_mock_handlers()),
    )
    captured = _capture_injections(monkeypatch)

    class _RaisingReadStore:
        def load_customer_memory(self, binding_key):
            raise RuntimeError("simulated datastore read failure")

    reply = "Happy to help — what size are you after?"
    run_turn = make_openrouter_run_turn(
        config=_CONFIG,
        store=_RaisingReadStore(),
        openai_factory=_scripted_openai_factory([{"content": reply}]),
    )
    context = SimpleNamespace(
        conversation_id="conv-readfail",
        sms_session_id=None,
        from_phone=_UNMATCHED_PHONE,  # provisional -> merge is skipped, read is exercised
        session_identity_snapshot=None,
    )

    with caplog.at_level(logging.WARNING, logger="hermes_runtime.openrouter"):
        turn = run_turn(context, "Hi")

    assert turn["final_response"] == reply       # still completes and replies
    assert "Customer Memory" not in captured[0]  # degraded to no injection
    assert "Customer Memory read failed" in caplog.text  # swallow is not silent
