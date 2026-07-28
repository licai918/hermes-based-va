"""0.0.5 S06 (FR-6/FR-7, NFR-4/5): the confirmed-L7 glossary at the two turn seams.

The L7 mirror of ``test_l6_injection.py``, deliberately the same shape. What this
file pins that L6's does not:

1. ONLY ``confirmed`` entries render -- ``proposed``/``rejected``/``retired``
   never reach a prompt, asserted on BOTH turn paths and at the source by the
   live-Postgres ``load_confirmed_lexicon`` filter.
2. TWO INDEPENDENT FLAGS (``LEXICON_INJECTION`` / ``LEXICON_EXTERNAL_INJECTION``)
   -- each seam reads only its OWN, both DEFAULT OFF.
3. **``default_rule`` conditions are evaluated AT RENDER.** Exactly one seasonal
   default renders, it is the one ``current_season`` picks for today, and a
   confirmed ``season=override`` row beats the calendar. The losing season's row
   is not in the prompt at all.
4. **A default renders as a QUESTION, never an assumption** -- the render-layer
   half of the guarantee ``SeasonalDefault.confirm_required`` makes unswitchable
   in data (S03).
5. **L4 beats L7 (FR-7).** A customer's own stated preference outranks a seasonal
   default: the Customer Memory fence renders BEFORE the glossary fence, and the
   glossary says so in words. The composer-level assertion lives in
   ``test_memory_boundary_tripwires.py``; this is the same claim through a real
   turn, which is what proves the wiring rather than the function.
6. TURN RESILIENCE (NFR-5) -- a glossary read that raises degrades to SKIP.
7. EVAL DETERMINISM (NFR-4) -- both flags default OFF and neither eval record
   path can surface a lexicon entry even with them forced ON.
8. The ledger's L7 seat rides **L7's own injection flag** (D4.1 as corrected),
   and records exactly the rows the prompt carried.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from hermes_runtime.copilot_turn import make_copilot_run_turn
from hermes_runtime.eval_record import scenario_user_message
from hermes_runtime.injection_ledger import LAYER_L4, LAYER_L7
from hermes_runtime.live import _scripted_openai_factory
from hermes_runtime.openrouter import (
    OPENROUTER_PRIMARY_MODEL,
    OpenRouterConfig,
    make_openrouter_run_turn,
)
from hermes_runtime.tool_backend import (
    LEXICON_GLOSSARY_LIMIT,
    lexicon_external_injection_enabled,
    lexicon_injection_enabled,
    load_confirmed_lexicon,
)

from toee_hermes.lexicon import SEASON_WINTER, current_season

_FENCE = "<confirmed_lexicon>"
_MEMORY_FENCE = "<untrusted_customer_memory>"


def _row(entry_id, kind, surface, canonical, *, status="confirmed", domain="tire"):
    """A row in the shape ``PostgresGatewayStore.load_confirmed_lexicon`` returns."""
    return {
        "id": entry_id,
        "domain": domain,
        "entry_kind": kind,
        "surface_form": surface,
        "canonical_form": canonical,
        "status": status,
    }


# The seeded domain, both seasonal rows present -- which is the real situation and
# the one where "evaluated at render" has something to decide.
_CONFIRMED = [
    _row("lex_alias", "alias", "TOEE", "TOEE TIRE", domain="company"),
    _row("lex_winter", "default_rule", "season=winter", "winter tires"),
    _row("lex_all_season", "default_rule", "season=all_season", "all-season tires"),
]
_CONFIG = OpenRouterConfig(
    base_url="https://openrouter.ai/api/v1",
    api_key="sk-or-test",
    model=OPENROUTER_PRIMARY_MODEL,
)


class _NoopQueue:
    """Swallows the S04 ``l6_review`` enqueue so no fork runs (DB-free)."""

    def enqueue(self, payload, *, job_type, **_kwargs) -> str:
        return "job_noop"


class _FakeStore:
    """A gateway store stub whose lexicon read is controllable per test."""

    def __init__(self, entries=(), *, raise_on_read: bool = False, memory=()) -> None:
        self._entries = list(entries)
        self._raise = raise_on_read
        self._memory = list(memory)

    def load_case_identity(self, case_id):  # copilot seam
        return {
            "outcome": "unmatched_caller",
            "channel": "sms",
            "channel_identity": "+14165550001",
        }

    def load_customer_memory(self, binding_key):  # both seams
        return list(self._memory)

    def load_confirmed_lexicon(self):
        if self._raise:
            raise RuntimeError("datastore down")
        return list(self._entries)


@pytest.fixture(autouse=True)
def _clean_l7_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # No real provider, no memory backend, and both L7 injection axes cleared so a
    # dev box's env can't leak into a test. Each test opts IN to the flag it needs.
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("TOOL_BACKEND", raising=False)
    monkeypatch.delenv("LEXICON_INJECTION", raising=False)
    monkeypatch.delenv("LEXICON_EXTERNAL_INJECTION", raising=False)
    monkeypatch.delenv("AGENT_EXPERIENCE_INJECTION", raising=False)
    monkeypatch.delenv("AGENT_EXPERIENCE_EXTERNAL_INJECTION", raising=False)
    monkeypatch.delenv("AGENT_EXPERIENCE_LEARNING", raising=False)


def _run_copilot_capturing(monkeypatch, *, store):
    """Drive the copilot draft turn; return ``(injected_user_message, result)``."""
    import hermes_runtime.copilot_turn as copilot_mod

    captured: dict[str, str] = {}

    def capture(*, user_message: str, **_kwargs: object) -> dict[str, object]:
        captured["user_message"] = user_message
        return {"final_response": "DRAFT", "messages": []}

    monkeypatch.setattr(copilot_mod, "run_scripted_agent", capture)
    run_turn = make_copilot_run_turn(
        scripted_completions=[{"content": "unused"}], store=store, queue=_NoopQueue()
    )
    result = run_turn(channel="sms", case_id="case_l7")
    return captured.get("user_message", ""), result


def _run_external_capturing(monkeypatch, *, store):
    """Drive the external turn; return the injected user message."""
    import hermes_runtime.openrouter as openrouter_mod

    captured: dict[str, str] = {}

    def capture(*, user_message: str, **_kwargs: object) -> dict[str, object]:
        captured["user_message"] = user_message
        return {"final_response": "", "messages": []}

    monkeypatch.setattr(openrouter_mod, "run_agent_turn", capture)
    monkeypatch.setattr(
        openrouter_mod, "record_memory_injection_metric", lambda _flag: None
    )
    run_turn = make_openrouter_run_turn(
        config=_CONFIG,
        openai_factory=_scripted_openai_factory([{"content": "ok"}]),
        store=store,
    )
    context = SimpleNamespace(
        event_id="evt-l7",
        conversation_id="conv-l7",
        sms_session_id=None,
        from_phone="+14165550001",
        session_identity_snapshot=None,
    )
    run_turn(context, "205 55 16")
    return captured["user_message"]


# --- the two flags, each on its own axis, both default OFF ---------------------


def test_copilot_injects_the_glossary_when_its_flag_is_on(monkeypatch) -> None:
    monkeypatch.setenv("LEXICON_INJECTION", "on")
    msg, result = _run_copilot_capturing(monkeypatch, store=_FakeStore(_CONFIRMED))
    assert _FENCE in msg
    assert '"TOEE" means "TOEE TIRE"' in msg
    assert result["draft"] == "DRAFT"  # turn completes normally


def test_copilot_injects_nothing_when_its_flag_is_off(monkeypatch) -> None:
    # DEFAULT OFF (flag unset by the fixture): no read, no fence.
    msg, _ = _run_copilot_capturing(monkeypatch, store=_FakeStore(_CONFIRMED))
    assert _FENCE not in msg


def test_copilot_ignores_the_external_flag(monkeypatch) -> None:
    # Two independent flags: the EXTERNAL flag on must NOT make the copilot inject.
    monkeypatch.setenv("LEXICON_EXTERNAL_INJECTION", "on")
    msg, _ = _run_copilot_capturing(monkeypatch, store=_FakeStore(_CONFIRMED))
    assert _FENCE not in msg


def test_copilot_ignores_the_l6_flags(monkeypatch) -> None:
    # And L7 is a separate axis from L6 entirely -- turning the agent-experience
    # injection on must not switch the glossary on as a side effect.
    monkeypatch.setenv("AGENT_EXPERIENCE_INJECTION", "on")
    monkeypatch.setenv("AGENT_EXPERIENCE_EXTERNAL_INJECTION", "on")
    msg, _ = _run_copilot_capturing(monkeypatch, store=_FakeStore(_CONFIRMED))
    assert _FENCE not in msg


def test_copilot_glossary_read_failure_degrades_to_skip(monkeypatch) -> None:
    # NFR-5: a read that raises is swallowed -- the draft is still produced.
    monkeypatch.setenv("LEXICON_INJECTION", "on")
    msg, result = _run_copilot_capturing(
        monkeypatch, store=_FakeStore(_CONFIRMED, raise_on_read=True)
    )
    assert _FENCE not in msg
    assert result["draft"] == "DRAFT"


def test_external_injects_the_glossary_when_its_flag_is_on(monkeypatch) -> None:
    monkeypatch.setenv("LEXICON_EXTERNAL_INJECTION", "on")
    msg = _run_external_capturing(monkeypatch, store=_FakeStore(_CONFIRMED))
    assert _FENCE in msg
    assert '"TOEE" means "TOEE TIRE"' in msg


def test_external_injects_nothing_when_its_flag_is_off(monkeypatch) -> None:
    msg = _run_external_capturing(monkeypatch, store=_FakeStore(_CONFIRMED))
    assert _FENCE not in msg


def test_external_ignores_the_copilot_flag(monkeypatch) -> None:
    # Independence, the other direction: the external read is disable-able without
    # touching the copilot path.
    monkeypatch.setenv("LEXICON_INJECTION", "on")
    msg = _run_external_capturing(monkeypatch, store=_FakeStore(_CONFIRMED))
    assert _FENCE not in msg


def test_external_glossary_read_failure_degrades_to_skip(monkeypatch) -> None:
    monkeypatch.setenv("LEXICON_EXTERNAL_INJECTION", "on")
    msg = _run_external_capturing(
        monkeypatch, store=_FakeStore(_CONFIRMED, raise_on_read=True)
    )
    assert _FENCE not in msg


# --- only confirmed entries render --------------------------------------------


@pytest.mark.parametrize("status", ["proposed", "rejected", "retired"])
def test_no_unconfirmed_entry_reaches_either_turn(monkeypatch, status: str) -> None:
    # The store read filters on status; this is the renderer's independent
    # re-check, driven through both real turn paths. A row that reached the list
    # by ANY route -- a mock store, a future caller, a widened query -- must not
    # become prompt text.
    monkeypatch.setenv("LEXICON_INJECTION", "on")
    monkeypatch.setenv("LEXICON_EXTERNAL_INJECTION", "on")
    entries = [
        _row("lex_bad", "alias", "GOODYEAR", "unconfirmedcanonical", status=status),
        _row("lex_bad_rule", "default_rule", "season=winter", "unconfirmedseason", status=status),
        *_CONFIRMED,
    ]
    copilot_msg, _ = _run_copilot_capturing(monkeypatch, store=_FakeStore(entries))
    external_msg = _run_external_capturing(monkeypatch, store=_FakeStore(entries))

    for msg in (copilot_msg, external_msg):
        assert _FENCE in msg, "the confirmed rows must still render"
        assert "unconfirmedcanonical" not in msg
        assert "unconfirmedseason" not in msg


def test_a_glossary_of_only_unconfirmed_entries_injects_no_fence(monkeypatch) -> None:
    # Not an empty fence, and not a header with no lines: no block at all.
    monkeypatch.setenv("LEXICON_EXTERNAL_INJECTION", "on")
    entries = [_row("lex_p", "alias", "TOEE", "TOEE TIRE", status="proposed")]
    msg = _run_external_capturing(monkeypatch, store=_FakeStore(entries))
    assert _FENCE not in msg


# --- default_rule: evaluated at render, and rendered as a QUESTION -------------


def _seasonal_lines(msg: str) -> list[str]:
    return [line for line in msg.splitlines() if "Seasonal default" in line]


def test_exactly_one_seasonal_default_renders_and_it_is_todays(monkeypatch) -> None:
    # BOTH seasonal rows are confirmed and in the read. The condition is resolved
    # at RENDER by current_season(), so exactly one line appears and the losing
    # season's row is not in the prompt at all -- calendar-driven, which is why
    # the expectation is derived from the same clock rather than hardcoded.
    monkeypatch.setenv("LEXICON_EXTERNAL_INJECTION", "on")
    msg = _run_external_capturing(monkeypatch, store=_FakeStore(_CONFIRMED))

    winter = current_season(date.today()) == SEASON_WINTER
    wanted, losing = ("winter tires", "all-season tires") if winter else ("all-season tires", "winter tires")
    lines = _seasonal_lines(msg)
    assert len(lines) == 1, msg
    assert wanted in lines[0]
    assert losing not in msg
    # The raw condition is never rendered as vocabulary: `"season=winter" means
    # "winter tires"` would read as a statement of fact, which is the assumption
    # phrasing FR-7 forbids.
    assert '"season=winter" means' not in msg
    assert '"season=all_season" means' not in msg


def test_a_seasonal_default_renders_as_a_question_never_an_assumption(monkeypatch) -> None:
    # S03 made SeasonalDefault.confirm_required a property that is always True so
    # the confirm posture cannot be switched off in DATA. This is the render-layer
    # half: the line is an imperative ASK, it names itself a question, and it
    # carries FR-7's override clause verbatim.
    monkeypatch.setenv("LEXICON_EXTERNAL_INJECTION", "on")
    line = _seasonal_lines(_run_external_capturing(monkeypatch, store=_FakeStore(_CONFIRMED)))[0]

    assert "ASK whether the customer wants" in line
    assert "unless the customer's own preference says otherwise" in line
    assert "A default is a question to raise, never an assumption to act on." in line


def test_an_admin_override_row_beats_the_calendar_at_render(monkeypatch) -> None:
    # S03's admin escape hatch, resolved at render: one confirmed
    # `season=override` row pins the season with no deploy. Asserted against the
    # season the calendar would NOT have picked, so it cannot pass by coincidence.
    monkeypatch.setenv("LEXICON_EXTERNAL_INJECTION", "on")
    winter_today = current_season(date.today()) == SEASON_WINTER
    override_to = "all_season" if winter_today else "winter"
    wanted = "all-season tires" if winter_today else "winter tires"
    entries = [*_CONFIRMED, _row("lex_override", "default_rule", "season=override", override_to)]

    msg = _run_external_capturing(monkeypatch, store=_FakeStore(entries))
    lines = _seasonal_lines(msg)
    assert len(lines) == 1, msg
    assert wanted in lines[0]


# --- FR-7: the customer's own preference outranks a shared default -------------


def test_customer_memory_renders_before_the_glossary_on_a_real_turn(monkeypatch) -> None:
    # The wiring half of FR-7 (the composer half is in
    # test_memory_boundary_tripwires.py). "In winter a bare size means winter
    # tires" is a DEFAULT; a default that overrides what the customer actually
    # told you is a bug that reads as a feature. Both mechanisms are asserted:
    # ORDER (L4 first, so the customer's own words are established before the
    # glossary arrives) and PHRASING (the glossary says so).
    monkeypatch.setenv("TOOL_BACKEND", "datastore")  # L4 read gate
    monkeypatch.setenv("LEXICON_EXTERNAL_INJECTION", "on")
    store = _FakeStore(
        _CONFIRMED, memory=[{"slot": "tire_preference_note", "value": "always all-seasons"}]
    )
    msg = _run_external_capturing(monkeypatch, store=store)

    assert _MEMORY_FENCE in msg and _FENCE in msg
    assert msg.index(_MEMORY_FENCE) < msg.index(_FENCE)
    assert "always all-seasons" in msg
    assert "take precedence over every line below" in msg


# --- the ledger's L7 seat rides L7's own flag (D4.1 as corrected) --------------


class _LedgerStore(_FakeStore):
    """A store whose ledger write is observable."""

    def __init__(self, entries=(), **kwargs) -> None:
        super().__init__(entries, **kwargs)
        self.writes: list[dict] = []

    def record_injection_ledger(self, *, turn_ref, case_or_binding_ref, entries):
        self.writes.append({"turn_ref": turn_ref, "entries": list(entries)})


def test_the_l7_row_lands_with_the_memory_backend_off(monkeypatch) -> None:
    # D4.1's correction, one layer over. TOOL_BACKEND stays UNSET, so a ledger
    # gated on the global memory flag would record nothing for a deployment that
    # is demonstrably injecting the glossary -- the exact hole the L6 fix closed.
    monkeypatch.setenv("LEXICON_EXTERNAL_INJECTION", "on")
    store = _LedgerStore(_CONFIRMED)
    _run_external_capturing(monkeypatch, store=store)

    assert len(store.writes) == 1
    layers = {layer for layer, _ in store.writes[0]["entries"]}
    assert layers == {LAYER_L7}
    assert LAYER_L4 not in layers  # its own flag is off


def test_the_ledger_records_only_the_rows_the_prompt_carried(monkeypatch) -> None:
    # The losing season's default_rule row is read from the store but never
    # rendered, so it must not be credited with an injection: over-claiming would
    # inflate S26's per-entry score and hide the row from S20's zero-hit sweep.
    monkeypatch.setenv("LEXICON_EXTERNAL_INJECTION", "on")
    store = _LedgerStore(_CONFIRMED)
    msg = _run_external_capturing(monkeypatch, store=store)

    recorded = {ref for layer, ref in store.writes[0]["entries"] if layer == LAYER_L7}
    winter = current_season(date.today()) == SEASON_WINTER
    applied, losing = ("lex_winter", "lex_all_season") if winter else ("lex_all_season", "lex_winter")
    assert recorded == {"lex_alias", applied}
    assert losing not in recorded
    # ... and the store really did hand over the row that was dropped, so this is
    # a filter doing work rather than a list that never contained it.
    assert len(store._entries) == 3 and _FENCE in msg


def test_no_ledger_row_when_the_glossary_flag_is_off(monkeypatch) -> None:
    store = _LedgerStore(_CONFIRMED)
    _run_external_capturing(monkeypatch, store=store)
    assert store.writes == []


# --- eval-determinism pin (NFR-4) ----------------------------------------------


def test_l7_injection_flags_default_off_the_eval_pin() -> None:
    # The pin: the record/replay path sets neither flag, so both fail-closed to
    # OFF and no lexicon entry is ever read on the eval path.
    assert lexicon_injection_enabled() is False
    assert lexicon_external_injection_enabled() is False


def test_external_eval_record_path_never_injects_the_glossary(monkeypatch) -> None:
    # Structural pin: even with BOTH flags forced ON, the external eval RECORD
    # path (scenario_user_message -> render_injection with no lexicon arg) can
    # never surface a lexicon entry -- the eval path structurally does not read L7.
    from pathlib import Path

    from eval_runner.fixtures import load_scenario

    monkeypatch.setenv("LEXICON_INJECTION", "on")
    monkeypatch.setenv("LEXICON_EXTERNAL_INJECTION", "on")
    eval_dir = Path(__file__).resolve().parents[2] / "eval"
    scenario = load_scenario("text_first_launch", "29", eval_dir)
    assert scenario.memory_preset, "use a scenario that actually renders a block"
    assert _FENCE not in scenario_user_message(scenario)


def test_copilot_eval_record_store_cannot_surface_the_glossary() -> None:
    # The copilot eval RECORD path binds a scenario-scoped store with no
    # load_confirmed_lexicon method, so the fail-closed loader returns None even
    # if the flag were on -- the record path can't inject L7.
    from pathlib import Path

    from eval_runner.fixtures import load_scenario

    from hermes_runtime.copilot_eval_record import _ScenarioCaseStore

    eval_dir = Path(__file__).resolve().parents[2] / "eval"
    scenario = load_scenario("text_first_launch", "30", eval_dir)
    assert load_confirmed_lexicon(_ScenarioCaseStore(scenario)) is None


# --- D16: the bound is a named constant, and the query uses it -----------------


def test_the_glossary_bound_is_a_named_constant() -> None:
    # S22's knob panel imports this name rather than hunting a literal, and the
    # selection query must actually use it -- a constant the SQL ignores is
    # documentation, not a knob.
    import inspect

    from hermes_runtime.postgres_gateway_store import PostgresGatewayStore

    assert LEXICON_GLOSSARY_LIMIT == 20
    source = inspect.getsource(PostgresGatewayStore.load_confirmed_lexicon)
    assert "LEXICON_GLOSSARY_LIMIT" in source
    assert "LIMIT 20" not in source


# --- live Postgres: the confirmed-only filter + the key contract (FR-6) --------


def test_load_confirmed_lexicon_returns_only_confirmed_rows_and_renders(datastore) -> None:
    # Two things at once, on purpose. The filter: only status='confirmed' is ever
    # read back. And the KEY CONTRACT: the dicts this method returns are fed
    # straight into the renderer, so a missing `status`/`entry_kind`/`domain` key
    # would silently produce an EMPTY glossary -- a failure no mock-shaped test
    # can catch, because the mock is written from the same assumption.
    _, conn, _ = datastore
    from toee_hermes.plugin.hooks import render_injection

    from hermes_runtime.postgres_gateway_store import PostgresGatewayStore

    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO semantic_lexicon "
            "(id, domain, entry_kind, surface_form, canonical_form, status, provenance) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'admin_manual')",
            # A test-only domain: migration 0024 already seeds `season=winter`
            # for `tire`, and UNIQUE(domain, surface_form) is the governed rule.
            [
                ("lex_pg_c", "company", "alias", "TOEEPG", "TOEE TIRE PG", "confirmed"),
                ("lex_pg_w", "pgtire", "default_rule", "season=winter", "pg winter tires", "confirmed"),
                ("lex_pg_p", "company", "alias", "PROPOSEDPG", "PROPOSED PG", "proposed"),
                ("lex_pg_r", "company", "alias", "REJECTEDPG", "REJECTED PG", "rejected"),
                ("lex_pg_t", "company", "alias", "RETIREDPG", "RETIRED PG", "retired"),
            ],
        )

    entries = PostgresGatewayStore(connection=conn).load_confirmed_lexicon()
    ids = {entry["id"] for entry in entries}
    assert "lex_pg_c" in ids and "lex_pg_w" in ids
    assert not ({"lex_pg_p", "lex_pg_r", "lex_pg_t"} & ids)

    # Rendered from the STORE's own dicts, with a date inside the winter window.
    text = render_injection(None, None, None, lexicon=entries, today=date(2026, 1, 15))
    assert text is not None
    assert '"TOEEPG" means "TOEE TIRE PG"' in text
    assert "ASK whether the customer wants pg winter tires" in text
