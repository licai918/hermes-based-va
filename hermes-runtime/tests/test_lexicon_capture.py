"""0.0.5 S04 (FR-4, US4): the two capture forks and where each one is allowed to route.

Two forks, and the whole slice is about **which layer each one may reach**:

* the **gateway-side capture fork** (new) — after an EXTERNAL customer turn, off the
  turn's thread, restricted to ``[propose_lexicon_entry]``. It can reach **L7 only**.
* the **copilot review fork** (S23-0.0.3, already shipped) — after a copilot draft
  turn. It could reach L6 only; it can now reach **L6 or L7**, and must still be able
  to reach **neither**.

**A routing test whose fixture only contains cases that route somewhere cannot catch a
fork that routes everything to one place.** So every destination below has at least one
input that must NOT reach it, and one input reaches nothing at all:

| input | L6 | L7 |
| --- | --- | --- |
| copilot fork proposes an operational learning | ✅ | ✖ must stay empty |
| copilot fork proposes a surface→canonical mapping | ✖ must stay empty | ✅ |
| copilot fork records nothing | ✖ | ✖ |
| gateway fork proposes a mapping | ✖ **structurally unreachable** | ✅ |
| gateway fork *tries* the L6 tool | ✖ the tool is not on its surface | ✖ |

The model is scripted everywhere, so the routing under test is the FORK's (its toolset,
its extraction, its gate) and never a model's judgement.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hermes_runtime.copilot_turn import (
    _REVIEW_SYSTEM_MESSAGE,
    l6_review_payload,
    review_fork_system_message,
    review_fork_tool_names,
    run_l6_review_job,
)
from hermes_runtime.job_queue import L7_CAPTURE_JOB_TYPE
from hermes_runtime.lexicon_capture import (
    CAPTURE_FORK_TOOL_NAMES,
    RECENT_EXCHANGE_LIMIT,
    _CAPTURE_SYSTEM_MESSAGE,
    format_exchange,
    l7_capture_payload,
    run_l7_capture_job,
)
from hermes_runtime.live import _scripted_openai_factory
from hermes_runtime.openrouter import (
    OPENROUTER_PRIMARY_MODEL,
    OpenRouterConfig,
    make_openrouter_run_turn,
)
from hermes_runtime.tool_backend import lexicon_capture_enabled

_CONFIG = OpenRouterConfig(
    base_url="https://openrouter.ai/api/v1",
    api_key="sk-or-test",
    model=OPENROUTER_PRIMARY_MODEL,
)

_LEXICON_TOOL = "toee_semantic_lexicon__propose_lexicon_entry"
_EXPERIENCE_TOOL = "toee_agent_experience__propose_experience"


@pytest.fixture(autouse=True)
def _clean_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """No real provider, and no dev box's env leaking into a gate under test."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_EXPERIENCE_LEARNING", raising=False)
    monkeypatch.delenv("LEXICON_CAPTURE", raising=False)
    monkeypatch.delenv("TOOL_BACKEND", raising=False)


