"""Scripted-eval seam (S18, FR-26): prod-inert guard, handshake, and the run_turn boundary.

The top risk of this slice is a seam that injects predetermined agent replies being
reachable on a real customer turn. These tests pin the two independent guards (off by
default; refused in a prod config) plus the datastore handshake and the deterministic
scripted turn the turn-worker runs when armed.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_runtime import scripted_eval
from hermes_runtime.scripted_eval import (
    ScriptedTurnNotSeeded,
    load_captured_turn,
    load_scripted_turn,
    make_scripted_eval_run_turn,
    require_scripted_eval_prod_inert,
    save_captured_turn,
    scripted_completions_from_transcript,
    scripted_eval_armed,
    seed_scripted_turn,
)

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"


# --------------------------------------------------------------------------- #
# Prod-inert guards.
# --------------------------------------------------------------------------- #


def test_disarmed_by_default(monkeypatch) -> None:
    monkeypatch.delenv(scripted_eval.SCRIPTED_MODE_ENV, raising=False)
    assert scripted_eval_armed() is False


@pytest.mark.parametrize("value", ["1", "true", "on", "YES"])
def test_armed_by_truthy_flag(monkeypatch, value) -> None:
    monkeypatch.setenv(scripted_eval.SCRIPTED_MODE_ENV, value)
    assert scripted_eval_armed() is True


# Allowlist guard: refuses known prod labels, novel/unknown prod labels, AND unset --
# only an explicit non-prod label arms. The unset + novel-label cases are the fail-open
# gaps the inversion closes (the old denylist armed on both).
@pytest.mark.parametrize(
    "env", ["production", "prod", "staging", "prod-us", "prod-eu", "live", "unknown"]
)
def test_refuses_to_arm_outside_an_explicit_non_prod_env(monkeypatch, env) -> None:
    monkeypatch.setenv(scripted_eval._DEPLOY_ENV, env)
    with pytest.raises(ValueError, match="may only arm"):
        require_scripted_eval_prod_inert()


def test_refuses_to_arm_when_deploy_env_is_unset(monkeypatch) -> None:
    monkeypatch.delenv(scripted_eval._DEPLOY_ENV, raising=False)
    with pytest.raises(ValueError, match="may only arm"):
        require_scripted_eval_prod_inert()


@pytest.mark.parametrize("env", ["development", "dev", "local", "test", "ci", " CI "])
def test_arms_on_an_explicit_non_prod_env(monkeypatch, env) -> None:
    monkeypatch.setenv(scripted_eval._DEPLOY_ENV, env)
    require_scripted_eval_prod_inert()  # does not raise


def test_disarmed_gateway_never_builds_the_scripted_run_turn(monkeypatch) -> None:
    """PROD PATH: with the flag unset, resolve_turn_collaborators uses OpenRouter and
    the scripted seam is never constructed -- the guarantee that the seam is inert on a
    default/prod boot."""
    from hermes_runtime import gateway_composition

    monkeypatch.delenv(scripted_eval.SCRIPTED_MODE_ENV, raising=False)

    def _boom(*_a, **_k):
        raise AssertionError("scripted-eval run_turn must not be built when disarmed")

    monkeypatch.setattr(gateway_composition, "make_scripted_eval_run_turn", _boom)

    built = {"openrouter": False}

    def _fake_openrouter(*_a, **_k):
        built["openrouter"] = True
        return lambda *a, **k: {}

    monkeypatch.setattr(gateway_composition, "make_openrouter_run_turn", _fake_openrouter)
    monkeypatch.setattr(gateway_composition, "resolve_openrouter_config", lambda: object())
    monkeypatch.setattr(gateway_composition, "resolve_reply_sender", lambda: (lambda *a, **k: None))
    monkeypatch.setattr(gateway_composition, "resolve_tool_backend", lambda: "mock")
    monkeypatch.setattr(gateway_composition, "_apply_external_profile_env", lambda: None)
    monkeypatch.setattr(gateway_composition, "_require_in_memory_store_is_allowed", lambda: None)
    # warm_knowledge_embedder is imported lazily inside resolve_turn_collaborators; stub it.
    import hermes_runtime.knowledge.driver as kd

    monkeypatch.setattr(kd, "warm_knowledge_embedder", lambda: None)

    gateway_composition.resolve_turn_collaborators()
    assert built["openrouter"] is True


# --------------------------------------------------------------------------- #
# Transcript -> scripted completions.
# --------------------------------------------------------------------------- #


def test_completions_derived_from_a_recorded_transcript() -> None:
    doc = json.loads((EVAL_DIR / "transcripts/text_first_launch/01.json").read_text("utf-8"))
    specs = scripted_completions_from_transcript(doc["messages"])
    # Scenario 01: one tool-call turn (3 parallel reads) then one final text.
    assert len(specs) == 2
    assert [c["name"] for c in specs[0]["tool_calls"]] == [
        "toee_shopify_read__get_order",
        "toee_easyroutes_read__get_delivery_status",
        "toee_qbo_read__get_invoice",
    ]
    # Arguments round-trip back to a dict (not the JSON string on the wire).
    assert specs[0]["tool_calls"][0]["arguments"] == {"order_number": "1042"}
    assert "final_response" not in specs[1]
    assert isinstance(specs[1]["content"], str) and specs[1]["content"]


# --------------------------------------------------------------------------- #
# Datastore handshake + the run_turn boundary (need the composed Postgres).
# --------------------------------------------------------------------------- #


def _migrated_conn(temp_schema_conn):
    from hermes_runtime.datastore.migrate import DEV_ONLY_MIGRATIONS, run_migrations

    conn, _schema = temp_schema_conn
    run_migrations(conn, exclude=DEV_ONLY_MIGRATIONS)
    return conn


def test_handshake_round_trips(temp_schema_conn) -> None:
    conn = _migrated_conn(temp_schema_conn)
    completions = [{"content": "hi"}]
    seed_scripted_turn(
        conn, event_id="evt-1", suite="text_first_launch", scenario_id="02",
        completions=completions,
    )
    row = load_scripted_turn(conn, "evt-1")
    assert row is not None
    assert (row.suite, row.scenario_id) == ("text_first_launch", "02")
    assert row.completions == completions
    # captured is empty until the worker runs the turn.
    assert load_captured_turn(conn, "evt-1") is None

    save_captured_turn(conn, "evt-1", {"final_response": "done", "messages": []})
    assert load_captured_turn(conn, "evt-1") == {"final_response": "done", "messages": []}


def test_run_turn_requires_a_seeded_row(temp_schema_conn) -> None:
    conn = _migrated_conn(temp_schema_conn)
    run_turn = make_scripted_eval_run_turn(eval_dir=EVAL_DIR, connect=lambda: conn)
    with pytest.raises(ScriptedTurnNotSeeded):
        run_turn(SimpleNamespace(event_id="missing"), "ignored inbound")


def test_scripted_run_turn_drives_a_real_governed_turn(temp_schema_conn) -> None:
    """The run_turn seam runs the scenario's scripted turn through the REAL governed
    dispatch and captures a transcript matching the recorded fixture's tool calls."""
    conn = _migrated_conn(temp_schema_conn)
    doc = json.loads((EVAL_DIR / "transcripts/text_first_launch/01.json").read_text("utf-8"))
    completions = scripted_completions_from_transcript(doc["messages"])
    seed_scripted_turn(
        conn, event_id="evt-01", suite="text_first_launch", scenario_id="01",
        completions=completions,
    )

    run_turn = make_scripted_eval_run_turn(eval_dir=EVAL_DIR, connect=lambda: conn)
    turn = run_turn(SimpleNamespace(event_id="evt-01"), "placeholder webhook body")

    # A real transcript came back and the three governed reads dispatched.
    assert turn["final_response"]
    tool_names = [
        (m.get("tool_calls") or [{}])[0].get("function", {}).get("name")
        for m in turn["messages"]
        if m.get("role") == "assistant" and m.get("tool_calls")
    ]
    assert "toee_shopify_read__get_order" in [
        tc.get("function", {}).get("name")
        for m in turn["messages"]
        if m.get("role") == "assistant"
        for tc in (m.get("tool_calls") or [])
    ]
    # And it was persisted back for the harness to read.
    assert load_captured_turn(conn, "evt-01") is not None
