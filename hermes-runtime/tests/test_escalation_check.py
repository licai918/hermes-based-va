"""The live-model escalation probe (0.0.5 S31, carry-in defect).

The launch gate replays recordings, so behavioural drift between a recording and
the CURRENT model is structurally invisible to CI. This probe is the only thing
that reads the live model for escalation, and these tests pin the three
properties that make it worth having:

* it reads the EFFECT (a successful governed ``toee_case__create_case``), never
  the reply's wording -- D24's whole point, and the reason a prose promise of a
  human hand-off with no case is exactly what it catches;
* it can go red in BOTH directions -- a should-escalate probe that opens no case
  AND a must-not-escalate probe that opens one, so a "fix" that escalates
  everything cannot show as a clean sheet;
* it is ADVISORY -- no outcome, and no fault while producing one, can change an
  exit code (NFR-4: only S21's safety leg may gate).

No network: ``run_turn`` is the injected model boundary, exactly as
``hermes_runtime.eval_record`` defines it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_runtime.escalation_check import (
    ESCALATION_PROBES,
    REPLAY_BOUNDARY_NOTE,
    over_escalation_count,
    panel_rows,
    probe_scenario,
    render_markdown,
    run_escalation_probes,
    should_escalate_rate,
)

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"
TRANSCRIPTS_DIR = EVAL_DIR / "transcripts"


# --- scripted turns -------------------------------------------------------


def _assistant_call(call_id: str, name: str, arguments: dict) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }


def _tool_result(call_id: str, name: str, content: object) -> dict:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "name": name,
        "content": json.dumps(content),
    }


def _case_turn(final_response: str, *, contact_reason: str = "unknown") -> dict:
    """A turn that actually opens a case (the governed effect)."""
    args = {"contact_reason": contact_reason, "urgency": "normal", "summary": "s"}
    return {
        "final_response": final_response,
        "messages": [
            _assistant_call("c1", "toee_case__create_case", args),
            _tool_result("c1", "toee_case__create_case", {"case_id": "case_1", **args}),
        ],
    }


def _no_case_turn(final_response: str) -> dict:
    """A turn that opens nothing -- whatever the reply promises."""
    return {"final_response": final_response, "messages": []}


def _scripted(by_probe: dict[str, dict]):
    """A ``run_turn`` that answers per probe, keyed by the probe's inbound text."""

    def run_turn(*, user_message: str, system_message=None, governed_tool_names=()):
        for probe in ESCALATION_PROBES:
            if probe.inbound in user_message:
                return by_probe[probe.name]
        raise AssertionError(f"no scripted turn matched: {user_message!r}")

    return run_turn


# --- the probe set itself -------------------------------------------------


def test_the_probe_set_carries_both_polarities() -> None:
    # A should-escalate-only set cannot tell "the contract works" from "the agent
    # now opens a case on every turn" -- S30's named out-of-scope risk. The set
    # needs at least one probe the operation must EXCLUDE.
    expectations = {p.expect_case for p in ESCALATION_PROBES}
    assert expectations == {True, False}
    assert sum(1 for p in ESCALATION_PROBES if p.expect_case) >= 2


def test_every_probe_resolves_against_the_shipped_eval_mocks() -> None:
    for probe in ESCALATION_PROBES:
        scenario = probe_scenario(probe, eval_dir=EVAL_DIR)
        assert scenario.turns[0].inbound == probe.inbound
        assert scenario.scenario_id == probe.name


# --- the load-bearing property: the EFFECT, not the wording ---------------


def test_a_promised_hand_off_with_no_case_call_is_a_miss() -> None:
    # D24: behaviour expressed as a tool call is invisible to a text gate, and the
    # inverse is the defect S30 records -- the agent SAID a human would follow up
    # and created nothing. The probe must score the second reply a miss and the
    # first (bland text, real case) a hit, i.e. the exact opposite of what any
    # wording-based read would conclude.
    escalating = [p for p in ESCALATION_PROBES if p.expect_case]
    assert len(escalating) >= 2
    promise = (
        "I don't have our Saturday hours on hand at the moment, but I've asked "
        "the team to reach out to you directly."
    )
    outcomes = run_escalation_probes(
        run_turn=_scripted(
            {
                escalating[0].name: _case_turn("Thanks, noted."),
                escalating[1].name: _no_case_turn(promise),
                **{
                    p.name: _no_case_turn("Here's the public info.")
                    for p in ESCALATION_PROBES
                    if not p.expect_case
                },
            }
        ),
        eval_dir=EVAL_DIR,
    )
    by_name = {o.probe.name: o for o in outcomes}

    assert by_name[escalating[0].name].case_created is True
    assert by_name[escalating[0].name].matched is True
    assert by_name[escalating[1].name].case_created is False
    assert by_name[escalating[1].name].matched is False
    # And the promise text is not what decided it.
    assert "reach out" in by_name[escalating[1].name].reply


def test_a_failed_case_call_does_not_count_as_an_escalation() -> None:
    # `case_created` is a SUCCESSFUL governed call. A blocked/failed create is the
    # agent trying and the system refusing -- not an escalation the team can see.
    escalating = [p for p in ESCALATION_PROBES if p.expect_case]
    failed = {
        "final_response": "I've asked the team to follow up.",
        "messages": [
            _assistant_call("c1", "toee_case__create_case", {"contact_reason": "unknown"}),
            _tool_result(
                "c1",
                "toee_case__create_case",
                {"error": "nope", "error_class": "policy_blocked"},
            ),
        ],
    }
    outcomes = run_escalation_probes(
        run_turn=_scripted(
            {
                p.name: (failed if p.expect_case else _no_case_turn("public"))
                for p in ESCALATION_PROBES
            }
        ),
        eval_dir=EVAL_DIR,
    )
    for outcome in outcomes:
        if outcome.probe.expect_case:
            assert outcome.case_created is False
            assert outcome.matched is False
    assert should_escalate_rate(outcomes) == 0.0
    assert len(escalating) >= 2


