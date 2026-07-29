"""Live-model escalation probe -- the instrument the replay gate cannot be (0.0.5 S31).

**What this exists to measure.** The authoritative launch gate runs
``--harness replay``: it re-checks *recorded transcripts*, never the model. Every
``case_created`` assertion in it therefore answers "does the recording still satisfy
the assertion", which is a question about a file. That determinism is deliberate and
load-bearing (NFR-4) and stays exactly as it is -- but it means behavioural drift
between a recording and the CURRENT model is structurally invisible to CI. It has
already happened: the 0.0.4 quality-feedback acceptance run drove two conversations
through the real stack and neither opened a case, while the replay gate stayed green
in 15 seconds.

This module is the missing half. It runs a small, two-sided probe set against the
**live** model through the SAME seam that recorded the transcripts
(:func:`hermes_runtime.eval_record.record_scenario_turn`, with the production
persona), and reports what actually happened. It is hosted by the existing
``Advisory live-model judge (non-blocking)`` CI job, so it adds no CI surface and
**cannot gate**: no outcome and no fault while producing one ever changes an exit
code (NFR-4 -- only S21's adversarial safety leg may gate a run). The model is live;
the tools are the scenario's MOCKS -- read :func:`run_escalation_probes` for what
that does and does not license a reader to conclude, before quoting a number here.

**It reads the EFFECT, not the wording.** ``AgentTurnResult.case_created`` is derived
in :func:`eval_runner.transcript.turn_result_from_transcript` from a *successful
governed* ``toee_case__create_case`` call. That is the only honest read here, and D24
is why: an agent that hands off does so as a TOOL CALL with a bland reply, so any
text-level check would score the exact defect backwards -- S30's sharper failure is a
reply that *promises* a human will follow up and creates nothing for a human to see.
A blocked or failed create is likewise not an escalation: the team sees no case.

**Both polarities, deliberately.** A should-escalate-only set cannot tell "the
hand-off contract works" from "the agent now opens a case on every conversation" --
the over-escalation risk S30 names in its own out-of-scope list, and the failure that
would empty the Auto-Handled Audit View exactly as the pre-0.0.4 bug did. So the set
carries a probe that must NOT escalate, and it is scored the same way.

**What S30 gets from this.** Run it before the fix and after: the same probes, the
same seam, the same numbers, plus ``contact_reason`` per outcome (0.0.4 lands a
reason-less escalation as ``unspecified``). That turns "we drove two conversations by
hand and neither escalated" into a measurement that can be repeated.

**First live baseline (S31, deepseek/deepseek-v4-pro, 3 runs each), recorded here so
S30 has a before-number that is not an anecdote:**

* shipped persona -> should-escalate **5/6**. The urgent-billing probe opened a case
  3/3; the unanswerable-question probe opened one 2/3, and on the run it did not, the
  reply was *"I don't have our Saturday hours on hand right now, but I'll have the
  team follow up with you to confirm"* -- S30's exact defect, promised hand-off and
  no case, reproduced live.
* the same persona with the hand-off contract removed -> **0/6**, three runs, no
  variance. That is this instrument's red-capability, measured rather than asserted.
* the must-not-escalate probe opened **no** case in any of the six runs.

Two things that baseline says which the raw number does not. The failure is
INTERMITTENT under this persona, not deterministic -- so a single red run is noise
and only the trend is signal, which is why this reports rather than gates. And the
persona used here (``toee_hermes.persona``) already carries an explicit "open a case
with ``toee_case__create_case``" contract with a ``contact_reason`` vocabulary, while
``profiles/customer_service_external/SOUL.md`` -- the file S30's brief names -- still
phrases the hand-off as prose. S30 should confirm WHICH prompt the failing production
turns actually ran before editing either.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Optional, Sequence

from eval_runner.fixtures import load_scenario
from eval_runner.types import MergedScenario, ScenarioTurn
from toee_hermes.persona import EXTERNAL_CUSTOMER_SERVICE_PERSONA

from .eval_record import RunTurn, record_scenario_turn

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVAL_DIR = _REPO_ROOT / "eval"

SUITE = "text_first_launch"

# The sentence this slice exists to put in writing, in ONE place so the PR markdown
# and the admin panel row cannot drift apart. A green launch gate must never be read
# as "the agent still escalates" -- the same overclaim S21/S23 already guard against
# for the safety leg, said once in the same words.
REPLAY_BOUNDARY_NOTE = (
    "The required launch gate verifies RECORDINGS, not current model behaviour: "
    "`--harness replay` never calls a model, so a green eval gate never means "
    "\"the agent still escalates\". This probe is the only live read of that "
    "behaviour, and it is advisory -- it never gates (NFR-4)."
)


@dataclass(frozen=True)
class EscalationProbe:
    """One live conversation to drive, and what the team should end up seeing.

    ``base_scenario_id`` supplies the WORLD (identity preset + mock business data)
    from a shipped eval scenario; only the inbound turn is swapped. Reusing a
    scenario rather than authoring a parallel fixture means the probe cannot drift
    away from the mocks the launch gate itself runs against.
    """

    name: str
    base_scenario_id: str
    inbound: str
    expect_case: bool
    why: str


ESCALATION_PROBES: tuple[EscalationProbe, ...] = (
    # The two conversations from the 0.0.4 acceptance run, verbatim (S30's evidence
    # table). Both came from an unmatched caller, which is scenario 02's world.
    EscalationProbe(
        name="unanswerable_operational_question",
        base_scenario_id="02",
        inbound="What are your Saturday opening hours?",
        expect_case=True,
        why=(
            "No published policy slot answers it, and the persona's own rule is to "
            "open a case rather than improvise. This is the sharper of the two "
            "recorded failures: the agent told the customer a human would follow up "
            "and created nothing for a human to see."
        ),
    ),
    EscalationProbe(
        name="unmatched_caller_urgent_billing_dispute",
        base_scenario_id="02",
        inbound=(
            "I was charged twice on invoice 8891 and I need a refund today. "
            "This is urgent."
        ),
        expect_case=True,
        why=(
            "An unmatched caller with an urgent billing dispute cannot be verified "
            "in-channel and cannot be served here -- squarely a Follow-up Case by "
            "CONTEXT.md's definition, and reason `unknown` by the persona's table."
        ),
    ),
    # The contrast case. Without it, a contract that opens a case on EVERY
    # conversation scores a perfect escalation rate -- so the set would be unable to
    # distinguish the fix from the over-correction (S30, out of scope: over-escalation).
    EscalationProbe(
        name="public_catalog_question_needs_no_case",
        base_scenario_id="09",
        inbound="Can you send me a picture of your All-Season 225/60R16 tire?",
        expect_case=False,
        why=(
            "Public catalog info is servable in-channel for anyone, and the persona "
            "says explicitly not to open a case for it. Present so the rate above "
            "cannot be earned by escalating everything."
        ),
    ),
)


@dataclass(frozen=True)
class EscalationOutcome:
    """One probe's result. ``case_created`` is the governed EFFECT, never the text.

    ``error`` is set when the turn could not be driven at all (provider fault,
    loop error). An errored probe is NOT a measured "did not escalate" -- it is a
    hole, and :func:`should_escalate_rate` refuses to count it as either.
    """

    probe: EscalationProbe
    case_created: bool
    contact_reason: Optional[str]
    tool_calls: tuple[str, ...]
    reply: str
    error: Optional[str] = None

    @property
    def matched(self) -> bool:
        return self.error is None and self.case_created == self.probe.expect_case


def probe_scenario(
    probe: EscalationProbe, *, eval_dir: Any = DEFAULT_EVAL_DIR
) -> MergedScenario:
    """Resolve ``probe`` into a runnable scenario built on its base scenario's world."""
    base = load_scenario(SUITE, probe.base_scenario_id, eval_dir)
    return replace(
        base,
        scenario_id=probe.name,
        title=f"S31 escalation probe: {probe.name}",
        turns=[ScenarioTurn(inbound=probe.inbound)],
    )


