"""Which prompt the EXTERNAL turn actually sends, and what it says about hand-offs.

0.0.5 S30, and the reason this file exists at all is D25. S30's brief names
``hermes/profiles/customer_service_external/SOUL.md`` as the surface to fix. It is
not the prompt. ``hermes_runtime.live.run_agent_turn`` -- the one seam BOTH the
production external turn (``openrouter.py:582``) and the eval recorder go through --
builds its ``AIAgent`` with ``skip_context_files=True`` and leaves
``load_soul_identity`` at its ``False`` default, and the SDK gates SOUL.md on exactly
that pair (``agent/system_prompt.py``: ``if agent.load_soul_identity or not
agent.skip_context_files``). So SOUL.md is never sent, even though
``gateway_composition._apply_external_profile_env`` points ``HERMES_HOME`` straight
at the home that contains it.

That is not a fact worth re-deriving by reading three packages, and it is a fact a
future slice will get wrong in exactly the way S30 nearly did -- edit SOUL.md, watch
the suite stay green, ship, and leave the defect alive. So it is pinned here against
the REAL seam rather than asserted in a comment: the test drives a turn and reads the
system prompt the provider was actually handed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from toee_hermes.persona import EXTERNAL_CUSTOMER_SERVICE_PERSONA

from hermes_runtime.gateway_composition import _EXTERNAL_PROFILE_HOME
from hermes_runtime.live import run_agent_turn

# A sentence that exists in SOUL.md and nowhere in the persona. If SOUL.md ever
# reaches the model, this is what shows up.
_SOUL_ONLY = "unified Toee Tire greeting"
_PERSONA_OPENING = "You are the customer-service assistant for Toee Tire"


class _CapturingOpenAI:
    """A provider double that records the messages it was called with."""

    seen: list[list[dict[str, Any]]] = []

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        outer = self

        class _Completions:
            def create(self, **kwargs: Any) -> Any:
                outer.seen.append(kwargs.get("messages") or [])
                message = type(
                    "_M", (), {"content": "ok", "tool_calls": None, "role": "assistant"}
                )()
                choice = type("_C", (), {"message": message, "finish_reason": "stop"})()
                return type(
                    "_R", (), {"choices": [choice], "usage": None, "id": "x", "model": "x"}
                )()

        self.chat = type("_Chat", (), {"completions": _Completions()})()


def _system_prompt_sent(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> str:
    """Drive one turn through the production seam; return the system prompt sent."""
    # Exactly what gateway_composition._apply_external_profile_env() does in
    # production: HERMES_HOME is the profile home, and it DOES contain SOUL.md.
    monkeypatch.setenv("HERMES_HOME", str(_EXTERNAL_PROFILE_HOME))
    monkeypatch.setattr(_CapturingOpenAI, "seen", [], raising=False)
    kwargs: dict[str, Any] = {
        "user_message": "What are your Saturday opening hours?",
        "system_message": EXTERNAL_CUSTOMER_SERVICE_PERSONA,
        "base_url": "http://capture.invalid/v1",
        "api_key": "sk-capture",
        "model": "capture-model",
        "max_iterations": 1,
        "openai_factory": _CapturingOpenAI,
        "governed_tool_names": ["toee_case__create_case"],
        "tools_exclusive": True,
    }
    kwargs.update(overrides)
    run_agent_turn(**kwargs)
    messages = _CapturingOpenAI.seen[0]
    return "\n\n".join(
        str(m.get("content") or "") for m in messages if m.get("role") == "system"
    )


def test_soul_md_exists_on_the_profile_home_production_points_at() -> None:
    """The premise. Without this the next test would pass for the wrong reason.

    If SOUL.md were simply absent from the home, "SOUL.md is not in the prompt"
    would be true and meaningless. It is present, and still not sent.
    """
    soul = Path(_EXTERNAL_PROFILE_HOME) / "SOUL.md"
    assert soul.is_file()
    assert _SOUL_ONLY in soul.read_text(encoding="utf-8")


def test_the_external_turn_sends_the_persona_and_never_soul_md(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D25: production runs ``toee_hermes.persona``; SOUL.md reaches no model.

    Goes red if ``run_agent_turn`` stops passing ``skip_context_files=True`` (or
    starts passing ``load_soul_identity=True``) -- i.e. the moment SOUL.md becomes
    load-bearing and the two files start silently competing to be the prompt.
    """
    prompt = _system_prompt_sent(monkeypatch)

    assert _PERSONA_OPENING in prompt
    assert EXTERNAL_CUSTOMER_SERVICE_PERSONA.strip() in prompt
    assert _SOUL_ONLY not in prompt


def test_the_hand_off_contract_reaches_the_model_not_just_the_source_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tool name and the reason vocabulary survive prompt assembly.

    The SDK truncates oversized context (``_dynamic_context_file_max_chars``), so
    "it is in persona.py" is not the same claim as "the model was told". S31
    measured the contract's weight -- deleting it took the live should-escalate
    rate from 5/6 to 0/6 -- which is why its arrival is checked at the wire.
    """
    prompt = _system_prompt_sent(monkeypatch)

    assert "toee_case__create_case" in prompt
    for reason in ("unknown", "tool_unavailable", "non_customer_general"):
        assert reason in prompt


def test_a_promised_hand_off_is_bound_to_an_actual_create_case_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S30's defect: the prompt described the hand-off as something to SAY.

    Three separate places told the agent what to say when it could not answer, and
    each read as a complete instruction on its own -- "say you don't have that on
    hand", "say ... you'll connect them with the team / open a follow-up". The
    "always open a case" contract lived in a different section, keyed on categories
    ("a policy question", "a non-customer") that the failing turn did not obviously
    match. The 0.0.4 acceptance run produced exactly the reply the nearest
    instruction asked for: *"I don't have our Saturday hours on hand at the moment,
    but I've asked the team to reach out to you directly"* -- and no case.

    Each assertion below is one of those sites. Reverting any one of them to its
    speech-only wording is what turns this red.
    """
    prompt = _system_prompt_sent(monkeypatch)

    # The rule itself, stated once where the case vocabulary is defined.
    assert "Saying it is not doing it." in prompt

    # The empty-knowledge path -- the literal 0.0.4 conversation. A search that
    # comes back with nothing used to end at "say plainly you don't have that".
    assert "If the results are empty, do NOT guess and do NOT stop there: call" in prompt

    # The no-published-policy path -- used to instruct the agent to SAY it would
    # "connect them with the team / open a follow-up".
    assert "open a case (see below) on this turn FIRST" in prompt

    # The trigger, widened past "a policy question" to the operational questions the
    # failing turn actually asked (hours), which the old wording did not name -- and
    # carrying its own reason, so the classification does not drift off `unknown`.
    assert "opening hours, locations, or availability — open a case with" in prompt
    assert "reason `unknown`" in prompt


def test_the_counterweight_against_escalating_everything_survives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Over-escalation is S30's own named out-of-scope risk, so it is pinned too.

    Tightening the hand-off contract trades under-escalation for a case on every
    conversation if the "serve it here" rule is weakened at the same time -- which
    would empty the Auto-Handled Audit View exactly as the pre-0.0.4 bug did. S31's
    must-NOT-escalate probe measures that live; this is its deterministic half.
    """
    prompt = _system_prompt_sent(monkeypatch)

    assert "Do NOT open a case for a request you can fully serve here" in prompt
    # ...and the escape hatch that keeps the new rule from being read as "always
    # escalate": not mentioning a human is a legal way to satisfy it.
    assert "If you are not going to open a case" in prompt
