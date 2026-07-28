"""0.0.5 S18 (FR-26): per-layer read-latency measurement, without a database.

The live-Postgres half (the percentile aggregation, the schema, the counter/sample
separation) is ``tests/test_datastore_latency.py``. This file pins the parts that
are true with no database at all:

1. A duration is actually **measured and attributed to the layer that spent it**.
   The trap this slice is warned about is a test shaped ``assert elapsed < N``:
   against a fast local path that passes whether or not the timer is wired up,
   and would still pass if the instrumentation were deleted and the emit recorded
   zero. So the store here makes ONE named layer deliberately slow and the
   assertions are about which metric carries the time, not about it being small.
2. The duration lands in a **numeric field**, never in the metric name and never
   as a boolean "was slow" (D5.1 names both as defects).
3. The SLO total covers the non-L5 **reads** only -- L5 has its own 800ms budget
   (D5.2) and ``merge`` is a write with its own tile (D5.3).
4. Eval-neutrality (NFR-4): a slower read changes no byte of the prompt or of the
   turn result, and every layer's gate is shut on the eval path so nothing is
   emitted there at all.
5. NFR-5: the emit never fails a turn, and it happens AFTER the model call so it
   is not a database round-trip in front of the reply.
"""

from __future__ import annotations

import inspect
import time
from types import SimpleNamespace

import pytest
from toee_hermes.gateway.ingress import SessionIdentitySnapshot

from hermes_runtime.copilot_turn import make_copilot_run_turn
from hermes_runtime.knowledge.driver import DEFAULT_DEADLINE_MS
from hermes_runtime.latency import (
    LATENCY_L4_LOAD,
    LATENCY_L4_MERGE,
    LATENCY_L5_RETRIEVAL,
    LATENCY_L6_LOAD,
    LATENCY_L7_LOAD,
    LATENCY_PRE_TURN_TOTAL,
    PRE_TURN_READ_SLO_P95_MS,
    SLO_TOTAL_METRICS,
    empty_latency_metrics,
)
from hermes_runtime.live import _scripted_openai_factory
from hermes_runtime.openrouter import OpenRouterConfig, make_openrouter_run_turn

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

# Long enough that no un-instrumented path could produce it by accident, short
# enough not to slow the suite. Asserted against a floor below it so a marginally
# short sleep cannot flake; the gap between "instrumented" (>= 25ms) and "not
# instrumented" (the metric is absent entirely) is total either way.
_SLOW_S = 0.04
_SLOW_FLOOR_MS = 25.0


class _SlowStore:
    """A gateway store where exactly ONE named read is slow.

    Which read is slow is the whole point: a timer that is not wired up, or wired
    to the wrong layer, cannot reproduce "L4 took 40ms and L6 took ~0".
    """

    def __init__(self, *, slow: str = "", memory=_MEMORY, experience=_EXPERIENCE, lexicon=_LEXICON):
        self._slow = slow
        self._memory = list(memory)
        self._experience = list(experience)
        self._lexicon = list(lexicon)
        self.merges: list[tuple[str, str]] = []

    def _maybe_sleep(self, name: str) -> None:
        if self._slow == name:
            time.sleep(_SLOW_S)

    def load_case_identity(self, case_id):
        return {"outcome": "unmatched_caller", "channel": "sms", "channel_identity": "+14165550001"}

    def load_customer_memory(self, binding_key):
        self._maybe_sleep("l4")
        return list(self._memory)

    def merge_provisional_memory(self, provisional_key, verified_key):
        self._maybe_sleep("merge")
        self.merges.append((provisional_key, verified_key))
        return None

    def load_confirmed_experience(self):
        self._maybe_sleep("l6")
        return list(self._experience)

    def load_confirmed_lexicon(self):
        self._maybe_sleep("l7")
        return list(self._lexicon)

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


def _all_layers_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    monkeypatch.setenv("AGENT_EXPERIENCE_EXTERNAL_INJECTION", "on")
    monkeypatch.setenv("AGENT_EXPERIENCE_INJECTION", "on")
    monkeypatch.setenv("LEXICON_EXTERNAL_INJECTION", "on")
    monkeypatch.setenv("LEXICON_INJECTION", "on")