@pytest.fixture
def mock_backed_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn the capture flag ON while keeping the governed write on a mock driver.

    ``_lexicon_capture_extra_drivers`` builds a real ``PostgresDriver`` when the flag
    is on, so a DB-free routing test would otherwise be testing a connection error.
    Patching ``select_tool_driver`` (the ``test_copilot_learning_loop`` convention)
    keeps the overlay INSTALLED — the governed call, its validation and its write scan
    all run for real — and only swaps where the row lands.
    """
    import hermes_runtime.tool_backend as tool_backend_mod
    from toee_hermes.drivers.mock import MockDriver, create_all_mock_handlers

    monkeypatch.setenv("LEXICON_CAPTURE", "on")
    driver = MockDriver(create_all_mock_handlers())
    monkeypatch.setattr(tool_backend_mod, "select_tool_driver", lambda *_a, **_k: driver)


def _propose_lexicon(**overrides: object) -> dict:
    arguments = {
        "domain": "tire",
        "entry_kind": "alias",
        "surface_form": "2055516",
        "canonical_form": "205/55R16",
        "evidence": "Agent: do you mean 205/55R16? Customer: yes that's the one",
        "proposer_context": {"case_id": "case_capture"},
    }
    arguments.update(overrides)  # type: ignore[arg-type]
    return {"tool_calls": [{"name": _LEXICON_TOOL, "arguments": arguments}]}


_PROPOSE_EXPERIENCE = {
    "tool_calls": [
        {
            "name": _EXPERIENCE_TOOL,
            "arguments": {
                "kind": "procedure",
                "content": "Check get_delivery_status with the bare order number first.",
            },
        }
    ]
}
_FORK_DONE = {"content": "Recorded what there was to record."}
_NOTHING = {"content": "Nothing durable in this turn."}


def _context(**overrides: object) -> SimpleNamespace:
    fields: dict = {
        "event_id": "evt_capture",
        "conversation_id": "+14165550188",
        "sms_session_id": "sess_capture",
        "customer_thread_id": "thread_capture",
        "from_phone": "+14165550188",
        "session_identity_snapshot": None,
        "channel": "simpletexting_sms",
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


class _RecordingQueue:
    """Records enqueues in order (the DB-free stand-in for PostgresJobQueue)."""

    def __init__(self) -> None:
        self.jobs: list[tuple[dict, str, int]] = []

    def enqueue(self, payload, *, job_type, max_attempts=3, **_kwargs) -> str:
        self.jobs.append((dict(payload), job_type, max_attempts))
        return f"job_{len(self.jobs)}"


class _ExchangeStore:
    """A gateway store that only knows the recent exchange (the fork's one read)."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, int]] = []

    def load_recent_exchange(self, sms_session_id: str, *, limit: int) -> list[dict]:
        self.calls.append((sms_session_id, limit))
        return self.rows


_CONFIRM_EXCHANGE = [
    {"author": "customer", "body": "need 4 of the 2055516"},
    {"author": "hermes", "body": "Just to confirm — do you mean 205/55R16?"},
    {"author": "customer", "body": "yes that's the one"},
    {"author": "hermes", "body": "Great, 205/55R16 it is."},
]
_NO_CONFIRM_EXCHANGE = [
    {"author": "customer", "body": "what time do you close saturday?"},
    {"author": "hermes", "body": "We're open until 4pm on Saturdays."},
]


def _run_gateway_turn(monkeypatch, *, queue, context=None, inbound="hello"):
    """Run the external turn with the agent loop stubbed; return its result."""
    import hermes_runtime.openrouter as openrouter_mod

    monkeypatch.setattr(
        openrouter_mod,
        "run_agent_turn",
        lambda **_kwargs: {"final_response": "A reply for the customer.", "messages": []},
    )
    run_turn = make_openrouter_run_turn(config=_CONFIG, store=None, queue=queue)
    return run_turn(context or _context(), inbound)


# --- gateway fork: the TRIGGER (enqueue, gate, resilience) --------------------


def test_the_gateway_turn_enqueues_one_l7_capture_job_when_the_flag_is_on(monkeypatch):
    monkeypatch.setenv("LEXICON_CAPTURE", "on")
    queue = _RecordingQueue()

    result = _run_gateway_turn(monkeypatch, queue=queue)

    assert result["final_response"] == "A reply for the customer."
    assert len(queue.jobs) == 1
    payload, job_type, max_attempts = queue.jobs[0]
    assert job_type == L7_CAPTURE_JOB_TYPE
    assert payload["sms_session_id"] == "sess_capture"
    assert payload["event_id"] == "evt_capture"
    # ONE attempt: the fork WRITES, so a retry could land a second proposed entry
    # for one turn (the l6_review precedent).
    assert max_attempts == 1


def test_the_capture_payload_carries_identity_keys_and_no_customer_text(monkeypatch):
    # The `job` table has no retention story yet (ADR-0153 fix #5), so the customer's
    # own words must not land in it. The fork reads the exchange from message_turn on
    # the worker instead -- where it is already stored, under its own retention.
    monkeypatch.setenv("LEXICON_CAPTURE", "on")
    queue = _RecordingQueue()

    _run_gateway_turn(monkeypatch, queue=queue, inbound="my number is 416-555-0199")

    payload, _type, _attempts = queue.jobs[0]
    assert "416-555-0199" not in repr(payload)
    assert set(payload) == {"event_id", "conversation_ref", "sms_session_id"}


def test_the_gateway_turn_does_not_enqueue_when_the_capture_flag_is_off(monkeypatch):
    # EVAL DETERMINISM: the record/replay path sets no flag, so nothing is enqueued
    # and the turn result is byte-identical to the pre-S04 shape.
    assert lexicon_capture_enabled() is False
    queue = _RecordingQueue()

    result = _run_gateway_turn(monkeypatch, queue=queue)

    assert result == {"final_response": "A reply for the customer.", "messages": []}
    assert queue.jobs == []


def test_the_eval_record_path_does_not_go_through_the_capture_enqueue_seam():
    # The stronger half of the eval pin, and the one a flag cannot leak past: the
    # record path builds its own turn (boot_profile_eval + run_agent_turn) and never
    # touches make_openrouter_run_turn, which is the ONLY thing that enqueues an
    # l7_capture job. Wiring the record path through it would redden this.
    import inspect

    from hermes_runtime import eval_record

    assert "make_openrouter_run_turn" not in inspect.getsource(eval_record)


def test_a_failing_enqueue_never_fails_the_customer_turn(monkeypatch):
    # TURN RESILIENCE: the reply is already produced and about to be delivered. A
    # queue that is down is caught, logged and swallowed.
    monkeypatch.setenv("LEXICON_CAPTURE", "on")

    class _DeadQueue:
        def enqueue(self, *_args, **_kwargs):
            raise RuntimeError("connection refused")

    result = _run_gateway_turn(monkeypatch, queue=_DeadQueue())

    assert result["final_response"] == "A reply for the customer."


# --- gateway fork: WHERE IT MAY ROUTE ----------------------------------------


def test_the_gateway_capture_fork_is_restricted_to_the_one_lexicon_propose_tool():
    assert CAPTURE_FORK_TOOL_NAMES == (_LEXICON_TOOL,)


@pytest.mark.parametrize(
    "forbidden",
    [
        _EXPERIENCE_TOOL,
        "toee_customer_memory__upsert_preference",
        "toee_review_inbox__propose_review_item",
        "toee_semantic_lexicon__confirm_lexicon_entry",
        "toee_sms_reply__send_message",
        "toee_case__create_case",
    ],
)
def test_the_gateway_capture_fork_cannot_reach_any_other_governed_surface(forbidden):
    # S13's precedent: name the layers it must NOT touch, one per case, rather than
    # asserting only the one it may. L4 (a customer's own memory), L6 (shared
    # operational learnings), the review inbox and every DECIDE action are all off
    # this fork's surface -- a capture proposes, it never confirms (NFR-3).
    assert forbidden not in CAPTURE_FORK_TOOL_NAMES


def test_a_confirm_exchange_yields_one_proposed_lexicon_entry(mock_backed_capture):
    proposals = run_l7_capture_job(
        {"sms_session_id": "sess_capture", "conversation_ref": "+1416", "event_id": "e1"},
        store=_ExchangeStore(_CONFIRM_EXCHANGE),
        capture_scripted_completions=[_propose_lexicon(), _FORK_DONE],
    )

    assert proposals == [
        {
            "domain": "tire",
            "entry_kind": "alias",
            "surface_form": "2055516",
            "canonical_form": "205/55R16",
            "status": "proposed",
        }
    ]


def test_a_transcript_with_no_confirm_yields_nothing(mock_backed_capture):
    store = _ExchangeStore(_NO_CONFIRM_EXCHANGE)

    assert (
        run_l7_capture_job(
            {"sms_session_id": "sess_capture"},
            store=store,
            capture_scripted_completions=[_NOTHING],
        )
        == []
    )
    # ...and the fork really did see the exchange it declined to capture from, so
    # "nothing" is a decision rather than an empty prompt.
    assert store.calls == [("sess_capture", RECENT_EXCHANGE_LIMIT)]


def test_an_l6_shaped_call_from_the_gateway_fork_produces_no_l7_proposal(
    mock_backed_capture,
):
    # The EXTRACTOR's routing negative: a `propose_experience` call in the fork's
    # transcript yields no lexicon proposal, so the two layers' captures cannot be
    # confused for one another. It does NOT prove the toolset restriction -- with
    # an unrestricted toolset this call would succeed against the default mock and
    # still extract to nothing. The two tests below are what pin the restriction.
    assert (
        run_l7_capture_job(
            {"sms_session_id": "sess_capture"},
            store=_ExchangeStore(_CONFIRM_EXCHANGE),
            capture_scripted_completions=[_PROPOSE_EXPERIENCE, _FORK_DONE],
        )
        == []
    )


def _fork_tool_surface(monkeypatch, module, run) -> tuple[list[str], bool]:
    """What a fork's CALL SITE really handed the agent loop: ``(names, exclusive)``.

    ``CAPTURE_FORK_TOOL_NAMES`` and ``review_fork_tool_names`` are the *stated*
    surface; this reads the one the model could actually reach, and BOTH halves
    are load-bearing. A bait proved it: unrestricting the call site left every
    other assertion in this file green, because a stray governed call simply
    extracts to nothing -- and a second bait showed that without
    ``tools_exclusive`` the names are UNIONed into the agent's existing
    ``valid_tool_names``, so a "restricted" fork could still dispatch every tool
    the profile booted. ``module`` is patched rather than ``live`` because both
    forks import ``run_scripted_agent`` by name at import time.
    """
    seen: dict[str, object] = {}

    def capture(*, governed_tool_names, tools_exclusive=False, **_kwargs):
        seen["names"] = sorted(governed_tool_names)
        seen["exclusive"] = tools_exclusive
        return {"final_response": "", "messages": []}

    monkeypatch.setattr(module, "run_scripted_agent", capture)
    run()
    return seen["names"], seen["exclusive"]  # type: ignore[return-value]


def test_the_gateway_fork_hands_the_model_only_the_lexicon_propose_tool(
    mock_backed_capture, monkeypatch
):
    import hermes_runtime.lexicon_capture as capture_mod

    names, exclusive = _fork_tool_surface(
        monkeypatch,
        capture_mod,
        lambda: run_l7_capture_job(
            {"sms_session_id": "sess_capture"},
            store=_ExchangeStore(_CONFIRM_EXCHANGE),
            capture_scripted_completions=[_FORK_DONE],
        ),
    )

    assert names == [_LEXICON_TOOL]
    # ...and it is a FENCE, not an offer. Without this the line above is decoration.
    assert exclusive is True


def test_the_review_fork_hands_the_model_only_the_two_propose_tools(
    mock_backed_capture, monkeypatch
):
    import hermes_runtime.copilot_turn as copilot_mod

    names, exclusive = _fork_tool_surface(
        monkeypatch, copilot_mod, lambda: _review(_FORK_DONE)
    )

    assert names == sorted([_EXPERIENCE_TOOL, _LEXICON_TOOL])
    assert exclusive is True


def test_an_empty_conversation_captures_nothing_and_never_reaches_a_model(
    mock_backed_capture,
):
    # Fail-open (NFR-5): no session, no rows, or a store that cannot answer degrades
    # to "captured nothing" and never raises into the worker.
    exploding = [{"content": "the model must not be reached"}]
    assert run_l7_capture_job({}, store=_ExchangeStore([]), capture_scripted_completions=exploding) == []
    assert run_l7_capture_job({"sms_session_id": "s"}, store=object()) == []


def test_the_capture_prompt_asks_for_confirmed_clarifications_and_forbids_contact_details():
    lowered = _CAPTURE_SYSTEM_MESSAGE.lower()
    assert "confirm" in lowered
    assert "propose_lexicon_entry" in _CAPTURE_SYSTEM_MESSAGE
    # D2 amendment 3: an L6 proposer_context VALUE carrying real contact details
    # hard-rejects the whole write, and an L7 one is redacted -- either way the fork
    # must be told to carry ids and refs, never a callback number.
    assert "phone" in lowered or "contact details" in lowered


def test_the_capture_fork_renders_the_exchange_with_both_speakers():
    text = format_exchange(_CONFIRM_EXCHANGE)

    assert "Customer: need 4 of the 2055516" in text
    assert "Agent: Just to confirm — do you mean 205/55R16?" in text


def test_an_l7_capture_job_on_a_worker_with_capture_off_fails_loudly(monkeypatch):
    # The flag-split failure, closed on the sibling path 0.0.4 S04 opened for L6:
    # the job's EXISTENCE proves LEXICON_CAPTURE was on in the gateway process, so
    # a worker where it reads OFF would run the fork against a throwaway mock and
    # report `succeeded` having written no semantic_lexicon row.
    from hermes_runtime.background_worker import L6ReviewMisconfigured, job_bodies

    body = job_bodies()[L7_CAPTURE_JOB_TYPE]

    with pytest.raises(L6ReviewMisconfigured, match="LEXICON_CAPTURE is off"):
        body({"sms_session_id": "sess_capture"})

    # ...and with the flag on but no model, the same guard fires for the other
    # half: a keyless fork proposes nothing and would also report success.
    monkeypatch.setenv("LEXICON_CAPTURE", "on")
    with pytest.raises(L6ReviewMisconfigured, match="no review model"):
        body({"sms_session_id": "sess_capture"})


def test_the_capture_payload_is_built_from_the_turn_context():
    assert l7_capture_payload(_context()) == {
        "event_id": "evt_capture",
        "conversation_ref": "+14165550188",
        "sms_session_id": "sess_capture",
    }


# --- copilot fork: L6, L7, or NEITHER ----------------------------------------


def _review(*completions: dict) -> dict:
    return run_l6_review_job(
        l6_review_payload("case_route", {"draft": "A draft.", "messages": []}),
        review_scripted_completions=list(completions),
    )


def test_the_copilot_fork_routes_an_operational_learning_to_l6_and_not_to_l7(
    mock_backed_capture,
):
    routed = _review(_PROPOSE_EXPERIENCE, _FORK_DONE)

    assert [p["kind"] for p in routed["experience"]] == ["procedure"]
    assert routed["lexicon"] == []


def test_the_copilot_fork_routes_a_surface_to_canonical_mapping_to_l7_and_not_to_l6(
    mock_backed_capture,
):
    routed = _review(_propose_lexicon(), _FORK_DONE)

    assert routed["experience"] == []
    assert [p["surface_form"] for p in routed["lexicon"]] == ["2055516"]


def test_the_copilot_fork_routes_nothing_when_the_turn_taught_nothing(
    mock_backed_capture,
):
    assert _review(_NOTHING) == {"experience": [], "lexicon": []}


def test_the_copilot_fork_carries_no_lexicon_surface_when_capture_is_off():
    # With LEXICON_CAPTURE off (the default) the review fork is byte-identical to
    # the S23-0.0.3 one: the tool is off its surface AND the prompt never mentions
    # it, so it cannot advertise a destination it has no way to reach.
    names = review_fork_tool_names([_EXPERIENCE_TOOL, _LEXICON_TOOL, "toee_case__create_case"])

    assert names == [_EXPERIENCE_TOOL]
    assert review_fork_system_message() == _REVIEW_SYSTEM_MESSAGE


def test_the_copilot_fork_gains_exactly_one_lexicon_tool_when_capture_is_on(
    monkeypatch,
):
    monkeypatch.setenv("LEXICON_CAPTURE", "on")

    names = review_fork_tool_names(
        [
            _EXPERIENCE_TOOL,
            _LEXICON_TOOL,
            "toee_semantic_lexicon__confirm_lexicon_entry",
            "toee_customer_memory__upsert_preference",
            "toee_case__create_case",
        ]
    )

    assert names == [_EXPERIENCE_TOOL, _LEXICON_TOOL]
    assert "propose_lexicon_entry" in review_fork_system_message()


def test_neither_fork_can_reach_any_other_tool_the_profile_registers(mock_backed_capture):
    # The whole INTERNAL surface, not a hand-written list: a later slice that
    # allowlists a new tool, or un-excludes a DECIDE action, cannot silently join
    # either fork. Run with capture ON so BOTH destinations are live -- with it off
    # the L7 half would be absent for the wrong reason and the test would pass
    # while proving less.
    from hermes_runtime.boot import boot_profile
    from toee_hermes.plugin.profiles import INTERNAL

    registered = boot_profile(INTERNAL).tool_names
    reachable = set(review_fork_tool_names(registered)) | set(CAPTURE_FORK_TOOL_NAMES)

    assert reachable == {_EXPERIENCE_TOOL, _LEXICON_TOOL}
    # The fixture has to be able to tell "narrowed" from "there was nothing else":
    # the profile registers a couple of dozen tools, and every one of the rest is
    # excluded by the two lines above.
    assert len(registered) > 10
    assert "toee_customer_memory__upsert_preference" in registered


# --- Live Postgres: the proposal really lands, proposed and unconfirmed -------


def test_the_capture_fork_persists_a_proposed_lexicon_row(datastore, monkeypatch):
    driver, conn, _ = datastore
    monkeypatch.setenv("LEXICON_CAPTURE", "on")
    import hermes_runtime.tool_backend as tool_backend_mod

    monkeypatch.setattr(tool_backend_mod, "select_tool_driver", lambda *_a, **_k: driver)

    proposals = run_l7_capture_job(
        {"sms_session_id": "sess_capture"},
        store=_ExchangeStore(_CONFIRM_EXCHANGE),
        # The fork tries to forge admin provenance and a confirmed status; ADR-0148
        # says both come from the framework, so neither may survive.
        capture_scripted_completions=[
            _propose_lexicon(provenance="admin_manual", status="confirmed"),
            _FORK_DONE,
        ],
    )

    assert proposals and proposals[0]["status"] == "proposed"
    with conn.cursor() as cur:
        # Scoped to the captured row: migration 0024 seeds the owner's curated
        # domain-#1 vocabulary into this table, so an unscoped SELECT would read
        # a seeded `admin_manual` row and pass for the wrong reason.
        cur.execute(
            "SELECT surface_form, canonical_form, status, provenance, "
            "decider_account_id, decided_at, evidence FROM semantic_lexicon "
            "WHERE surface_form = '2055516'"
        )
        rows = cur.fetchall()
    assert len(rows) == 1
    surface, canonical, status, provenance, decider, decided_at, evidence = rows[0]
    assert (surface, canonical) == ("2055516", "205/55R16")
    # NFR-3: a capture PROPOSES. It never confirms, and nobody decided it.
    assert status == "proposed"
    assert decider is None and decided_at is None
    # ADR-0148: framework-derived from the dispatch route, never the forged param.
    assert provenance == "conversation_confirmed"
    # FR-4: the exchange rides along as the evidence an admin decides on.
    assert "205/55R16" in evidence


def test_a_capture_evidence_phone_number_is_redacted_not_rejected(datastore, monkeypatch):
    # D2: L7 evidence REDACTS PII in place rather than rejecting the entry -- the
    # governance evidence is exactly what the admin needs in order to decide.
    driver, conn, _ = datastore
    monkeypatch.setenv("LEXICON_CAPTURE", "on")
    import hermes_runtime.tool_backend as tool_backend_mod

    monkeypatch.setattr(tool_backend_mod, "select_tool_driver", lambda *_a, **_k: driver)

    run_l7_capture_job(
        {"sms_session_id": "sess_capture"},
        store=_ExchangeStore(_CONFIRM_EXCHANGE),
        capture_scripted_completions=[
            _propose_lexicon(evidence="yes 205/55R16 — call me on 416-555-0199"),
            _FORK_DONE,
        ],
    )

    with conn.cursor() as cur:
        cur.execute(
            "SELECT evidence, pii_redacted FROM semantic_lexicon "
            "WHERE surface_form = '2055516'"
        )
        evidence, pii_redacted = cur.fetchone()
    assert "416-555-0199" not in evidence
    # ...and the entry SURVIVED with the rest of its evidence intact -- redact, not
    # reject. An empty read here would mean the write was blocked instead.
    assert "205/55R16" in evidence
    assert pii_redacted is True


def test_the_recent_exchange_read_is_scoped_to_one_session_newest_last(temp_schema_conn):
    from hermes_runtime.datastore.migrate import run_migrations
    from hermes_runtime.postgres_gateway_store import PostgresGatewayStore

    conn, _schema = temp_schema_conn
    run_migrations(conn)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO customer_thread (id, channel, channel_identity) "
            "VALUES ('thr_x', 'sms', '+14165550188')"
        )
        for session in ("sess_x", "sess_other"):
            cur.execute(
                "INSERT INTO sms_session (id, customer_thread_id, expires_at) "
                "VALUES (%s, 'thr_x', now() + interval '1 hour')",
                (session,),
            )
        rows = [
            ("mt_1", "sess_x", "inbound", "customer", "need 2055516"),
            ("mt_2", "sess_x", "outbound", "hermes", "do you mean 205/55R16?"),
            ("mt_3", "sess_other", "inbound", "customer", "a different conversation"),
        ]
        for turn_id, session, direction, author, body in rows:
            cur.execute(
                "INSERT INTO message_turn (id, sms_session_id, customer_thread_id, "
                "direction, author, body) VALUES (%s, %s, 'thr_x', %s, %s, %s)",
                (turn_id, session, direction, author, body),
            )
    conn.commit()

    exchange = PostgresGatewayStore(connection=conn).load_recent_exchange(
        "sess_x", limit=RECENT_EXCHANGE_LIMIT
    )

    # Chronological, this session only -- the other conversation must not leak in.
    assert [row["body"] for row in exchange] == [
        "need 2055516",
        "do you mean 205/55R16?",
    ]
