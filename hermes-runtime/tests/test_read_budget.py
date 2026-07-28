"""0.0.5 S19 (FR-27, US14): the pre-turn read budget -- deadline, skip, pool.

S18 measured; this file pins what S19 ENFORCES. Three things have to be true at
once, and each of them has a way of being faked that these tests are shaped to
refuse:

1. **The deadline is enforced, not observed.** A bound that is only checked after
   the slow read returns is a comment. So every deadline test drives a store that
   sleeps far longer than the budget and asserts BOTH halves: the turn came back
   in a fraction of that sleep, AND the slow layer's content is absent from the
   prompt. "Nothing crashed" is not the assertion -- a turn that waited out the
   sleep and then injected everything would satisfy it.
2. **Fail-open is per layer.** The fast layers still render. A blanket "drop
   everything on any breach" would pass a one-sided test.
3. **The pool is a strict addition.** With the flag OFF no executor is
   constructed at all (asserted by RECORDING construction, never by an explosive
   fake -- ``load_reads`` swallows pool failures by design, so an exploding
   double would be caught and the test would pass regardless), and a pool that
   refuses to submit degrades to the sequential path with identical results.

The budget itself is deliberately NOT a new number -- see
``test_the_deadline_is_the_connect_budget_not_a_third_number``.
"""

from __future__ import annotations

import inspect
import time
from types import SimpleNamespace

import pytest

from hermes_runtime.datastore.config import CONNECT_TIMEOUT_TURN_SECONDS
from hermes_runtime.latency import (
    LATENCY_L4_LOAD,
    LATENCY_L6_LOAD,
    LATENCY_L7_LOAD,
    LATENCY_PRE_TURN_TOTAL,
    MEMORY_READ_BUDGET_ENV,
    MEMORY_READ_DEADLINE_MS,
    SLO_TOTAL_METRICS,
    empty_latency_metrics,
    memory_read_budget_enabled,
    skip_metric,
)
from hermes_runtime.live import _scripted_openai_factory
from hermes_runtime.openrouter import OpenRouterConfig, make_openrouter_run_turn
from hermes_runtime.copilot_turn import make_copilot_run_turn

_CONFIG = OpenRouterConfig(
    base_url="https://openrouter.ai/api/v1", api_key="sk-or-test", model="m", fallback_model="f"
)

# Distinctive markers, one per layer, so "which layer reached the prompt" is a
# substring check rather than a guess.
_L4_MARKER = "evenings-in-the-week"
_L6_MARKER = "Check get_delivery_status first."
_L7_MARKER = "ZQXJV"

_MEMORY = [{"slot": "contact_time", "value": _L4_MARKER}]
_EXPERIENCE = [{"id": "aexp_1", "content": _L6_MARKER, "kind": "procedure"}]
_LEXICON = [
    {
        "id": "lex_1",
        "domain": "company",
        "entry_kind": "alias",
        "surface_form": _L7_MARKER,
        "canonical_form": "TOEE TIRE",
        "status": "confirmed",
    }
]

# The slow read is ~15x the test deadline in each direction: long enough that an
# unenforced deadline is unmistakable in the wall clock, short enough that the
# abandoned worker costs the suite well under a second.
_SLOW_S = 0.6
_TEST_DEADLINE_MS = 40.0


