"""Advisory LLM-judge wiring for a scenario transcript (S08; PRD §9, §6.2 R5/R6, PAC-4).

The deterministic replay gate (:mod:`eval_runner.assertions`, :mod:`eval_runner.turn_result`,
:mod:`eval_runner.replay`) keeps ONLY the mechanical hard assertions (``forbid_inferred_upsert``,
``text.must_not_contain``, ...). The freebie that used to force ``honored_injected_preference=True``
onto every scenario carrying a ``memory_preset`` is gone (S08), and nothing mechanical replaces
it there: a genuine "honored" / "stayed silent" judgment needs a real LLM read of the reply,
which is exactly the non-deterministic call the replay gate must never make (PRD §9 decision 4 —
"the LLM-judge is advisory, recorded, never gating, so the gate cannot flake").

This module is that judgment, wired one layer OUTSIDE the gate: given a scenario's transcript
(its reply + its ``memory_preset``) and which leg to check, it composes the S06 judge's fenced
prompt (:func:`eval_runner.judge.judge_reply`) and returns the resulting
:class:`eval_runner.judge.JudgeVerdict` — recorded/reported, never raised on, never fed back
into :func:`eval_runner.assertions.evaluate_scenario`.

Callers with a live :class:`eval_runner.judge.JudgeClient` invoke this where a live LLM is
actually available: during recording, or the separate ``hermes_runtime.judge_eval`` advisory
command — never from ``--harness replay``. ``hermes/tests/test_eval_advisory.py`` pins that
boundary by grepping every deterministic-path module's source for the word "judge".
"""

from __future__ import annotations

from typing import Optional

from .harness import AgentTurnResult
from .judge import JudgeClient, JudgeLeg, JudgeVerdict, judge_reply
from .types import MergedScenario


def judge_scenario_leg(
    scenario: MergedScenario,
    result: AgentTurnResult,
    *,
    leg: JudgeLeg,
    client: JudgeClient,
    model: Optional[str] = None,
) -> JudgeVerdict:
    """Judge one scenario's reply for one leg — advisory only, never gates.

    The two inputs are exactly the transcript pieces the leg needs: the turn's
    customer-facing text (``result.outbound_text``) and the scenario's own
    ``memory_preset`` as the injected memory. One call == one recorded
    :class:`JudgeVerdict`.
    """
    return judge_reply(
        reply=result.outbound_text,
        leg=leg,
        injected_memory=scenario.memory_preset,
        client=client,
        model=model,
    )