def _capture_emits(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, object, object]]:
    """Intercept the batched metric write.

    Patched in ``hermes_runtime.latency``'s own namespace, not in
    ``hermes_runtime.metrics``: ``latency.py`` does ``from .metrics import
    emit_metric_samples``, so the name is bound at import time and patching the
    source module would never reach the call site (the house's patch-target trap).
    """
    rows: list[tuple[str, object, object]] = []
    monkeypatch.setattr(
        "hermes_runtime.latency.emit_metric_samples",
        lambda batch: rows.extend(batch),
        raising=True,
    )
    return rows


def _run_external(monkeypatch, *, store, model=None, prompts=None):
    import hermes_runtime.openrouter as openrouter_mod

    monkeypatch.setattr(openrouter_mod, "record_memory_injection_metric", lambda _flag: None)

    def _default_model(**kwargs):
        if prompts is not None:
            prompts.append(kwargs.get("user_message"))
        return {"final_response": "REPLY", "messages": []}

    monkeypatch.setattr(openrouter_mod, "run_agent_turn", model or _default_model)
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


def _run_copilot(monkeypatch, *, store, model=None):
    import hermes_runtime.copilot_turn as copilot_mod

    monkeypatch.setattr(copilot_mod, "record_memory_injection_metric", lambda _flag: None)
    monkeypatch.setattr(
        copilot_mod,
        "run_scripted_agent",
        model or (lambda **_kwargs: {"final_response": "DRAFT", "messages": []}),
    )
    run_turn = make_copilot_run_turn(scripted_completions=[{"content": "x"}], store=store)
    return run_turn(channel="sms", case_id="case_1")


def _by_metric(rows) -> dict[str, float]:
    return {metric: duration for metric, _flag, duration in rows}


# --- 1. the measurement is TAKEN, and attributed to the layer that spent it -----


def test_the_external_turn_attributes_the_time_to_the_layer_that_was_slow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _all_layers_on(monkeypatch)
    rows = _capture_emits(monkeypatch)
    _run_external(monkeypatch, store=_SlowStore(slow="l4"))

    samples = _by_metric(rows)
    # Present at all -- a deleted timer emits nothing, which fails here first.
    assert LATENCY_L4_LOAD in samples
    assert LATENCY_L6_LOAD in samples
    assert LATENCY_L7_LOAD in samples
    # ... and the time is on the RIGHT layer. A timer wired to the wrong read, or
    # one that records a constant, cannot satisfy both of these.
    assert samples[LATENCY_L4_LOAD] >= _SLOW_FLOOR_MS
    assert samples[LATENCY_L6_LOAD] < _SLOW_FLOOR_MS
    assert samples[LATENCY_L7_LOAD] < _SLOW_FLOOR_MS


def test_the_slow_layer_moves_when_the_slow_read_moves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The mirror image of the test above, on a different layer. Two tests that
    # disagree about which metric is large cannot both pass against a constant,
    # a mislabelled emit, or a single shared timer.
    _all_layers_on(monkeypatch)
    rows = _capture_emits(monkeypatch)
    _run_external(monkeypatch, store=_SlowStore(slow="l7"))

    samples = _by_metric(rows)
    assert samples[LATENCY_L7_LOAD] >= _SLOW_FLOOR_MS
    assert samples[LATENCY_L4_LOAD] < _SLOW_FLOOR_MS
    assert samples[LATENCY_L6_LOAD] < _SLOW_FLOOR_MS


def test_the_copilot_turn_is_instrumented_too(monkeypatch: pytest.MonkeyPatch) -> None:
    # Fix rounds close the class, not the instance: the draft seam is the sibling
    # read path and carries the same three layers.
    _all_layers_on(monkeypatch)
    rows = _capture_emits(monkeypatch)
    _run_copilot(monkeypatch, store=_SlowStore(slow="l6"))

    samples = _by_metric(rows)
    assert samples[LATENCY_L6_LOAD] >= _SLOW_FLOOR_MS
    assert samples[LATENCY_L4_LOAD] < _SLOW_FLOOR_MS
    assert LATENCY_L7_LOAD in samples


# --- 2. the duration is a NUMBER, not a name and not a boolean (D5.1) ----------