class _SlowStore:
    """A gateway store where exactly ONE named read sleeps past the deadline."""

    def __init__(self, *, slow: str = ""):
        self._slow = slow
        self.merges: list[tuple[str, str]] = []

    def _maybe_sleep(self, name: str) -> None:
        if self._slow == name:
            time.sleep(_SLOW_S)

    def load_case_identity(self, case_id):
        return {"outcome": "unmatched_caller", "channel": "sms", "channel_identity": "+14165550001"}

    def load_customer_memory(self, binding_key):
        self._maybe_sleep("l4")
        return list(_MEMORY)

    def merge_provisional_memory(self, provisional_key, verified_key):
        self.merges.append((provisional_key, verified_key))
        return None

    def load_confirmed_experience(self):
        self._maybe_sleep("l6")
        return list(_EXPERIENCE)

    def load_confirmed_lexicon(self):
        self._maybe_sleep("l7")
        return list(_LEXICON)

    def record_injection_ledger(self, **_kwargs):
        return None


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("TOOL_BACKEND", raising=False)
    monkeypatch.delenv("AGENT_EXPERIENCE_INJECTION", raising=False)
    monkeypatch.delenv("AGENT_EXPERIENCE_EXTERNAL_INJECTION", raising=False)
    monkeypatch.delenv("AGENT_EXPERIENCE_LEARNING", raising=False)
    monkeypatch.delenv("LEXICON_INJECTION", raising=False)
    monkeypatch.delenv("LEXICON_EXTERNAL_INJECTION", raising=False)
    monkeypatch.delenv("KNOWLEDGE_BACKEND", raising=False)
    monkeypatch.delenv(MEMORY_READ_BUDGET_ENV, raising=False)


def _all_layers_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    monkeypatch.setenv("AGENT_EXPERIENCE_EXTERNAL_INJECTION", "on")
    monkeypatch.setenv("AGENT_EXPERIENCE_INJECTION", "on")
    monkeypatch.setenv("LEXICON_EXTERNAL_INJECTION", "on")
    monkeypatch.setenv("LEXICON_INJECTION", "on")


def _budget_on(monkeypatch: pytest.MonkeyPatch, *, deadline_ms: float = _TEST_DEADLINE_MS) -> None:
    monkeypatch.setenv(MEMORY_READ_BUDGET_ENV, "on")
    # The shipped deadline is 2s (the connect budget); a suite that waited it out
    # three times over would be its own defect. Patched as a module attribute --
    # `latency` reads the global at call time -- rather than adding a deploy knob
    # nobody asked for (D14: knob changes are config commits).
    monkeypatch.setattr("hermes_runtime.latency.MEMORY_READ_DEADLINE_MS", deadline_ms)


def _capture_emits(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, object, object]]:
    """Intercept the batched metric write in ``latency``'s OWN namespace.

    ``latency.py`` does ``from .metrics import emit_metric_samples``, so patching
    ``hermes_runtime.metrics`` would never reach the call site.
    """
    rows: list[tuple[str, object, object]] = []
    monkeypatch.setattr(
        "hermes_runtime.latency.emit_metric_samples",
        lambda batch: rows.extend(batch),
        raising=True,
    )
    return rows


def _run_external(monkeypatch, *, store, prompts=None, order=None):
    import hermes_runtime.openrouter as openrouter_mod

    monkeypatch.setattr(
        openrouter_mod,
        "record_memory_injection_metric",
        (lambda _flag: order.append("memory_injection_metric")) if order is not None
        else (lambda _flag: None),
    )

    def _model(**kwargs):
        if prompts is not None:
            prompts.append(kwargs.get("user_message"))
        if order is not None:
            order.append("model")
        return {"final_response": "REPLY", "messages": []}

    monkeypatch.setattr(openrouter_mod, "run_agent_turn", _model)
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


def _run_copilot(monkeypatch, *, store, prompts=None, order=None):
    import hermes_runtime.copilot_turn as copilot_mod

    monkeypatch.setattr(
        copilot_mod,
        "record_memory_injection_metric",
        (lambda _flag: order.append("memory_injection_metric")) if order is not None
        else (lambda _flag: None),
    )

    def _model(**kwargs):
        if prompts is not None:
            prompts.append(kwargs.get("user_message"))
        if order is not None:
            order.append("model")
        return {"final_response": "DRAFT", "messages": []}

    monkeypatch.setattr(copilot_mod, "run_scripted_agent", _model)
    run_turn = make_copilot_run_turn(scripted_completions=[{"content": "x"}], store=store)
    return run_turn(channel="sms", case_id="case_1")


def _by_metric(rows) -> dict[str, float]:
    return {metric: duration for metric, _flag, duration in rows}


# --- 1. the deadline is ENFORCED: the turn returns, the slow layer does not -----


