"""0.0.5 S06 follow-up: ONE clock read per turn (the Sep 30 / Oct 1 straddle).

``render_injection`` renders the seasonal ``default_rule`` that applies to
*today*, and the provenance ledger re-derives the same selection through
``glossary_entries``. When each of those reads the clock for ITSELF, a turn that
crosses midnight on Sep 30 / Oct 1 -- the ``WINTER_MONTHS`` edge in
``toee_hermes.lexicon`` -- renders ONE seasonal default into the prompt and
credits the OTHER in the ledger. That is the ledger asserting an entry reached a
reply that never carried it: the over-claim D4.3 forbids, and the thing that
inflates S26's per-entry score while hiding a genuinely unused row from S20's
zero-hit sweep.

**Why the clock here MOVES.** A test that freezes the clock and asserts "the
same date was passed to both calls" cannot go red on this defect: the bug IS
that two independent reads can differ, and a frozen clock makes them agree by
construction. So the fake below returns Sep 30 (``all_season``) on its FIRST
read and Oct 1 (``winter``) on every read after it, and the assertion is that
the ledger credits the row the prompt actually carried.

The fake is installed on all three modules that could reach a clock during a
turn -- ``hooks`` (where ``glossary_entries`` falls back when ``today`` is
``None``) and the two turn seams -- so what is pinned is "however the reads
land, the prompt and the ledger agree", not "the seam I already believe in got
used". Both seams are covered: a fix that lands on one is half a fix.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from hermes_runtime.copilot_turn import make_copilot_run_turn
from hermes_runtime.injection_ledger import LAYER_L7
from hermes_runtime.live import _scripted_openai_factory
from hermes_runtime.openrouter import (
    OPENROUTER_PRIMARY_MODEL,
    OpenRouterConfig,
    make_openrouter_run_turn,
)

from toee_hermes.lexicon import current_season

_FENCE = "<confirmed_lexicon>"

# The straddle. Sep 30 is outside WINTER_MONTHS, Oct 1 is the first day inside
# it, so the two reads resolve to DIFFERENT seasonal default_rule rows.
_BEFORE_MIDNIGHT = date(2025, 9, 30)
_AFTER_MIDNIGHT = date(2025, 10, 1)


def _row(entry_id, kind, surface, canonical, *, domain="tire"):
    return {
        "id": entry_id,
        "domain": domain,
        "entry_kind": kind,
        "surface_form": surface,
        "canonical_form": canonical,
        "status": "confirmed",
    }


# Both seasonal rows confirmed and in the read -- the real seeded situation, and
# the only one where "which season is it" has something to decide. The alias row
# is the control: it is season-independent, so it must be credited either way.
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


class _StraddlingClock:
    """A ``date`` stand-in whose successive reads cross the season boundary."""

    def __init__(self) -> None:
        self.reads = 0

    def today(self) -> date:
        self.reads += 1
        return _BEFORE_MIDNIGHT if self.reads == 1 else _AFTER_MIDNIGHT


def _install_clock(monkeypatch: pytest.MonkeyPatch) -> _StraddlingClock:
    """One clock, shared by every module a turn could read the date from."""
    import toee_hermes.plugin.hooks as hooks_mod

    import hermes_runtime.copilot_turn as copilot_mod
    import hermes_runtime.openrouter as openrouter_mod

    clock = _StraddlingClock()
    monkeypatch.setattr(hooks_mod, "date", clock)
    # raising=False: a seam that does not read the clock at all has no `date` to
    # replace, and that is exactly the broken state this file has to be able to
    # observe rather than error out on.
    monkeypatch.setattr(copilot_mod, "date", clock, raising=False)
    monkeypatch.setattr(openrouter_mod, "date", clock, raising=False)
    return clock


class _LedgerStore:
    """A gateway store stub whose lexicon read and ledger write are observable."""

    def __init__(self, entries=()) -> None:
        self._entries = list(entries)
        self.writes: list[dict] = []

    def load_case_identity(self, case_id):  # copilot seam
        return {
            "outcome": "unmatched_caller",
            "channel": "sms",
            "channel_identity": "+14165550001",
        }

    def load_customer_memory(self, binding_key):  # both seams
        return []

    def load_confirmed_lexicon(self):
        return list(self._entries)

    def record_injection_ledger(self, *, turn_ref, case_or_binding_ref, entries):
        self.writes.append({"turn_ref": turn_ref, "entries": list(entries)})


class _NoopQueue:
    """Swallows the S04 ``l6_review`` enqueue so no fork runs (DB-free)."""

    def enqueue(self, payload, *, job_type, **_kwargs) -> str:
        return "job_noop"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("TOOL_BACKEND", raising=False)
    monkeypatch.delenv("LEXICON_INJECTION", raising=False)
    monkeypatch.delenv("LEXICON_EXTERNAL_INJECTION", raising=False)
    monkeypatch.delenv("AGENT_EXPERIENCE_INJECTION", raising=False)
    monkeypatch.delenv("AGENT_EXPERIENCE_EXTERNAL_INJECTION", raising=False)
    monkeypatch.delenv("AGENT_EXPERIENCE_LEARNING", raising=False)


def _run_copilot(monkeypatch, *, store) -> str:
    import hermes_runtime.copilot_turn as copilot_mod

    captured: dict[str, str] = {}

    def capture(*, user_message: str, **_kwargs: object) -> dict[str, object]:
        captured["user_message"] = user_message
        return {"final_response": "DRAFT", "messages": []}

    monkeypatch.setattr(copilot_mod, "run_scripted_agent", capture)
    run_turn = make_copilot_run_turn(
        scripted_completions=[{"content": "unused"}], store=store, queue=_NoopQueue()
    )
    run_turn(channel="sms", case_id="case_l7_midnight")
    return captured.get("user_message", "")


def _run_external(monkeypatch, *, store) -> str:
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
        event_id="evt-l7-midnight",
        conversation_id="conv-l7-midnight",
        sms_session_id=None,
        from_phone="+14165550001",
        session_identity_snapshot=None,
    )
    run_turn(context, "205 55 16")
    return captured["user_message"]


def _rendered_seasonal_ref(msg: str) -> str:
    """The entry id of the ONE seasonal default the prompt actually carried."""
    lines = [line for line in msg.splitlines() if "Seasonal default" in line]
    assert len(lines) == 1, f"expected exactly one seasonal line, got: {lines}"
    return "lex_winter" if "winter tires" in lines[0] else "lex_all_season"


def _recorded_l7_refs(store: _LedgerStore) -> set[str]:
    assert len(store.writes) == 1, store.writes
    return {ref for layer, ref in store.writes[0]["entries"] if layer == LAYER_L7}


def test_the_straddle_fixture_can_actually_tell_the_two_reads_apart() -> None:
    # The premise this whole file rests on. If these two dates ever resolved to
    # the same season -- someone widens WINTER_MONTHS, someone edits the
    # constants above -- both assertions below would pass no matter how many
    # times the clock is read, and this file would be decoration.
    assert current_season(_BEFORE_MIDNIGHT) != current_season(_AFTER_MIDNIGHT)


def test_copilot_ledger_credits_the_default_the_draft_carried(monkeypatch) -> None:
    monkeypatch.setenv("LEXICON_INJECTION", "on")
    clock = _install_clock(monkeypatch)
    store = _LedgerStore(_CONFIRMED)

    msg = _run_copilot(monkeypatch, store=store)

    assert _FENCE in msg, "nothing was injected -- the assertion below is inert"
    rendered = _rendered_seasonal_ref(msg)
    # The prompt was rendered from the FIRST read, so it is the pre-midnight
    # season. Stated explicitly: it is what makes a post-midnight ledger row a
    # visible contradiction rather than a coin flip.
    assert rendered == "lex_all_season"
    assert "winter tires" not in msg
    assert _recorded_l7_refs(store) == {"lex_alias", rendered}
    assert clock.reads == 1, "the clock must be read once per turn, not per consumer"


def test_external_ledger_credits_the_default_the_reply_carried(monkeypatch) -> None:
    monkeypatch.setenv("LEXICON_EXTERNAL_INJECTION", "on")
    clock = _install_clock(monkeypatch)
    store = _LedgerStore(_CONFIRMED)

    msg = _run_external(monkeypatch, store=store)

    assert _FENCE in msg, "nothing was injected -- the assertion below is inert"
    rendered = _rendered_seasonal_ref(msg)
    assert rendered == "lex_all_season"
    assert "winter tires" not in msg
    assert _recorded_l7_refs(store) == {"lex_alias", rendered}
    assert clock.reads == 1, "the clock must be read once per turn, not per consumer"