def test_the_duration_is_a_numeric_field_never_the_metric_name_or_a_boolean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _all_layers_on(monkeypatch)
    rows = _capture_emits(monkeypatch)
    _run_external(monkeypatch, store=_SlowStore(slow="l4"))

    latency_rows = [row for row in rows if row[0].startswith("latency_")]
    assert latency_rows
    for metric, flag, duration in latency_rows:
        # No duration smuggled into the metric NAME (a "latency_l4_load_over_100ms"
        # style encoding satisfies the brief's letter and is named a defect).
        assert not any(ch.isdigit() for ch in metric.replace("l4", "").replace("l5", "")
                       .replace("l6", "").replace("l7", "")), metric
        assert isinstance(duration, float)
        # ... and not degraded to a boolean "was slow": the row carries NO boolean
        # signal at all, only the number.
        assert flag is None


# --- 3. the SLO total: non-L5 READS only (D5.2 / D5.3) -------------------------


def test_the_total_is_the_per_turn_sum_of_the_reads_and_excludes_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _all_layers_on(monkeypatch)
    rows = _capture_emits(monkeypatch)
    # Verified identity so the merge actually runs, and make the MERGE the slow
    # one: if it leaked into the total, the total would be >= the floor.
    store = _SlowStore(slow="merge")
    import hermes_runtime.openrouter as openrouter_mod

    monkeypatch.setattr(openrouter_mod, "record_memory_injection_metric", lambda _flag: None)
    monkeypatch.setattr(openrouter_mod, "run_agent_turn", lambda **_k: {"final_response": "R", "messages": []})
    run_turn = make_openrouter_run_turn(
        config=_CONFIG,
        openai_factory=_scripted_openai_factory([{"content": "ok"}]),
        store=store,
    )
    context = SimpleNamespace(
        event_id="evt-2",
        conversation_id="conv-2",
        sms_session_id=None,
        from_phone="+14165550001",
        session_identity_snapshot=SessionIdentitySnapshot(
            outcome="verified_customer",
            resolved_at="2026-07-28T00:00:00Z",
            shopify_customer_id="gid://shopify/Customer/1",
        ),
    )
    run_turn(context, "Hi")

    samples = _by_metric(rows)
    assert store.merges, "this test needs the merge to actually fire"
    assert samples[LATENCY_L4_MERGE] >= _SLOW_FLOOR_MS
    # D5.3: merge is a WRITE. Its own tile, outside the read-SLO total.
    assert samples[LATENCY_PRE_TURN_TOTAL] < _SLOW_FLOOR_MS
    assert samples[LATENCY_PRE_TURN_TOTAL] == pytest.approx(
        sum(samples[m] for m in SLO_TOTAL_METRICS), rel=1e-9
    )


def test_the_slo_total_metrics_are_the_three_reads_and_nothing_else() -> None:
    # D5.2: L5 has its own 800ms budget, so a total including it can never meet
    # 150ms. D5.3: merge is a write. Pinned as a set so a later slice adding a
    # layer has to make a deliberate decision rather than a silent one.
    assert set(SLO_TOTAL_METRICS) == {LATENCY_L4_LOAD, LATENCY_L6_LOAD, LATENCY_L7_LOAD}
    assert LATENCY_L4_MERGE not in SLO_TOTAL_METRICS
    assert LATENCY_L5_RETRIEVAL not in SLO_TOTAL_METRICS


def test_the_l5_budget_is_the_shipped_retrieval_deadline_not_a_second_copy() -> None:
    tiles = {tile["metric"]: tile for tile in empty_latency_metrics()["layers"]}
    assert tiles[LATENCY_L5_RETRIEVAL]["budget_ms"] == DEFAULT_DEADLINE_MS
    # ... and it is that constant rather than a copy of its current value: a
    # literal 800 anywhere in the module would be the second source of truth.
    import hermes_runtime.latency as latency_mod

    assert "800" not in inspect.getsource(latency_mod)


def test_the_slo_line_is_the_owner_decision_and_only_the_total_carries_it() -> None:
    payload = empty_latency_metrics()
    assert payload["slo_p95_ms"] == PRE_TURN_READ_SLO_P95_MS == 150.0
    assert payload["total"]["budget_ms"] == 150.0
    # No budget is invented for the read layers or for merge -- this slice
    # measures and displays; S19 owns enforcement.
    budgeted = {t["metric"] for t in payload["layers"] if t["budget_ms"] is not None}
    assert budgeted == {LATENCY_L5_RETRIEVAL}


# --- honest labelling: an unmeasured tile never reports "within SLO" ------------