@pytest.mark.parametrize(
    "slow,dropped_marker,kept_markers",
    [
        ("l7", _L7_MARKER, (_L4_MARKER, _L6_MARKER)),
        ("l6", _L6_MARKER, (_L4_MARKER, _L7_MARKER)),
    ],
)
def test_a_breached_layer_is_dropped_and_the_turn_answers_inside_the_budget(
    monkeypatch: pytest.MonkeyPatch, slow, dropped_marker, kept_markers
) -> None:
    _all_layers_on(monkeypatch)
    _budget_on(monkeypatch)
    rows = _capture_emits(monkeypatch)
    prompts: list[str] = []

    # One untimed turn first: `boot_profile`'s plugin discovery is a one-time
    # ~1.3s cost on the first call in a process, and timing it would drown the
    # signal this test is about.
    _run_external(monkeypatch, store=_SlowStore())
    prompts.clear()

    started = time.perf_counter()
    result = _run_external(monkeypatch, store=_SlowStore(slow=slow), prompts=prompts)
    elapsed = time.perf_counter() - started

    # Half one -- the turn completed, and it completed on the BUDGET's clock, not
    # the slow read's. A deadline checked after the read returns fails here.
    assert result["final_response"] == "REPLY"
    assert elapsed < _SLOW_S / 2, f"the turn waited {elapsed:.3f}s on a {_TEST_DEADLINE_MS}ms budget"

    # Half two -- the slow layer's contribution was actually DROPPED, and only it.
    assert prompts and dropped_marker not in prompts[0]
    for kept in kept_markers:
        assert kept in prompts[0], f"fail-open must be per layer; {kept} was collateral"

    # ... and the skip is countable.
    samples = _by_metric(rows)
    breached = {"l6": LATENCY_L6_LOAD, "l7": LATENCY_L7_LOAD}[slow]
    assert skip_metric(breached) in samples


def test_the_copilot_seam_is_bounded_too(monkeypatch: pytest.MonkeyPatch) -> None:
    # The sibling read path. A fix that closes only the path the ticket named
    # leaves the twin unbounded -- the draft seam carries the same three layers.
    _all_layers_on(monkeypatch)
    _budget_on(monkeypatch)
    rows = _capture_emits(monkeypatch)
    prompts: list[str] = []

    _run_copilot(monkeypatch, store=_SlowStore())  # untimed: see the external twin
    prompts.clear()

    started = time.perf_counter()
    result = _run_copilot(monkeypatch, store=_SlowStore(slow="l7"), prompts=prompts)
    elapsed = time.perf_counter() - started

    assert result["draft"] == "DRAFT"
    assert elapsed < _SLOW_S / 2
    assert prompts and _L7_MARKER not in prompts[0]
    assert _L6_MARKER in prompts[0]
    assert skip_metric(LATENCY_L7_LOAD) in _by_metric(rows)


def test_a_breached_l4_read_leaves_the_copilot_draft_standing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # L4 on the draft seam resolves the case IDENTITY as well as the slots, so a
    # breach costs more than a memory block. It must still be a degradation, not
    # a failure: NFR-5 is absolute.
    _all_layers_on(monkeypatch)
    _budget_on(monkeypatch)
    _capture_emits(monkeypatch)
    prompts: list[str] = []

    result = _run_copilot(monkeypatch, store=_SlowStore(slow="l4"), prompts=prompts)

    assert result["draft"] == "DRAFT"
    assert prompts and _L4_MARKER not in prompts[0]
    assert _L7_MARKER in prompts[0]


def test_a_breach_still_charges_its_time_to_the_slo_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A dropped layer that also vanished from the histogram would make a
    # struggling deployment read as a fast one -- the breach must stay visible on
    # the very tile the owner judges PAC-6 with.
    _all_layers_on(monkeypatch)
    _budget_on(monkeypatch)
    rows = _capture_emits(monkeypatch)
    _run_external(monkeypatch, store=_SlowStore(slow="l7"))

    samples = _by_metric(rows)
    # The breach cost about the budget -- not zero (which would erase it from the
    # histogram) and not the whole sleep (which would mean nothing was enforced).
    assert samples[LATENCY_L7_LOAD] >= _TEST_DEADLINE_MS * 0.8
    assert samples[LATENCY_L7_LOAD] < _SLOW_S * 1000.0 / 2
    assert samples[LATENCY_PRE_TURN_TOTAL] == pytest.approx(
        sum(samples[m] for m in SLO_TOTAL_METRICS), rel=1e-9
    )
    # The skip row is a COUNT, not a second helping of the same milliseconds.
    assert skip_metric(LATENCY_L7_LOAD) not in SLO_TOTAL_METRICS


