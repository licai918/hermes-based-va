"""Record a real ``internal_copilot`` draft turn per Launch Eval scenario (S07).

Sibling to :mod:`hermes_runtime.eval_record` (its ``record_scenario_turn`` is the
template this mirrors), but drives the UNBOUND copilot draft seam
(:func:`hermes_runtime.copilot_turn.make_copilot_run_turn`) instead of the bound
External turn, so a copilot-path scenario (e.g. 30's no-inferred-write regression,
PRD FR-3/R4) gets the SAME persist/parse pipeline --
:func:`eval_runner.recorder.record_turn` and
:func:`eval_runner.turn_result.build_scenario_turn_result`, both used completely
unmodified -- as the External scenarios (S05 spike: GO-WITH-PLUMBING, zero changes
needed in ``eval_runner`` itself).

A scenario has no case/thread row in Postgres, so :class:`_ScenarioCaseStore`
answers ``load_case_identity``/``load_customer_memory`` straight from the
scenario's already-merged ``session_identity``/``memory_preset`` (the S02/S07
identity shape :func:`toee_hermes.drivers.mock.memory.binding_key_from_identity`
expects) instead of a real case row -- mirrors ``_NullStore`` in
``tests/test_copilot_memory_write_overlay.py``, scenario-scoped rather than empty.

The copilot ``channel`` (sms/email/internal_note/chat -- which system message
frames the draft) is a different axis from the scenario's own ``channel`` field
(sms/email -- which structural disclosures apply, ADR-0056); the recorder
picks it explicitly rather than reusing the scenario's value (S05 spike "naming
trap").
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from eval_runner.harness import AgentTurnResult
from eval_runner.recorder import record_turn
from eval_runner.replay import PathLike
from eval_runner.turn_result import build_scenario_turn_result
from eval_runner.types import MergedScenario

from hermes_runtime.copilot_turn import _DEFAULT_MAX_ITERATIONS, make_copilot_run_turn
from hermes_runtime.eval_record import _turn_text
from hermes_runtime.openrouter import OpenRouterConfig


class _ScenarioCaseStore:
    """Answers a copilot draft turn's case-identity/memory read from a scenario.

    One scenario is one case: both methods just read the ``MergedScenario`` closed
    over here, regardless of the ``case_id``/``binding_key`` argument passed in (kept
    for call-shape parity with :class:`hermes_runtime.postgres_gateway_store.PostgresGatewayStore`).
    """

    def __init__(self, scenario: MergedScenario) -> None:
        self._scenario = scenario

    def load_case_identity(self, case_id: str) -> Optional[dict[str, Any]]:
        return self._scenario.session_identity

    def load_customer_memory(self, binding_key: str) -> list[dict[str, Any]]:
        return [
            {"slot": slot, "value": value}
            for slot, value in (self._scenario.memory_preset or {}).items()
        ]


def scenario_copilot_prompt(scenario: MergedScenario) -> str:
    """The copilot draft ``prompt``: the scenario's inbound turn text, unadorned.

    Unlike :func:`hermes_runtime.eval_record.scenario_user_message`, no identity/
    memory block is prepended here -- the copilot turn injects Customer Memory
    itself (:func:`hermes_runtime.copilot_turn.make_copilot_run_turn`'s
    ``_load_case_memory``) and never surfaces identity as a snapshot (ADR-0147
    decision 2), so prepending one here would double-inject it.
    """
    return "\n\n".join(_turn_text(turn) for turn in scenario.turns)


def record_copilot_scenario_turn(
    scenario: MergedScenario,
    *,
    transcripts_dir: PathLike,
    channel: str = "sms",
    scripted_completions: Optional[Sequence[Mapping[str, Any]]] = None,
    config: Optional[OpenRouterConfig] = None,
    openai_factory: Any = None,
    max_iterations: int = _DEFAULT_MAX_ITERATIONS,
) -> tuple[Path, AgentTurnResult]:
    """Record one copilot draft turn for ``scenario``; return ``(path, result)``.

    Builds the copilot ``run_turn`` via :func:`make_copilot_run_turn` -- its own
    ``scripted_completions`` -> keyed-OpenRouter -> keyless-stub precedence,
    unmodified -- bound to a scenario-scoped :class:`_ScenarioCaseStore`, drives one
    draft, and persists/parses it through the eval runner's existing ``record_turn``
    / ``build_scenario_turn_result`` -- the exact pipeline
    :func:`hermes_runtime.eval_record.record_scenario_turn` uses for the External
    path, so a copilot scenario replays identically (ADR-0121).
    """
    run_turn = make_copilot_run_turn(
        scripted_completions=scripted_completions,
        config=config,
        openai_factory=openai_factory,
        max_iterations=max_iterations,
        store=_ScenarioCaseStore(scenario),
    )

    turn = run_turn(
        channel=channel,
        case_id=f"eval-{scenario.scenario_id}",
        prompt=scenario_copilot_prompt(scenario),
    )

    path = record_turn(
        turn={"final_response": turn.get("draft", ""), "messages": turn.get("messages", [])},
        scenario=scenario,
        transcripts_dir=transcripts_dir,
    )

    result = build_scenario_turn_result(
        scenario,
        final_response=turn.get("draft", "") or "",
        messages=list(turn.get("messages", []) or []),
    )
    return path, result