def test_a_tile_with_no_samples_reports_not_measured_never_a_pass() -> None:
    payload = empty_latency_metrics()
    for tile in [payload["total"], *payload["layers"]]:
        assert tile["samples"] == 0
        assert tile["p50_ms"] is None
        assert tile["p95_ms"] is None
        # `False` here would render as a green "within budget" tile on a
        # deployment that has never measured anything.
        assert tile["breached"] is None, tile["metric"]
    assert payload["not_measured_label"]


# --- 4. eval-neutrality (NFR-4) ------------------------------------------------


def test_a_slower_read_changes_no_byte_of_the_prompt_or_the_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The determinism assertion the replay gate depends on: a timing emit varies
    # run to run, so it must not reach anything the eval harness compares.
    _all_layers_on(monkeypatch)
    _capture_emits(monkeypatch)

    fast_prompts: list[str] = []
    fast = _run_external(monkeypatch, store=_SlowStore(), prompts=fast_prompts)
    slow_prompts: list[str] = []
    slow = _run_external(monkeypatch, store=_SlowStore(slow="l4"), prompts=slow_prompts)

    assert fast_prompts and fast_prompts == slow_prompts
    assert fast == slow


def test_nothing_is_emitted_when_every_layer_gate_is_shut_which_is_the_eval_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The eval record/replay path sets no injection flag and forces a mock
    # backend, so every per-layer gate is shut and the turn attempts no metrics
    # connection at all.
    rows = _capture_emits(monkeypatch)
    calls: list[int] = []
    monkeypatch.setattr(
        "hermes_runtime.latency.emit_metric_samples",
        lambda batch: (calls.append(len(batch)), rows.extend(batch)),
        raising=True,
    )
    _run_external(monkeypatch, store=_SlowStore(slow="l4"))
    assert rows == []
    # Not merely "an empty batch was written" -- no write was attempted.
    assert calls == []


def test_a_metric_with_no_registered_gate_is_not_emitted_at_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Fail-closed on an unregistered metric. The next slice to wrap a read site
    # in `measure` without registering its layer gets no rows -- not ungated ones
    # that would land on the eval record/replay path.
    _all_layers_on(monkeypatch)
    rows = _capture_emits(monkeypatch)
    from hermes_runtime.latency import record_latency_samples

    record_latency_samples([("latency_l9_unregistered", 99.0)])
    assert rows == []
    # ... and a registered one on the same call still gets through, so this is a
    # filter rather than an all-or-nothing bail.
    record_latency_samples([("latency_l9_unregistered", 99.0), (LATENCY_L4_LOAD, 5.0)])
    assert [metric for metric, _flag, _d in rows] == [LATENCY_L4_LOAD, LATENCY_PRE_TURN_TOTAL]


