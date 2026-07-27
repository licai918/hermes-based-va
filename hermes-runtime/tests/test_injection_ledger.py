"""0.0.5 S09 (FR-11): the injection provenance ledger's non-DB properties.

The live-Postgres half (schema, grain, the turn x layer x entry join, the prune)
is ``tests/test_datastore_injection_ledger.py``. This file pins the parts that
are true with no database at all:

1. ``entry_ref`` is a STABLE NATURAL KEY (D4.3) -- ``binding_key + slot_name``
   for L4, the entry id for L6 -- never a row id, because the cross-channel
   merge path DELETEs and re-INSERTs L4 rows with fresh ids.
2. The gate is the EVAL axis, not the injection axis (D4.1): the write is
   skipped on a non-datastore deployment (which is what the eval record/replay
   path runs as) and skipped when nothing was injected.
3. A ledger write failure NEVER reaches the turn (NFR-5) -- both turn paths
   still return their reply/draft.
4. ``prune_window >= zero_hit_window`` (D12) -- the constant relation that keeps
   garbage collection from manufacturing S20 retirement candidates.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hermes_runtime.copilot_turn import make_copilot_run_turn
from hermes_runtime.injection_ledger import (
    LAYER_L4,
    LAYER_L6,
    PRUNE_WINDOW_SECONDS,
    ZERO_HIT_WINDOW_SECONDS,
    injected_entry_refs,
    record_injection,
)
from hermes_runtime.live import _scripted_openai_factory
from hermes_runtime.openrouter import OpenRouterConfig, make_openrouter_run_turn

_CONFIG = OpenRouterConfig(
    base_url="https://openrouter.ai/api/v1", api_key="sk-or-test", model="m", fallback_model="f"
)
_MEMORY = [{"slot": "contact_time", "value": "evenings"}]
_EXPERIENCE = [{"id": "aexp_1", "content": "Check get_delivery_status first.", "kind": "procedure"}]


class _LedgerStore:
    """A gateway store whose ledger write is observable (or explosive)."""

    def __init__(self, *, memory=(), experience=(), raise_on_write: bool = False) -> None:
        self._memory = list(memory)
        self._experience = list(experience)
        self._raise = raise_on_write
        self.writes: list[dict] = []

    def load_case_identity(self, case_id):
        return {"outcome": "unmatched_caller", "channel": "sms", "channel_identity": "+14165550001"}

    def load_customer_memory(self, binding_key):
        return list(self._memory)

    def load_confirmed_experience(self):
        return list(self._experience)

    def record_injection_ledger(self, *, turn_ref, case_or_binding_ref, entries):
        if self._raise:
            raise RuntimeError("ledger table is on fire")
        self.writes.append(
            {"turn_ref": turn_ref, "case_or_binding_ref": case_or_binding_ref, "entries": list(entries)}
        )


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("TOOL_BACKEND", raising=False)
    monkeypatch.delenv("AGENT_EXPERIENCE_INJECTION", raising=False)
    monkeypatch.delenv("AGENT_EXPERIENCE_EXTERNAL_INJECTION", raising=False)
    monkeypatch.delenv("AGENT_EXPERIENCE_LEARNING", raising=False)


# --- entry_ref shape (D4.3) ----------------------------------------------------


def test_l4_entry_ref_is_binding_key_plus_slot_name_never_a_row_id() -> None:
    refs = injected_entry_refs(
        binding_key="provisional:sms:+14165550001", memory=_MEMORY, experience=None
    )
    assert refs == [(LAYER_L4, "provisional:sms:+14165550001:contact_time")]


def test_l6_entry_ref_is_the_entry_id() -> None:
    refs = injected_entry_refs(binding_key=None, memory=None, experience=_EXPERIENCE)
    assert refs == [(LAYER_L6, "aexp_1")]


def test_refs_mirror_the_renderer_and_skip_what_it_skips() -> None:
    # hooks._render_memory drops a slot with no name; _render_experience drops an
    # entry with no content. A ref for either would claim an injection that did
    # not happen, which is exactly the lie S26's per-entry score cannot survive.
    refs = injected_entry_refs(
        binding_key="k",
        memory=[{"value": "orphan"}, {"slot": "channel_pref", "value": "sms"}],
        experience=[{"id": "aexp_empty", "content": ""}, *_EXPERIENCE],
    )
    assert refs == [(LAYER_L4, "k:channel_pref"), (LAYER_L6, "aexp_1")]


def test_l4_refs_need_a_binding_key_to_be_a_stable_natural_key() -> None:
    # No resolvable binding -> no stable key -> no L4 row (rather than a ref that
    # cannot be joined back to anything).
    assert injected_entry_refs(binding_key=None, memory=_MEMORY, experience=None) == []


# --- the gate is the eval axis, not the injection axis (D4.1) ------------------


def test_no_write_on_a_non_datastore_deployment_which_is_the_eval_path() -> None:
    # TOOL_BACKEND unset (the eval record/replay path's backend). The store would
    # raise if it were reached; it is not.
    store = _LedgerStore(raise_on_write=True)
    record_injection(store, turn_ref="t1", case_or_binding_ref="k", entries=[(LAYER_L4, "k:s")])
    assert store.writes == []


def test_no_write_when_nothing_was_injected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    store = _LedgerStore(raise_on_write=True)
    record_injection(store, turn_ref="t1", case_or_binding_ref="k", entries=[])
    assert store.writes == []


def test_a_store_without_the_writer_is_a_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    # The eval record paths bind scenario-scoped stores that have no ledger writer
    # at all -- a second, structural reason nothing is recorded there.
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    record_injection(object(), turn_ref="t1", case_or_binding_ref=None, entries=[(LAYER_L6, "a")])


def test_neither_render_injection_nor_the_eval_record_path_knows_about_the_ledger() -> None:
    # D4.2, as a LAYERING assertion rather than a behavioural one -- a behavioural
    # spy would be defeated by the very import style the rule forbids. Neither the
    # pure plugin-side renderer nor the eval record adapter may reference the
    # ledger at all; the write lives in the two live turn callers.
    import inspect

    import toee_hermes.plugin.hooks as hooks_mod

    import hermes_runtime.eval_record as eval_record_mod

    for module in (hooks_mod, eval_record_mod):
        assert "injection_ledger" not in inspect.getsource(module), module.__name__


def test_the_external_eval_record_path_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # And the same thing from the outside: recording a scenario WITH a memory
    # preset -- the case that renders a real injection block through the shared
    # renderer -- completes without a ledger write even with the datastore
    # backend forced on. A store that would explode on write proves it.
    from pathlib import Path

    from eval_runner.fixtures import load_scenario

    from hermes_runtime.eval_record import record_scenario_turn

    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    store = _LedgerStore(raise_on_write=True)
    monkeypatch.setattr(
        "hermes_runtime.tool_backend._gateway_store", lambda: store, raising=True
    )

    eval_dir = Path(__file__).resolve().parents[2] / "eval"
    scenario = load_scenario("text_first_launch", "07", eval_dir)
    _path, _result = record_scenario_turn(
        scenario,
        run_turn=lambda **_kwargs: {"final_response": "ok", "messages": []},
        transcripts_dir=tmp_path,
        system_message="sys",
    )
    assert store.writes == []


# --- NFR-5: a ledger failure never reaches the turn ----------------------------


def _run_external(monkeypatch, *, store):
    import hermes_runtime.openrouter as openrouter_mod

    monkeypatch.setattr(
        openrouter_mod,
        "run_agent_turn",
        lambda **_kwargs: {"final_response": "REPLY", "messages": []},
    )
    run_turn = make_openrouter_run_turn(
        config=_CONFIG,
        openai_factory=_scripted_openai_factory([{"content": "ok"}]),
        store=store,
    )
    context = SimpleNamespace(
        event_id="evt-1",
        conversation_id="conv-1",
        sms_session_id=None,
        from_phone="+14165550001",
        session_identity_snapshot=None,
    )
    return run_turn(context, "Hi again")


def _run_copilot(monkeypatch, *, store):
    import hermes_runtime.copilot_turn as copilot_mod

    monkeypatch.setattr(
        copilot_mod,
        "run_scripted_agent",
        lambda **_kwargs: {"final_response": "DRAFT", "messages": []},
    )
    run_turn = make_copilot_run_turn(scripted_completions=[{"content": "x"}], store=store)
    return run_turn(channel="sms", case_id="case_1")


def test_a_ledger_write_failure_leaves_the_external_turn_intact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    monkeypatch.setattr(
        "hermes_runtime.openrouter.record_memory_injection_metric", lambda _flag: None
    )
    result = _run_external(monkeypatch, store=_LedgerStore(memory=_MEMORY, raise_on_write=True))
    assert result["final_response"] == "REPLY"


def test_a_ledger_write_failure_leaves_the_copilot_turn_intact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    monkeypatch.setattr(
        "hermes_runtime.copilot_turn.record_memory_injection_metric", lambda _flag: None
    )
    result = _run_copilot(monkeypatch, store=_LedgerStore(memory=_MEMORY, raise_on_write=True))
    assert result["draft"] == "DRAFT"


def test_the_external_turn_records_the_turn_layer_entry_grain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    monkeypatch.setenv("AGENT_EXPERIENCE_EXTERNAL_INJECTION", "on")
    monkeypatch.setattr(
        "hermes_runtime.openrouter.record_memory_injection_metric", lambda _flag: None
    )
    store = _LedgerStore(memory=_MEMORY, experience=_EXPERIENCE)
    _run_external(monkeypatch, store=store)

    assert len(store.writes) == 1
    write = store.writes[0]
    assert write["turn_ref"] == "evt-1"
    assert write["case_or_binding_ref"] == "provisional:sms:+14165550001"
    assert write["entries"] == [
        (LAYER_L4, "provisional:sms:+14165550001:contact_time"),
        (LAYER_L6, "aexp_1"),
    ]


def test_the_copilot_turn_records_the_case_ref_and_a_per_turn_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    monkeypatch.setattr(
        "hermes_runtime.copilot_turn.record_memory_injection_metric", lambda _flag: None
    )
    store = _LedgerStore(memory=_MEMORY)
    _run_copilot(monkeypatch, store=store)
    _run_copilot(monkeypatch, store=store)

    assert [w["case_or_binding_ref"] for w in store.writes] == ["case_1", "case_1"]
    # Two draft turns on ONE case are two turns: the grain must not collapse them.
    assert store.writes[0]["turn_ref"] != store.writes[1]["turn_ref"]


def test_a_turn_that_injects_nothing_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    monkeypatch.setattr(
        "hermes_runtime.copilot_turn.record_memory_injection_metric", lambda _flag: None
    )
    store = _LedgerStore()  # no slots, no confirmed entries -> render_injection -> None
    _run_copilot(monkeypatch, store=store)
    assert store.writes == []


# --- retention: the prune job is actually wired to the worker ------------------


def test_the_prune_job_is_registered_on_the_background_worker() -> None:
    # A prune body nothing schedules is not retention. Same tick retention,
    # integration_probe and honored_rate ride (0.0.4 S04).
    from hermes_runtime.background_worker import BACKGROUND_JOB_TYPES, SCHEDULES, job_bodies
    from hermes_runtime.job_queue import INJECTION_LEDGER_PRUNE_JOB_TYPE

    assert INJECTION_LEDGER_PRUNE_JOB_TYPE in BACKGROUND_JOB_TYPES
    assert INJECTION_LEDGER_PRUNE_JOB_TYPE in job_bodies()
    assert any(s.job_type == INJECTION_LEDGER_PRUNE_JOB_TYPE for s in SCHEDULES)


# --- D12: the prune window is coupled to S20's zero-hit window -----------------


def test_prune_window_is_at_least_the_zero_hit_window() -> None:
    # If the ledger is pruned BEFORE the zero-hit window elapses, S20's sweep sees
    # an actively-used entry as unused and manufactures a retirement candidate --
    # garbage collection turned into a memory-loss actuator. Editing either
    # constant to break this relation must fail here, loudly.
    assert PRUNE_WINDOW_SECONDS >= ZERO_HIT_WINDOW_SECONDS
