"""S25 (FR-25/26, NFR-5/6): confirmed-L6-entry injection at the two turn seams.

The make-or-break properties this file pins:

1. ONLY ``confirmed`` entries are injected -- ``proposed``/``rejected`` never reach
   any turn (asserted for BOTH the copilot draft turn AND the external turn, and
   proven at the source by the live-Postgres ``load_confirmed_experience`` filter).
2. TWO INDEPENDENT FLAGS -- the external read is disable-able WITHOUT touching the
   copilot path; each seam reads only its OWN flag; both DEFAULT OFF.
3. EXTERNAL IS READ-ONLY -- it reads confirmed learnings, never proposes (S23 kept
   propose off the external profile; nothing added here).
4. TURN RESILIENCE (NFR-5) -- an injection read that raises degrades to SKIP; the
   turn completes with its draft/reply intact.
5. EVAL DETERMINISM (NFR-6) -- the flags default OFF and the eval record path never
   surfaces a confirmed learning, so the deterministic replay gate stays green.
6. DRAFT-TURN-INERT (folded-in S23 follow-up) -- a draft-side ``propose_experience``
   call persists NOTHING; only the review fork ever writes.

The model boundary is the scripted path so every injected-content assertion is
deterministic; ``run_scripted_agent`` / ``run_agent_turn`` are captured so the
assertion is on the exact injected user message, not a model reply.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hermes_runtime.copilot_turn import make_copilot_run_turn
from hermes_runtime.eval_record import scenario_user_message
from hermes_runtime.live import _scripted_openai_factory
from hermes_runtime.openrouter import (
    OPENROUTER_PRIMARY_MODEL,
    OpenRouterConfig,
    make_openrouter_run_turn,
)
from hermes_runtime.tool_backend import (
    agent_experience_external_injection_enabled,
    agent_experience_injection_enabled,
    load_confirmed_experience,
)

_FENCE = "<confirmed_operational_learnings>"
_CONFIRMED = [
    {"content": "For EasyRoutes gaps, check get_delivery_status first.", "kind": "procedure"},
    {"content": "Confirm the ship-to ZIP before quoting freight.", "kind": "note"},
]
_CONFIG = OpenRouterConfig(
    base_url="https://openrouter.ai/api/v1",
    api_key="sk-or-test",
    model=OPENROUTER_PRIMARY_MODEL,
)


class _FakeStore:
    """A gateway store stub whose confirmed-read is controllable per test.

    ``load_case_identity``/``load_customer_memory`` answer benignly so the memory
    path (gated off by TOOL_BACKEND-unset in these tests) never interferes; the
    confirmed read returns the seeded entries, or raises for the resilience test.
    """

    def __init__(self, entries=(), *, raise_on_read: bool = False) -> None:
        self._entries = list(entries)
        self._raise = raise_on_read

    def load_case_identity(self, case_id):  # copilot seam
        return None

    def load_customer_memory(self, binding_key):  # both seams (memory disabled here)
        return []

    def load_confirmed_experience(self):
        if self._raise:
            raise RuntimeError("datastore down")
        return list(self._entries)


@pytest.fixture(autouse=True)
def _clean_l6_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # No real provider, no memory backend, and both L6 injection axes cleared so a
    # dev box's env can't leak into a test. Each test opts IN to the flag it needs.
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("TOOL_BACKEND", raising=False)
    monkeypatch.delenv("AGENT_EXPERIENCE_INJECTION", raising=False)
    monkeypatch.delenv("AGENT_EXPERIENCE_EXTERNAL_INJECTION", raising=False)
    monkeypatch.delenv("AGENT_EXPERIENCE_LEARNING", raising=False)


# --- copilot draft turn --------------------------------------------------------


def _run_copilot_capturing(monkeypatch, *, store):
    """Drive the copilot draft turn; return ``(injected_user_message, result)``."""
    import hermes_runtime.copilot_turn as copilot_mod

    captured: dict[str, str] = {}

    def capture(*, user_message: str, **_kwargs: object) -> dict[str, object]:
        captured["user_message"] = user_message
        return {"final_response": "DRAFT", "messages": []}

    monkeypatch.setattr(copilot_mod, "run_scripted_agent", capture)
    run_turn = make_copilot_run_turn(
        scripted_completions=[{"content": "unused"}], store=store
    )
    result = run_turn(channel="sms", case_id="case_l6")
    return captured.get("user_message", ""), result


def test_copilot_injects_confirmed_learnings_when_its_flag_is_on(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_EXPERIENCE_INJECTION", "on")
    msg, result = _run_copilot_capturing(monkeypatch, store=_FakeStore(_CONFIRMED))
    assert _FENCE in msg
    assert "check get_delivery_status first" in msg
    assert "Confirm the ship-to ZIP" in msg
    assert result["draft"] == "DRAFT"  # turn completes normally


def test_copilot_injects_nothing_when_its_flag_is_off(monkeypatch) -> None:
    # DEFAULT OFF (flag unset by the fixture): no read, no fence.
    msg, _ = _run_copilot_capturing(monkeypatch, store=_FakeStore(_CONFIRMED))
    assert _FENCE not in msg


def test_copilot_ignores_the_external_flag(monkeypatch) -> None:
    # Two independent flags: turning ON the EXTERNAL flag must NOT make the copilot
    # inject -- the copilot reads only its own axis.
    monkeypatch.setenv("AGENT_EXPERIENCE_EXTERNAL_INJECTION", "on")
    msg, _ = _run_copilot_capturing(monkeypatch, store=_FakeStore(_CONFIRMED))
    assert _FENCE not in msg


def test_copilot_injection_failure_degrades_to_skip(monkeypatch) -> None:
    # NFR-5: a confirmed-read that raises is swallowed -- the draft is still produced
    # and no fence is injected.
    monkeypatch.setenv("AGENT_EXPERIENCE_INJECTION", "on")
    msg, result = _run_copilot_capturing(
        monkeypatch, store=_FakeStore(_CONFIRMED, raise_on_read=True)
    )
    assert _FENCE not in msg
    assert result["draft"] == "DRAFT"


# --- external turn -------------------------------------------------------------


def _run_external_capturing(monkeypatch, *, store):
    """Drive the external turn; return the injected user message."""
    import hermes_runtime.openrouter as openrouter_mod

    captured: dict[str, str] = {}

    def capture(*, user_message: str, **_kwargs: object) -> dict[str, object]:
        captured["user_message"] = user_message
        return {"final_response": "", "messages": []}

    monkeypatch.setattr(openrouter_mod, "run_agent_turn", capture)
    run_turn = make_openrouter_run_turn(
        config=_CONFIG,
        openai_factory=_scripted_openai_factory([{"content": "ok"}]),
        store=store,
    )
    context = SimpleNamespace(
        conversation_id="conv-l6",
        sms_session_id=None,
        from_phone="+14165550001",
        session_identity_snapshot=None,
    )
    run_turn(context, "Hi again")
    return captured["user_message"]


def test_external_injects_confirmed_learnings_when_its_flag_is_on(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_EXPERIENCE_EXTERNAL_INJECTION", "on")
    msg = _run_external_capturing(monkeypatch, store=_FakeStore(_CONFIRMED))
    assert _FENCE in msg
    assert "check get_delivery_status first" in msg


def test_external_injects_nothing_when_its_flag_is_off(monkeypatch) -> None:
    msg = _run_external_capturing(monkeypatch, store=_FakeStore(_CONFIRMED))
    assert _FENCE not in msg


def test_external_ignores_the_copilot_flag(monkeypatch) -> None:
    # Independence, the other direction: the copilot flag ON must NOT make the
    # external turn read -- so the external read is disable-able without touching
    # the copilot path.
    monkeypatch.setenv("AGENT_EXPERIENCE_INJECTION", "on")
    msg = _run_external_capturing(monkeypatch, store=_FakeStore(_CONFIRMED))
    assert _FENCE not in msg


def test_external_injection_failure_degrades_to_skip(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_EXPERIENCE_EXTERNAL_INJECTION", "on")
    msg = _run_external_capturing(
        monkeypatch, store=_FakeStore(_CONFIRMED, raise_on_read=True)
    )
    assert _FENCE not in msg  # swallowed; the turn still ran and injected nothing


# --- eval-determinism pin (NFR-6) ----------------------------------------------


def test_l6_injection_flags_default_off_the_eval_pin() -> None:
    # The pin: the record/replay path sets neither flag, so both fail-closed to
    # OFF and no confirmed entry is ever read on the eval path.
    assert agent_experience_injection_enabled() is False
    assert agent_experience_external_injection_enabled() is False


def test_external_eval_record_path_never_injects_confirmed_learnings(monkeypatch) -> None:
    # Structural pin: even with BOTH flags forced ON, the external eval RECORD path
    # (scenario_user_message -> render_injection with no experience arg) can never
    # surface a confirmed learning -- the eval path structurally does not read L6.
    from pathlib import Path

    from eval_runner.fixtures import load_scenario

    monkeypatch.setenv("AGENT_EXPERIENCE_INJECTION", "on")
    monkeypatch.setenv("AGENT_EXPERIENCE_EXTERNAL_INJECTION", "on")
    eval_dir = Path(__file__).resolve().parents[2] / "eval"
    scenario = load_scenario("text_first_launch", "07", eval_dir)
    assert _FENCE not in scenario_user_message(scenario)


def test_copilot_eval_record_store_cannot_surface_confirmed_learnings() -> None:
    # The copilot eval RECORD path binds a scenario-scoped store with no
    # load_confirmed_experience method, so the fail-closed loader returns None even
    # if the flag were on -- the record path can't inject L6.
    from pathlib import Path

    from eval_runner.fixtures import load_scenario

    from hermes_runtime.copilot_eval_record import _ScenarioCaseStore

    eval_dir = Path(__file__).resolve().parents[2] / "eval"
    scenario = load_scenario("text_first_launch", "30", eval_dir)
    assert load_confirmed_experience(_ScenarioCaseStore(scenario)) is None


# --- live Postgres: the confirmed-only filter at the source (FR-25) -------------


def test_load_confirmed_experience_returns_only_confirmed_rows(datastore) -> None:
    # ONLY status='confirmed' is ever read back -- proposed/rejected never surface.
    _, conn, _ = datastore
    from hermes_runtime.postgres_gateway_store import PostgresGatewayStore

    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO agent_experience (id, kind, status, content, source) "
            "VALUES (%s, %s, %s, %s, 'copilot_agent')",
            [
                ("aexp_c", "procedure", "confirmed", "CONFIRMED learning."),
                ("aexp_p", "note", "proposed", "PROPOSED learning."),
                ("aexp_r", "note", "rejected", "REJECTED learning."),
            ],
        )

    entries = PostgresGatewayStore(connection=conn).load_confirmed_experience()
    contents = [e["content"] for e in entries]
    assert contents == ["CONFIRMED learning."]
    assert all("PROPOSED" not in c and "REJECTED" not in c for c in contents)


# --- folded-in S23 follow-up: the draft turn is inert-by-construction ------------


def test_draft_turn_propose_experience_persists_nothing(datastore, monkeypatch) -> None:
    # The draft turn's tool schema technically includes propose_experience, but the
    # draft's _turn_extra_drivers has NO agent-experience override, so a draft-side
    # call lands on the shared mock and is discarded -- never persisted. Proven with
    # the LEARNING flag ON and select_tool_driver pointed at the real datastore
    # driver: if the draft path DID route L6 to Postgres, a row would appear. It
    # doesn't. Only the review fork ever writes.
    driver, conn, _ = datastore
    monkeypatch.setenv("AGENT_EXPERIENCE_LEARNING", "on")
    import hermes_runtime.tool_backend as tool_backend_mod

    monkeypatch.setattr(tool_backend_mod, "select_tool_driver", lambda *_a, **_k: driver)

    run_turn = make_copilot_run_turn(
        scripted_completions=[
            {
                "tool_calls": [
                    {
                        "name": "toee_agent_experience__propose_experience",
                        "arguments": {
                            "kind": "procedure",
                            "content": "Draft-side learning that must not persist.",
                        },
                    }
                ]
            },
            {"content": "A draft for the rep."},
        ],
        # Review fork runs (flag on) but proposes nothing, isolating the draft path.
        review_scripted_completions=[{"content": "Nothing worth recording."}],
    )

    run_turn(channel="sms", case_id="case_draft_inert")

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM agent_experience")
        assert cur.fetchone()[0] == 0