# --- 2. the pool: off by default, and a failing pool degrades sequentially ------


class _RefusingPool:
    """Constructs fine, refuses to submit -- the shape a thread-starved box has."""

    submits: list[int] = []

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def submit(self, *_args, **_kwargs):
        _RefusingPool.submits.append(1)
        raise RuntimeError("cannot start new thread")

    def shutdown(self, wait: bool = True) -> None:
        return None


def test_the_flag_is_off_by_default_and_no_pool_is_constructed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _all_layers_on(monkeypatch)
    _capture_emits(monkeypatch)
    assert memory_read_budget_enabled() is False

    constructed: list[int] = []

    # RECORDING, not exploding: `load_reads` swallows pool failures on purpose,
    # so an exploding double would be caught and this test would pass whatever
    # the code did.
    class _Recording(_RefusingPool):
        def __init__(self, *args, **kwargs):
            constructed.append(1)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("hermes_runtime.latency.ThreadPoolExecutor", _Recording)
    prompts: list[str] = []
    _run_external(monkeypatch, store=_SlowStore(), prompts=prompts)

    assert constructed == [], "the default turn path must not construct an executor"
    assert prompts and _L7_MARKER in prompts[0]


def test_a_pool_that_refuses_to_submit_degrades_to_the_sequential_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _all_layers_on(monkeypatch)
    _budget_on(monkeypatch)
    _capture_emits(monkeypatch)

    baseline: list[str] = []
    _run_external(monkeypatch, store=_SlowStore(), prompts=baseline)

    _RefusingPool.submits = []
    monkeypatch.setattr("hermes_runtime.latency.ThreadPoolExecutor", _RefusingPool)
    rows = _capture_emits(monkeypatch)
    degraded: list[str] = []
    result = _run_external(monkeypatch, store=_SlowStore(), prompts=degraded)

    # The fallback was actually exercised (not skipped past), and it produced the
    # SAME turn -- identical prompt, identical result.
    assert _RefusingPool.submits, "the pool-failure path was never reached"
    assert result["final_response"] == "REPLY"
    assert degraded == baseline
    # ... and it kept instrumenting. A fallback that quietly dropped the timers
    # would hide the very condition that triggered it.
    samples = _by_metric(rows)
    for metric in SLO_TOTAL_METRICS:
        assert metric in samples


# --- 3. the budget is not a third number ---------------------------------------


def test_the_deadline_is_the_connect_budget_not_a_third_number() -> None:
    # b989048 already decided how long anything on the reply path may wait for
    # the database, against a measured 130s hang. A read cannot beat its own
    # connect, so a shorter read deadline would fire on every cold connect.
    assert MEMORY_READ_DEADLINE_MS == CONNECT_TIMEOUT_TURN_SECONDS * 1000.0

    import hermes_runtime.latency as latency_mod

    source = inspect.getsource(latency_mod)
    assert "CONNECT_TIMEOUT_TURN_SECONDS" in source
    # ... derived, not copied: a literal 2000 would be the second source of truth.
    assert "2000" not in source


def test_the_skip_metric_is_derived_from_the_read_it_replaces() -> None:
    # One naming rule, so a later read site cannot invent a second convention and
    # leave its skips uncountable.
    for metric in SLO_TOTAL_METRICS:
        assert skip_metric(metric).startswith(metric)
    assert len({skip_metric(m) for m in SLO_TOTAL_METRICS}) == len(SLO_TOTAL_METRICS)