# --- red in both directions ----------------------------------------------


def test_over_escalation_is_a_miss_too() -> None:
    # The must-not-escalate probe exists so a contract that opens a case on every
    # conversation cannot report a perfect escalation rate (S30 out-of-scope note).
    outcomes = run_escalation_probes(
        run_turn=_scripted({p.name: _case_turn("ok") for p in ESCALATION_PROBES}),
        eval_dir=EVAL_DIR,
    )

    assert should_escalate_rate(outcomes) == 1.0  # every should-escalate probe hit
    assert over_escalation_count(outcomes) == 1  # ...and the guard still fires
    assert any(o.matched is False for o in outcomes)


def test_a_clean_sheet_is_reachable() -> None:
    outcomes = run_escalation_probes(
        run_turn=_scripted(
            {
                p.name: (_case_turn("ok") if p.expect_case else _no_case_turn("public"))
                for p in ESCALATION_PROBES
            }
        ),
        eval_dir=EVAL_DIR,
    )

    assert should_escalate_rate(outcomes) == 1.0
    assert over_escalation_count(outcomes) == 0
    assert all(o.matched for o in outcomes)


def test_the_contact_reason_travels_with_the_outcome() -> None:
    # S30 needs "a case with a non-null contact_reason", and 0.0.4 lands a reason-less
    # escalation as `unspecified`. Reading it here is what lets S30 prove the half of
    # its fix that `case_created` alone cannot show.
    outcomes = run_escalation_probes(
        run_turn=_scripted(
            {
                p.name: (
                    _case_turn("ok", contact_reason="unknown")
                    if p.expect_case
                    else _no_case_turn("public")
                )
                for p in ESCALATION_PROBES
            }
        ),
        eval_dir=EVAL_DIR,
    )
    reasons = {o.probe.name: o.contact_reason for o in outcomes}
    for probe in ESCALATION_PROBES:
        assert reasons[probe.name] == ("unknown" if probe.expect_case else None)


# --- the required replay gate is untouched --------------------------------


def test_probing_never_touches_the_replay_gate_transcripts() -> None:
    # The required wall replays `eval/transcripts`. A probe that wrote there would
    # silently re-record the gate's own inputs (S31: "runtime and determinism
    # unchanged"; S23's scenario-17 warning about re-recording inside a slice).
    before = {p: p.stat().st_size for p in sorted(TRANSCRIPTS_DIR.rglob("*.json"))}
    assert before, "expected recorded transcripts to exist"

    run_escalation_probes(
        run_turn=_scripted({p.name: _no_case_turn("hi") for p in ESCALATION_PROBES}),
        eval_dir=EVAL_DIR,
    )

    after = {p: p.stat().st_size for p in sorted(TRANSCRIPTS_DIR.rglob("*.json"))}
    assert after == before


# --- advisory: it reports, it never gates ---------------------------------


def test_panel_rows_are_advisory_and_name_every_probe() -> None:
    outcomes = run_escalation_probes(
        run_turn=_scripted({p.name: _no_case_turn("hi") for p in ESCALATION_PROBES}),
        eval_dir=EVAL_DIR,
    )
    rows = panel_rows(outcomes)

    # Every row advisory: `passed=None` is what the panel renders as an ADVISORY
    # chip, and what keeps a red probe from ever reading as a failed gate.
    assert rows and all(row["passed"] is None for row in rows)
    for probe in ESCALATION_PROBES:
        assert any(probe.name in row["name"] for row in rows)
    # The boundary the whole slice exists to state travels with the numbers.
    assert any(REPLAY_BOUNDARY_NOTE in (row["note"] or "") for row in rows)


def test_markdown_reports_case_created_per_probe_and_states_the_boundary() -> None:
    outcomes = run_escalation_probes(
        run_turn=_scripted(
            {
                p.name: (_case_turn("ok") if p.expect_case else _no_case_turn("public"))
                for p in ESCALATION_PROBES
            }
        ),
        eval_dir=EVAL_DIR,
    )
    markdown = render_markdown(outcomes)

    for probe in ESCALATION_PROBES:
        assert probe.name in markdown
    assert REPLAY_BOUNDARY_NOTE in markdown
    assert "advisory" in markdown.lower()


def test_a_probe_that_explodes_is_recorded_not_raised() -> None:
    # Advisory means advisory (NFR-4/FR-29): a model fault is data on the report,
    # never an exception the CI job turns into a red build.
    def boom(**_kwargs):
        raise RuntimeError("provider on fire")

    outcomes = run_escalation_probes(run_turn=boom, eval_dir=EVAL_DIR)

    assert len(outcomes) == len(ESCALATION_PROBES)
    assert all(o.error is not None for o in outcomes)
    assert all(o.case_created is False for o in outcomes)
    # An errored run is NOT a measured zero: the rate refuses to fabricate one.
    assert should_escalate_rate(outcomes) is None
    assert "provider on fire" in render_markdown(outcomes)


@pytest.mark.parametrize("probe", ESCALATION_PROBES, ids=lambda p: p.name)
def test_each_probe_states_why_it_expects_what_it_expects(probe) -> None:
    assert probe.why.strip()