def test_a_layer_is_still_measured_when_only_its_own_flag_is_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The per-layer gate (D4.1's correction, as a class): L6 injection rides its
    # own flag, so an L6-injecting deployment with the memory backend OFF must
    # still get its L6 latency -- a blanket memory_enabled() gate would record
    # nothing for exactly the layer that was on.
    monkeypatch.setenv("AGENT_EXPERIENCE_EXTERNAL_INJECTION", "on")
    rows = _capture_emits(monkeypatch)
    _run_external(monkeypatch, store=_SlowStore(slow="l6"))

    samples = _by_metric(rows)
    assert samples[LATENCY_L6_LOAD] >= _SLOW_FLOOR_MS
    assert LATENCY_L4_LOAD not in samples
    assert LATENCY_L4_MERGE not in samples


# --- 5. NFR-5: never stalls, never fails, and lands after the model call --------


def test_an_emit_failure_never_fails_the_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    _all_layers_on(monkeypatch)
    seen: list[int] = []

    def _boom(batch):
        # Records FIRST, then explodes: a double that only raised would leave
        # `seen` empty whether or not it was called, so the assertion below
        # would hold against instrumentation that was never wired up.
        seen.append(len(batch))
        raise RuntimeError("metric_event is on fire")

    monkeypatch.setattr("hermes_runtime.latency.emit_metric_samples", _boom, raising=True)

    assert _run_external(monkeypatch, store=_SlowStore())["final_response"] == "REPLY"
    assert _run_copilot(monkeypatch, store=_SlowStore())["draft"] == "DRAFT"
    assert len(seen) == 2


def test_the_latency_write_happens_after_the_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A synchronous INSERT + commit in FRONT of the model is a database
    # round-trip added to the reply path -- the instrumentation becoming the
    # thing NFR-5 exists to prevent.
    _all_layers_on(monkeypatch)
    order: list[str] = []
    monkeypatch.setattr(
        "hermes_runtime.latency.emit_metric_samples",
        lambda batch: order.append("emit"),
        raising=True,
    )

    def _model(**_kwargs):
        order.append("model")
        return {"final_response": "REPLY", "messages": []}

    _run_external(monkeypatch, store=_SlowStore(), model=_model)
    assert order == ["model", "emit"]


def test_the_copilot_latency_write_happens_after_the_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _all_layers_on(monkeypatch)
    order: list[str] = []
    monkeypatch.setattr(
        "hermes_runtime.latency.emit_metric_samples",
        lambda batch: order.append("emit"),
        raising=True,
    )

    def _model(**_kwargs):
        order.append("model")
        return {"final_response": "DRAFT", "messages": []}

    _run_copilot(monkeypatch, store=_SlowStore(), model=_model)
    assert order == ["model", "emit"]


def test_the_whole_turn_writes_metrics_once_not_once_per_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Four per-layer emits would be four unpooled connections on the turn path.
    # One batch, one connection.
    _all_layers_on(monkeypatch)
    batches: list[list] = []
    monkeypatch.setattr(
        "hermes_runtime.latency.emit_metric_samples",
        lambda batch: batches.append(list(batch)),
        raising=True,
    )
    _run_external(monkeypatch, store=_SlowStore())
    assert len(batches) == 1
    assert len(batches[0]) > 1


# --- L5: the duration rides the row the driver already writes ------------------


class _Chunk:
    title = "Winter tires"
    url = "https://example.test/winter"
    chunk_text = "…"


@pytest.mark.parametrize(
    "outcome, expected_flag",
    [("miss", False), ("hit", True), ("timeout", False), ("error", False)],
)
def test_the_knowledge_driver_stamps_its_retrieval_duration_on_every_branch(
    monkeypatch: pytest.MonkeyPatch, outcome: str, expected_flag: bool
) -> None:
    # All four exits emit, and all four must carry the duration: a retrieval that
    # blew its deadline or raised is exactly the datapoint S19 will want, and
    # dropping those would make L5's p95 a survivorship statistic.
    from hermes_runtime.knowledge.driver import KnowledgeDriver

    monkeypatch.setenv("KNOWLEDGE_BACKEND", "retriever")
    emits: list[tuple] = []
    monkeypatch.setattr(
        "hermes_runtime.knowledge.driver.emit_metric_event",
        lambda *args: emits.append(args),
        raising=True,
    )

    def _retrieve(query, embed_query_fn=None):
        time.sleep(_SLOW_S)
        if outcome == "error":
            raise RuntimeError("retriever exploded")
        return [_Chunk()] if outcome == "hit" else []

    # The timeout branch needs a deadline shorter than the sleep; the other three
    # need one longer than it.
    deadline = 5.0 if outcome == "timeout" else 5000.0
    driver = KnowledgeDriver(retrieve_fn=_retrieve, deadline_ms=deadline)
    driver._search_public_site({"query": "winter tires"})

    assert len(emits) == 1, "one row per retrieval attempt, same as before"
    metric, flag, duration = emits[0]
    assert metric == LATENCY_L5_RETRIEVAL
    assert flag is expected_flag  # the found/miss boolean it always carried
    assert duration is not None and duration > 0.0
    # The timeout branch returns at the DEADLINE, not after the full sleep, so
    # only the three completing branches can be held to the sleep floor.
    if outcome != "timeout":
        assert duration >= _SLOW_FLOOR_MS


# --- NFR-7: the mock twin and the Postgres twin agree on the empty payload -----


def test_the_mock_twin_reports_the_same_zero_sample_payload() -> None:
    # Both feed the same BFF mapper, which requires the keys. Full equality
    # rather than a key-set check: a mock that drifted to a different label or a
    # fabricated zero would be a silent lie on every storeless deployment.
    from toee_hermes.drivers.mock.metrics import create_metrics_mock_handlers

    handler = create_metrics_mock_handlers()["toee_metrics"]["get_aggregate_metrics"]
    payload = handler({}, None)
    assert payload["latency"] == empty_latency_metrics()