def test_a_skip_is_countable_without_disturbing_the_tile_set() -> None:
    # A skip is a plain `metric_event` row under its own name, so it is countable
    # in SQL as it stands. It stays OUT of the LATENCY tiles, which are duration
    # tiles judged against a budget -- a count rendered there would report the
    # deadline's own length as a p95, and would read "Not yet measured" for a
    # layer nothing has ever dropped. The skip metrics are registered for GATING
    # (or the fail-closed emit filter would drop them and leave a breach
    # uncountable) and absent from the tiles: both halves, because either alone
    # is satisfiable by accident.
    #
    # 0.0.5 S22 placed the tile, as a COUNT per injected layer on the lifecycle
    # block -- see `test_lifecycle_metrics.py`. That is why this assertion is now
    # a boundary between two shapes rather than a note about unfinished work.
    from hermes_runtime.latency import _METRIC_LAYER

    tiles = {tile["metric"] for tile in empty_latency_metrics()["layers"]}
    for metric in SLO_TOTAL_METRICS:
        assert skip_metric(metric) in _METRIC_LAYER
        assert _METRIC_LAYER[skip_metric(metric)] == _METRIC_LAYER[metric]
        assert skip_metric(metric) not in tiles


# --- 4. eval determinism (NFR-4) and the gate ----------------------------------


def test_a_skip_row_rides_its_own_layers_gate_in_both_directions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Both halves, because either alone is satisfiable by an accident. With the
    # layer's flag ON the skip must actually be emitted -- an unregistered skip
    # metric is dropped by `record_latency_samples`' fail-closed filter and would
    # leave a breach uncountable. With every flag OFF -- the eval record/replay
    # path -- nothing is emitted at all, skips included: an ungated skip row is
    # precisely the nondeterministic write into the replay gate that filter
    # exists to prevent.
    _budget_on(monkeypatch)

    _all_layers_on(monkeypatch)
    on_rows = _capture_emits(monkeypatch)
    _run_external(monkeypatch, store=_SlowStore(slow="l7"))
    assert skip_metric(LATENCY_L7_LOAD) in _by_metric(on_rows)

    # Every axis, not just the external pair: L6's and L7's ledger gates are
    # "either turn path's flag", so leaving the copilot ones set would keep them
    # open and this half would pass for the wrong reason.
    for flag in (
        "TOOL_BACKEND",
        "AGENT_EXPERIENCE_EXTERNAL_INJECTION",
        "AGENT_EXPERIENCE_INJECTION",
        "LEXICON_EXTERNAL_INJECTION",
        "LEXICON_INJECTION",
    ):
        monkeypatch.delenv(flag, raising=False)
    off_rows = _capture_emits(monkeypatch)
    _run_external(monkeypatch, store=_SlowStore(slow="l7"))
    assert off_rows == []


def test_the_budget_changes_no_byte_of_a_healthy_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    # Turning the mechanism on must be invisible when nothing breaches: same
    # prompt, same result. Anything else would move the replay gate.
    _all_layers_on(monkeypatch)
    _capture_emits(monkeypatch)

    off_prompts: list[str] = []
    off = _run_external(monkeypatch, store=_SlowStore(), prompts=off_prompts)

    _budget_on(monkeypatch, deadline_ms=5000.0)
    on_prompts: list[str] = []
    on = _run_external(monkeypatch, store=_SlowStore(), prompts=on_prompts)

    assert off_prompts and off_prompts == on_prompts
    assert off == on


# --- 5. the memory-injection counter is no longer in front of the model --------


@pytest.mark.parametrize("run", [_run_external, _run_copilot])
def test_the_memory_injection_counter_is_emitted_after_the_model_call(
    monkeypatch: pytest.MonkeyPatch, run
) -> None:
    # It is a synchronous, unpooled INSERT. Ahead of the model it is a database
    # round-trip in front of the customer's reply -- the shape NFR-5 exists to
    # forbid, and the shape S18's own emit was built to avoid.
    _all_layers_on(monkeypatch)
    _capture_emits(monkeypatch)
    order: list[str] = []
    run(monkeypatch, store=_SlowStore(), order=order)
    assert order == ["model", "memory_injection_metric"]