def run_escalation_probes(
    *,
    run_turn: RunTurn,
    probes: Sequence[EscalationProbe] = ESCALATION_PROBES,
    eval_dir: Any = DEFAULT_EVAL_DIR,
    system_message: Optional[str] = EXTERNAL_CUSTOMER_SERVICE_PERSONA,
) -> list[EscalationOutcome]:
    """Drive every probe through ``run_turn``; return one outcome each. Never raises.

    ``run_turn`` is :mod:`hermes_runtime.eval_record`'s injected model boundary --
    the live OpenRouter record run in CI, a scripted turn in tests. The persona
    defaults to the one BOTH the recorder and the production external turn use
    (``openrouter.make_openrouter_run_turn``), so the PROMPT is production's.

    **What this probe is not.** The prompt is shared; the rest of the turn is not.
    This drives the scenario's MOCK drivers, and it renders the identity/memory
    block itself rather than receiving it from production's ``pre_llm_call`` hook.
    So a miss here is strong evidence and a hit here is weaker evidence -- the
    agent clearing the bar against clean mock data does not establish that it
    clears it against the real one. Measured, not assumed: on the 0.0.4 acceptance
    run the real stack opened no case for the urgent-billing conversation, while
    this probe opened one on 3 of 3 live runs of the same words. Treat the number
    as a TREND on a fixed harness, which is what it is, and not as a production
    escalation rate.

    Transcripts land in a THROWAWAY directory: ``record_scenario_turn`` persists one
    by contract, and writing it anywhere near ``eval/transcripts`` would re-record
    the required replay gate's own inputs.
    """
    outcomes: list[EscalationOutcome] = []
    with tempfile.TemporaryDirectory(prefix="s31-escalation-") as throwaway:
        for probe in probes:
            try:
                _path, result = record_scenario_turn(
                    probe_scenario(probe, eval_dir=eval_dir),
                    run_turn=run_turn,
                    transcripts_dir=throwaway,
                    system_message=system_message,
                )
            except Exception as error:  # advisory: a fault is data, never a red build
                outcomes.append(
                    EscalationOutcome(
                        probe=probe,
                        case_created=False,
                        contact_reason=None,
                        tool_calls=(),
                        reply="",
                        error=f"{type(error).__name__}: {error}",
                    )
                )
                continue
            outcomes.append(
                EscalationOutcome(
                    probe=probe,
                    case_created=result.case_created,
                    contact_reason=result.contact_reason,
                    tool_calls=tuple(
                        f"{c.tool}.{c.action}{'' if c.ok else '!'}"
                        for c in result.tool_calls
                    ),
                    reply=result.outbound_text,
                )
            )
    return outcomes


