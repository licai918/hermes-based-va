"""Live-turn bridge: a real Nous ``AIAgent`` turn closes the record/replay loop.

A live turn is driven by a deterministic provider seam (scripted ChatCompletions),
captured as ``{final_response, messages}`` exactly as ``run_agent`` returns, handed
to :func:`eval_runner.recorder.record_turn`, and replayed through
:class:`eval_runner.replay.ReplayAgentHarness` (ADR-0121, ADR-0139).

The LLM provider is the only fake — the unavoidable nondeterministic boundary. The
agent loop, turn capture, recorder, and replay parser are all real, so this proves
a recorded real-agent turn reproduces deterministically with no model or network.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from eval_runner.fixtures import load_scenario
from eval_runner.recorder import record_turn
from eval_runner.replay import ReplayAgentHarness
from tools.registry import registry

from hermes_runtime.boot import boot_profile
from hermes_runtime.live import run_live_turn

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"

EXTERNAL_PROFILE = "customer_service_external"


def test_live_turn_round_trips_through_record_and_replay() -> None:
    reply = "Thanks for reaching out to Toee Tire - how can I help with your order?"

    turn = run_live_turn(
        user_message="Hello?",
        system_message="You are Toee Tire support. Reply in one short sentence.",
        scripted_completions=[{"content": reply}],
    )

    # A real AIAgent loop ran and surfaced the model's final reply + message log.
    assert turn["final_response"].strip() == reply
    assert isinstance(turn["messages"], list) and turn["messages"]

    # The captured turn records and replays deterministically. With no SMS
    # send, the customer-facing text falls back to the agent's final_response.
    scenario = load_scenario("text_first_launch", "01", EVAL_DIR)
    with tempfile.TemporaryDirectory(prefix="live-turn-") as tmp:
        root = Path(tmp)
        record_turn(turn=turn, scenario=scenario, transcripts_dir=root)
        result = ReplayAgentHarness(root).run_turn(scenario)

    assert result.outbound_text.strip() == reply


def test_live_turn_dispatches_governed_sms_tool_through_real_loop() -> None:
    """A scripted tool-call turn executes a governed toee_* tool in the real loop.

    Booting the External profile registers its allowlisted tools into the global
    Hermes registry; the live AIAgent then dispatches the scripted
    ``toee_sms_reply__send_message`` call through governed execution (ADR-0139,
    ADR-0066). The captured assistant tool_calls + tool result round-trip through
    record/replay into the recorded tool call and customer-facing text.
    """
    body = "Your order TOEE-1001 shipped today - tracking to follow."

    turn = run_live_turn(
        profile=EXTERNAL_PROFILE,
        user_message="Where is my order?",
        system_message="You are Toee Tire support.",
        scripted_completions=[
            {
                "tool_calls": [
                    {
                        "name": "toee_sms_reply__send_message",
                        "arguments": {"conversation_id": "conv1", "body": body},
                    }
                ]
            },
            {"content": "Done - I've texted you the shipping update."},
        ],
    )

    scenario = load_scenario("text_first_launch", "01", EVAL_DIR)
    with tempfile.TemporaryDirectory(prefix="live-tool-") as tmp:
        root = Path(tmp)
        record_turn(turn=turn, scenario=scenario, transcripts_dir=root)
        result = ReplayAgentHarness(root).run_turn(scenario)

    assert [(c.tool, c.action) for c in result.tool_calls] == [
        ("toee_sms_reply", "send_message")
    ]
    assert result.tool_calls[0].ok
    assert result.outbound_text == body


class _SentinelDriver:
    """A distinguishable driver: any dispatch through it proves it, not mock, ran."""

    kind = "sentinel"

    def execute(self, request, context):  # noqa: ANN001 - matches ToolDriver protocol
        return {"sentinel": True}


def test_run_live_turn_preserves_a_prior_overlay_boot() -> None:
    """Regression: a live-shaped turn must not clobber an already-booted overlay.

    ``boot_profile`` always re-registers every allowlisted tool into the shared
    upstream ``tools.registry`` singleton (ADR-0139) -- registering is not
    additive/merge-aware, it's last-boot-wins. Mirroring the production shape
    (``openrouter.py``'s ``_turn_extra_drivers()`` overlay boot), this boots once
    with a sentinel driver for ``toee_knowledge_search``, then drives
    ``run_live_turn`` -- the code path that used to boot bare, with no
    ``extra_drivers`` of its own, silently falling every tool (including the
    already-overlaid one) back to mock. Dispatching the tool afterwards must
    still reach the sentinel, not mock.
    """
    sentinel = _SentinelDriver()
    boot_profile(EXTERNAL_PROFILE, extra_drivers={"toee_knowledge_search": sentinel})

    run_live_turn(
        profile=EXTERNAL_PROFILE,
        user_message="Where is my order?",
        system_message="You are Toee Tire support.",
        scripted_completions=[{"content": "ok, no tools needed"}],
        extra_drivers={"toee_knowledge_search": sentinel},
    )

    result = registry.dispatch(
        "toee_knowledge_search__search_public_site", {"query": "warranty policy"}
    )
    assert json.loads(result) == {"sentinel": True}
