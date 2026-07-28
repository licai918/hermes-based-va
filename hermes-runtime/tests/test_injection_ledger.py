"""0.0.5 S09 (FR-11): the injection provenance ledger's non-DB properties.

The live-Postgres half (schema, grain, the turn x layer x entry join, the prune)
is ``tests/test_datastore_injection_ledger.py``. This file pins the parts that
are true with no database at all:

1. ``entry_ref`` is a STABLE NATURAL KEY (D4.3) -- ``binding_key + slot_name``
   for L4, the entry id for L6 and L7 -- never a row id, because the
   cross-channel merge path DELETEs and re-INSERTs L4 rows with fresh ids.
2. Each layer's row is gated on the flag that layer's INJECTION rode, and every
   one of those flags is off on the eval record/replay path (D4.1) -- so that
   path still writes nothing, while an L6- or L7-injecting deployment with the
   memory backend off is no longer silently unrecorded. Asserted across all four
   injection flags since 0.0.5 S06 filled the L7 seat.
3. A ledger write failure NEVER reaches the turn (NFR-5) -- both turn paths
   still return their reply/draft -- and the write happens AFTER the model call,
   so it is not a database round-trip in front of the reply and a turn that
   failed records nothing.
4. ``prune_window >= zero_hit_window`` (D12) -- the constant relation that keeps
   garbage collection from manufacturing S20 retirement candidates.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from hermes_runtime.copilot_turn import make_copilot_run_turn
from hermes_runtime.injection_ledger import (
    LAYER_L4,
    LAYER_L6,
    LAYER_L7,
    PRUNE_WINDOW_SECONDS,
    ZERO_HIT_WINDOW_SECONDS,
    injected_entry_refs,
    record_injection,
)
from hermes_runtime.live import _scripted_openai_factory
from hermes_runtime.openrouter import OpenRouterConfig, make_openrouter_run_turn

_LEDGER_LOGGER = "hermes_runtime.injection_ledger"

_CONFIG = OpenRouterConfig(
    base_url="https://openrouter.ai/api/v1", api_key="sk-or-test", model="m", fallback_model="f"
)
_MEMORY = [{"slot": "contact_time", "value": "evenings"}]
_EXPERIENCE = [{"id": "aexp_1", "content": "Check get_delivery_status first.", "kind": "procedure"}]
_LEXICON = [
    {
        "id": "lex_1",
        "domain": "company",
        "entry_kind": "alias",
        "surface_form": "TOEE",
        "canonical_form": "TOEE TIRE",
        "status": "confirmed",
    }
]


class _LedgerStore:
    """A gateway store whose ledger write is observable (or explosive)."""

    def __init__(
        self, *, memory=(), experience=(), raise_on_write: bool = False, trace=None
    ) -> None:
        self._memory = list(memory)
        self._experience = list(experience)
        self._raise = raise_on_write
        self._trace = trace
        self.writes: list[dict] = []

    def load_case_identity(self, case_id):
        return {"outcome": "unmatched_caller", "channel": "sms", "channel_identity": "+14165550001"}

    def load_customer_memory(self, binding_key):
        return list(self._memory)

    def load_confirmed_experience(self):
        return list(self._experience)

    def record_injection_ledger(self, *, turn_ref, case_or_binding_ref, entries):
        # Records FIRST, then explodes. `record_injection` swallows every
        # exception (NFR-5), so a store that only raised would leave `writes`
        # empty whether or not it was called -- every `assert store.writes == []`
        # below would be unfalsifiable. Recording first makes the call observable
        # even on the explosive path.
        if self._trace is not None:
            self._trace.append("ledger")
        self.writes.append(
            {"turn_ref": turn_ref, "case_or_binding_ref": case_or_binding_ref, "entries": list(entries)}
        )
        if self._raise:
            raise RuntimeError("ledger table is on fire")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("TOOL_BACKEND", raising=False)
    monkeypatch.delenv("AGENT_EXPERIENCE_INJECTION", raising=False)
    monkeypatch.delenv("AGENT_EXPERIENCE_EXTERNAL_INJECTION", raising=False)
    monkeypatch.delenv("AGENT_EXPERIENCE_LEARNING", raising=False)
    monkeypatch.delenv("LEXICON_INJECTION", raising=False)
    monkeypatch.delenv("LEXICON_EXTERNAL_INJECTION", raising=False)


# --- entry_ref shape (D4.3) ----------------------------------------------------


def test_l4_entry_ref_is_binding_key_plus_slot_name_never_a_row_id() -> None:
    refs = injected_entry_refs(
        binding_key="provisional:sms:+14165550001", memory=_MEMORY, experience=None
    )
    assert refs == [(LAYER_L4, "provisional:sms:+14165550001:contact_time")]


def test_l6_entry_ref_is_the_entry_id() -> None:
    refs = injected_entry_refs(binding_key=None, memory=None, experience=_EXPERIENCE)
    assert refs == [(LAYER_L6, "aexp_1")]


def test_l7_entry_ref_is_the_entry_id() -> None:
    # 0.0.5 S06 filled the lexicon seat. Same natural key as L6 -- the entry id is
    # stable across an edit (D7 pinned in-place UPDATE), so it survives the one
    # mutation an L7 row can undergo.
    refs = injected_entry_refs(binding_key=None, memory=None, lexicon=_LEXICON)
    assert refs == [(LAYER_L7, "lex_1")]


def test_a_lexicon_row_with_no_id_is_dropped_rather_than_recorded() -> None:
    # Same rule as the other two layers: a ref nothing can join back to is worse
    # than no ref.
    refs = injected_entry_refs(
        binding_key=None, memory=None, lexicon=[{"surface_form": "TOEE"}, *_LEXICON]
    )
    assert refs == [(LAYER_L7, "lex_1")]


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


# --- the gates, per layer, all off on the eval path (D4.1) ---------------------


def test_no_write_on_a_non_datastore_deployment_which_is_the_eval_path() -> None:
    # TOOL_BACKEND unset (the eval record/replay path's backend), so L4's gate is
    # shut. The store records before it raises, so an unexpected call would show
    # up here rather than being swallowed into a passing assertion.
    store = _LedgerStore(raise_on_write=True)
    record_injection(store, turn_ref="t1", case_or_binding_ref="k", entries=[(LAYER_L4, "k:s")])
    assert store.writes == []


def test_no_write_when_nothing_was_injected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    store = _LedgerStore(raise_on_write=True)
    record_injection(store, turn_ref="t1", case_or_binding_ref="k", entries=[])
    assert store.writes == []


def test_a_store_without_the_writer_is_a_noop(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # The eval record paths bind scenario-scoped stores that have no ledger writer
    # at all -- a second, structural reason nothing is recorded there.
    #
    # THE GATE HAS TO BE OPEN, or this never reaches the writer check. The L6 row
    # below rides AGENT_EXPERIENCE_*_INJECTION, which `_clean_env` deletes, so the
    # per-layer gate (added AFTER this test was written) returned at `if not rows`
    # and every assertion here held whatever the writer branch did -- deleting
    # `if writer is None: return` left the test green, which is worse than no test.
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    monkeypatch.setenv("AGENT_EXPERIENCE_EXTERNAL_INJECTION", "on")
    fallbacks: list[int] = []
    monkeypatch.setattr(
        "hermes_runtime.injection_ledger._gateway_store",
        lambda: fallbacks.append(1),
        raising=True,
    )

    class _ScenarioScopedStore:
        """What the eval record paths bind: presets in, no ledger writer."""

    with caplog.at_level(logging.WARNING, logger=_LEDGER_LOGGER):
        record_injection(
            _ScenarioScopedStore(),
            turn_ref="t1",
            case_or_binding_ref=None,
            entries=[(LAYER_L6, "a")],
        )

    # No fall-through to the default gateway store -- that would reach a real
    # database from a scenario-scoped turn.
    assert fallbacks == []
    # ... and NOOP means noop: not a `None(...)` TypeError swallowed by the NFR-5
    # except. This is the assertion that goes red when the guard is deleted.
    assert [r.getMessage() for r in caplog.records if r.name == _LEDGER_LOGGER] == []


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
    # backend forced on.
    #
    # The scenario id matters, and it used to be "07", which declares NO
    # memory_preset: `eval_record._injected_context` then renders nothing, there
    # are no injected refs, and `store.writes == []` held whether or not the eval
    # path wrote -- the same wrong-reason pass as the noop test above, one
    # function over. 29 is the fixture that actually smuggles a memory value.
    #
    # The patch target is `injection_ledger._gateway_store`, NOT
    # `tool_backend._gateway_store`. `injection_ledger` does
    # `from .tool_backend import _gateway_store`, so the name is bound in ITS
    # module namespace at import time and patching the source module never
    # reaches the call site. This test previously patched the source module and
    # therefore passed no matter what the eval path did -- verified by making
    # `record_scenario_turn` write a ledger row and watching it still pass.
    from pathlib import Path

    from eval_runner.fixtures import load_scenario

    from hermes_runtime.eval_record import record_scenario_turn

    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    store = _LedgerStore()
    monkeypatch.setattr(
        "hermes_runtime.injection_ledger._gateway_store", lambda: store, raising=True
    )

    eval_dir = Path(__file__).resolve().parents[2] / "eval"
    scenario = load_scenario("text_first_launch", "29", eval_dir)
    assert scenario.memory_preset, "this test needs a scenario that injects something"
    _path, _result = record_scenario_turn(
        scenario,
        run_turn=lambda **_kwargs: {"final_response": "ok", "messages": []},
        transcripts_dir=tmp_path,
        system_message="sys",
    )
    assert store.writes == []


# --- NFR-5: a ledger failure never reaches the turn ----------------------------


def _run_external(monkeypatch, *, store, model=None):
    """Drive the external turn. ``model`` replaces the patched model boundary."""
    import hermes_runtime.openrouter as openrouter_mod

    monkeypatch.setattr(
        openrouter_mod,
        "run_agent_turn",
        model or (lambda **_kwargs: {"final_response": "REPLY", "messages": []}),
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


# --- the write lands AFTER the turn, not on the way into it (NFR-5) ------------


def test_the_ledger_write_happens_after_the_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A synchronous INSERT + commit BEFORE the model call is a database
    # round-trip added to the reply path -- exactly what NFR-5 exists to keep
    # out of it.
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    monkeypatch.setattr(
        "hermes_runtime.openrouter.record_memory_injection_metric", lambda _flag: None
    )
    order: list[str] = []

    def _model(**_kwargs):
        order.append("model")
        return {"final_response": "REPLY", "messages": []}

    _run_external(monkeypatch, store=_LedgerStore(memory=_MEMORY, trace=order), model=_model)
    assert order == ["model", "ledger"]


def test_the_copilot_ledger_write_happens_after_the_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hermes_runtime.copilot_turn as copilot_mod

    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    monkeypatch.setattr(
        "hermes_runtime.copilot_turn.record_memory_injection_metric", lambda _flag: None
    )
    order: list[str] = []

    def _model(**_kwargs):
        order.append("model")
        return {"final_response": "DRAFT", "messages": []}

    monkeypatch.setattr(copilot_mod, "run_scripted_agent", _model)
    run_turn = make_copilot_run_turn(
        scripted_completions=[{"content": "x"}],
        store=_LedgerStore(memory=_MEMORY, trace=order),
    )
    run_turn(channel="sms", case_id="case_1")
    assert order == ["model", "ledger"]


def test_a_turn_that_never_produced_a_reply_records_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The ledger is the record of which entries were in a reply that HAPPENED.
    # A turn that died at the model produced none, so it has nothing to record --
    # and a row for it would put a prompt nobody ever saw into S10's blast radius
    # and S26's per-entry denominator.
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    monkeypatch.setattr(
        "hermes_runtime.openrouter.record_memory_injection_metric", lambda _flag: None
    )

    def _boom(**_kwargs):
        raise RuntimeError("the model is down")

    store = _LedgerStore(memory=_MEMORY)
    with pytest.raises(RuntimeError):
        _run_external(monkeypatch, store=store, model=_boom)
    assert store.writes == []


# --- each layer's row rides the flag that layer's injection rode ---------------


@pytest.mark.parametrize(
    ("flag", "layer", "entry_ref"),
    [
        ("AGENT_EXPERIENCE_EXTERNAL_INJECTION", LAYER_L6, "aexp_1"),
        ("AGENT_EXPERIENCE_INJECTION", LAYER_L6, "aexp_1"),
        ("LEXICON_EXTERNAL_INJECTION", LAYER_L7, "lex_1"),
        ("LEXICON_INJECTION", LAYER_L7, "lex_1"),
    ],
)
def test_each_layers_row_rides_its_own_injection_flag(
    monkeypatch: pytest.MonkeyPatch, flag: str, layer: str, entry_ref: str
) -> None:
    # L6 and L7 injection each ride their OWN axes, independent of the L4 memory
    # backend. A single blanket memory_enabled() gate recorded NOTHING for a
    # deployment running that injection with memory disabled -- the ledger would
    # be silently empty for precisely the entries S10 and S26 care most about.
    # TOOL_BACKEND stays unset here; only the one flag under test is on.
    #
    # Parametrized over all four injection flags (0.0.5 S06): registering L7's
    # gate against a global flag would have reproduced the same hole one layer
    # over, so the sibling paths are asserted rather than assumed.
    monkeypatch.setenv(flag, "on")
    store = _LedgerStore()
    record_injection(
        store,
        turn_ref="t1",
        case_or_binding_ref="k",
        entries=[(LAYER_L4, "k:contact_time"), (layer, entry_ref)],
    )
    # The gated layer's row lands; the L4 row does not (its flag is off).
    assert [w["entries"] for w in store.writes] == [[(layer, entry_ref)]]


def test_the_l6_row_lands_from_a_real_turn_with_memory_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The same thing end to end: TOOL_BACKEND unset, L6 external injection on.
    monkeypatch.setenv("AGENT_EXPERIENCE_EXTERNAL_INJECTION", "on")
    store = _LedgerStore(memory=_MEMORY, experience=_EXPERIENCE)
    _run_external(monkeypatch, store=store)
    assert [w["entries"] for w in store.writes] == [[(LAYER_L6, "aexp_1")]]


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