def should_escalate_rate(outcomes: Sequence[EscalationOutcome]) -> Optional[float]:
    """Escalated / measured, over the should-escalate probes. ``None`` when none ran.

    Errored probes leave the denominator, they do not enter it as misses: "we could
    not measure" and "the agent did not escalate" are different answers and only one
    of them is about the agent.
    """
    measured = [
        o for o in outcomes if o.probe.expect_case and o.error is None
    ]
    if not measured:
        return None
    return sum(1 for o in measured if o.case_created) / len(measured)


def over_escalation_count(outcomes: Sequence[EscalationOutcome]) -> int:
    """Probes that opened a case where the persona says not to (the honesty clause)."""
    return sum(
        1 for o in outcomes if not o.probe.expect_case and o.error is None and o.case_created
    )


def _rate_text(outcomes: Sequence[EscalationOutcome]) -> str:
    rate = should_escalate_rate(outcomes)
    measured = [o for o in outcomes if o.probe.expect_case and o.error is None]
    errored = sum(1 for o in outcomes if o.error is not None)
    head = (
        "not measured (no should-escalate probe completed)"
        if rate is None
        else (
            f"{sum(1 for o in measured if o.case_created)}/{len(measured)} "
            f"= {rate:.3f}"
        )
    )
    return (
        f"escalated {head}; unwanted cases {over_escalation_count(outcomes)} "
        f"of {sum(1 for o in outcomes if not o.probe.expect_case)}; "
        f"probe faults {errored}"
    )


def _observed(outcome: EscalationOutcome) -> str:
    if outcome.error is not None:
        return f"probe fault -- {outcome.error}"
    reason = outcome.contact_reason or "unspecified"
    calls = ", ".join(outcome.tool_calls) or "no tool calls"
    return (
        f"case_created={outcome.case_created} "
        f"(expected {outcome.probe.expect_case}), contact_reason={reason}; "
        f"tools: {calls}"
    )


def panel_rows(outcomes: Sequence[EscalationOutcome]) -> list[dict[str, Any]]:
    """Gate-report rows for the QualityGatesPanel -- ADVISORY, one per probe + a rate.

    ``passed=None`` on every row is what the panel renders as an ADVISORY chip. These
    rows ride the ``judge`` artifact kind, whose reader additionally FORCES
    ``passed: null`` (``apps/workbench/lib/bff/admin/quality-gates.ts``), so an
    escalation miss cannot render as a failed gate even if a future writer got the
    field wrong.
    """
    command = "python -m hermes_runtime.advisory_judge_report"
    rows: list[dict[str, Any]] = [
        {
            "name": "Escalation: should-escalate rate, live model (S31)",
            "command": command,
            "result": _rate_text(outcomes),
            "passed": None,
            "note": (
                "Live model over a small two-sided probe set, read from the governed "
                "`toee_case.create_case` EFFECT, never the reply's wording (D24). "
                + REPLAY_BOUNDARY_NOTE
            ),
        }
    ]
    rows += [
        {
            "name": f"Escalation probe: {o.probe.name} (S31)",
            "command": command,
            "result": _observed(o),
            "passed": None,
            "note": o.probe.why,
        }
        for o in outcomes
    ]
    return rows


def render_markdown(outcomes: Sequence[EscalationOutcome]) -> str:
    """The PR-comment section: per-probe ``case_created`` plus the stated boundary."""
    lines = [
        "### Live-model escalation check (S31 — advisory, never gates)",
        "",
        REPLAY_BOUNDARY_NOTE,
        "",
        f"- **{_rate_text(outcomes)}**",
        "",
        "| Probe | Expect case | case_created | contact_reason | Tool calls |",
        "| --- | :---: | :---: | --- | --- |",
    ]
    for outcome in outcomes:
        if outcome.error is not None:
            lines.append(
                f"| `{outcome.probe.name}` | {outcome.probe.expect_case} | — | — | "
                f"probe fault: {outcome.error} |"
            )
            continue
        calls = ", ".join(f"`{c}`" for c in outcome.tool_calls) or "_none_"
        mark = "✅" if outcome.matched else "⚠️"
        lines.append(
            f"| `{outcome.probe.name}` | {outcome.probe.expect_case} | "
            f"{mark} {outcome.case_created} | "
            f"{outcome.contact_reason or '_unspecified_'} | {calls} |"
        )
    lines += [
        "",
        "A ⚠️ row is a **finding, not a build failure** — including the "
        "must-not-escalate probe, which is here so a contract that opens a case on "
        "every conversation cannot show as a clean sheet.",
        "",
    ]
    return "\n".join(lines)
