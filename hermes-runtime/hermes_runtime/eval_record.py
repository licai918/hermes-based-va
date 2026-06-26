"""Record a real ``AIAgent`` turn per Launch Eval scenario for deterministic replay.

This is the dependency-gated adapter :mod:`eval_runner.recorder` names. It boots the
External Customer Service Profile with the *scenario's* MockDriver + External-profile
Tool Gate + Session Identity Snapshot (:func:`hermes_runtime.boot.boot_profile_eval`),
drives one real ``AIAgent`` turn through an injected model boundary, captures
``{final_response, messages}`` exactly as ``run_agent`` returns, persists it via
:func:`eval_runner.recorder.record_turn`, and returns the parsed
:class:`eval_runner.harness.AgentTurnResult` (ADR-0071, ADR-0121, ADR-0139).

The model boundary is the only seam tests fake (a scripted provider); production
injects the real OpenRouter/DeepSeek run. The agent loop, governed dispatch through
the scenario's driver, transcript capture, and replay parser are all real.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, NamedTuple, Optional

from eval_runner.fixtures import load_suite
from eval_runner.harness import (
    AgentTurnResult,
    create_scenario_driver,
    scenario_tool_gate,
)
from eval_runner.recorder import record_turn
from eval_runner.replay import PathLike
from eval_runner.turn_result import build_scenario_turn_result
from eval_runner.types import MergedScenario, ScenarioTurn
from toee_hermes.plugin.hooks import render_injection
from toee_hermes.plugin.profiles import EXTERNAL

from hermes_runtime.boot import boot_profile_eval
from hermes_runtime.live import run_agent_turn
from hermes_runtime.openrouter import (
    _DEFAULT_MAX_ITERATIONS,
    OpenRouterConfig,
    default_is_retryable,
    make_fallback_openai_factory,
    resolve_openrouter_config,
)

# The model boundary: run a real ``AIAgent`` turn for the booted profile's tools and
# return the captured ``{final_response, messages}``. Tests inject a scripted run;
# production injects the real OpenRouter-backed run (ADR-0009). It is called with
# ``user_message``, ``system_message``, and ``governed_tool_names`` keyword args.
RunTurn = Callable[..., Mapping[str, Any]]


def _turn_text(turn: ScenarioTurn) -> str:
    """The inbound text of one turn: a plain SMS string or an email ``{body, subject}``."""
    inbound = turn.inbound
    if isinstance(inbound, dict):
        subject = inbound.get("subject")
        body = inbound.get("body", "")
        return f"Subject: {subject}\n\n{body}" if subject else str(body)
    return str(inbound)


def _injected_context(scenario: MergedScenario) -> Optional[str]:
    """The Session Identity Snapshot + Customer Memory block for this scenario.

    In eval the ``pre_llm_call`` providers are unwired (``register_eval`` installs no
    snapshot/memory provider), so the model would never see the identity or injected
    preference that disclosure / honored-preference behavior depends on. We render the
    same block production's ``pre_llm_call`` hook appends (ADR-0043, ADR-0113, ADR-0140)
    and prepend it to the turn, using the identical renderer for parity.
    """
    memory = [
        {"slot": slot, "value": value}
        for slot, value in (scenario.memory_preset or {}).items()
    ]
    return render_injection(scenario.session_identity, memory)


def scenario_user_message(scenario: MergedScenario) -> str:
    """Compose one user message from the scenario's inbound turns.

    Prepends the injected identity/memory context (mirroring production's pre_llm_call
    injection, which is unwired in eval) so the model sees who it is talking to. The two
    multi-turn text scenarios (03 disambiguation, 05 payment-link) are joined into one
    exchange so a single recording captures the full inbound context.
    """
    inbound = "\n\n".join(_turn_text(turn) for turn in scenario.turns)
    context = _injected_context(scenario)
    return f"{context}\n\n{inbound}" if context else inbound


def record_scenario_turn(
    scenario: MergedScenario,
    *,
    run_turn: RunTurn,
    transcripts_dir: PathLike,
    system_message: Optional[str] = None,
) -> tuple[Path, AgentTurnResult]:
    """Record one External-profile turn for ``scenario``; return ``(path, result)``.

    Boots the External profile with the scenario's driver/gate/identity, drives the
    turn through ``run_turn`` (the injected model boundary), persists the captured
    transcript for deterministic replay, and returns the parsed AgentTurnResult with
    structural disclosures merged in (matching :class:`ReplayAgentHarness`, ADR-0056).
    """
    driver = create_scenario_driver(scenario.mock_context)
    gate = scenario_tool_gate(scenario)
    booted = boot_profile_eval(
        EXTERNAL, driver=driver, gate=gate, identity=scenario.session_identity
    )

    turn = run_turn(
        user_message=scenario_user_message(scenario),
        system_message=system_message,
        governed_tool_names=booted.tool_names,
    )

    path = record_turn(turn=turn, scenario=scenario, transcripts_dir=transcripts_dir)

    result = build_scenario_turn_result(
        scenario,
        final_response=turn.get("final_response", "") or "",
        messages=list(turn.get("messages", []) or []),
    )
    return path, result


class RecordedScenario(NamedTuple):
    """One recorded scenario: its id, the persisted transcript path, and parsed result."""

    scenario_id: str
    path: Path
    result: AgentTurnResult


def record_suite(
    suite: str,
    *,
    eval_dir: PathLike,
    transcripts_dir: PathLike,
    run_turn: RunTurn,
    system_message: Optional[str] = None,
    scenario_ids: Optional[Iterable[str]] = None,
    on_scenario: Optional[Callable[[RecordedScenario], None]] = None,
) -> list[RecordedScenario]:
    """Record every scenario in ``suite``; return one :class:`RecordedScenario` each.

    Loads the merged suite (:func:`eval_runner.fixtures.load_suite`) and records each
    scenario through :func:`record_scenario_turn`, persisting one transcript per
    scenario for deterministic ``--harness replay`` (ADR-0121). ``scenario_ids``
    restricts recording to a subset (compared as zero-padded ids) so the iterate loop
    can re-record only the scenarios that failed replay. ``on_scenario`` is called
    after each recording for progress reporting in a long live run.
    """
    wanted = {sid.zfill(2) for sid in scenario_ids} if scenario_ids is not None else None
    recorded: list[RecordedScenario] = []
    for scenario in load_suite(suite, eval_dir):
        if wanted is not None and scenario.scenario_id.zfill(2) not in wanted:
            continue
        path, result = record_scenario_turn(
            scenario,
            run_turn=run_turn,
            transcripts_dir=transcripts_dir,
            system_message=system_message,
        )
        entry = RecordedScenario(scenario.scenario_id, path, result)
        recorded.append(entry)
        if on_scenario is not None:
            on_scenario(entry)
    return recorded


def make_openrouter_record_run(
    *,
    config: Optional[OpenRouterConfig] = None,
    openai_factory: Any = None,
    max_iterations: int = _DEFAULT_MAX_ITERATIONS,
    is_retryable: Callable[[BaseException], bool] = default_is_retryable,
) -> RunTurn:
    """Build the production record seam: one real ``AIAgent`` turn over OpenRouter.

    Returns a ``run_turn(*, user_message, system_message, governed_tool_names)`` that
    drives a real agent loop against OpenRouter's pinned primary model with
    per-completion fallback (ADR-0009). ``config`` defaults to
    :func:`resolve_openrouter_config` (resolved per turn, fail-closed on a missing
    key); ``openai_factory`` injects a deterministic provider in tests (the real
    OpenAI client is used otherwise). The caller (``record_scenario_turn``) owns
    profile booting, so this only supplies the model boundary.
    """

    def run_turn(
        *,
        user_message: str,
        system_message: Optional[str] = None,
        governed_tool_names: Any = (),
    ) -> Mapping[str, Any]:
        resolved = config or resolve_openrouter_config()
        base_factory = openai_factory
        if base_factory is None:
            from openai import OpenAI

            base_factory = OpenAI
        factory = make_fallback_openai_factory(
            base_factory=base_factory,
            fallback_model=resolved.fallback_model,
            is_retryable=is_retryable,
        )
        return run_agent_turn(
            user_message=user_message,
            system_message=system_message,
            base_url=resolved.base_url,
            api_key=resolved.api_key,
            model=resolved.model,
            max_iterations=max_iterations,
            openai_factory=factory,
            governed_tool_names=governed_tool_names,
        )

    return run_turn
