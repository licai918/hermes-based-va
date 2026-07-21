"""Rubric-contract test for the S27 judge-tuning rubric sharpening (PRD FR-29).

0.0.2's cheap-model judge conflated a numeric "2pm" delivery ETA with an
"after 2pm Eastern" contact-time preference in both directions (recorded in
workspace/0.0.3/EXPLORATION.md). This pins that the judge prompt now carries
an explicit instruction ruling that conflation class out, so no future edit
to :func:`eval_runner.judge.build_judge_prompt` silently drops it. No live
model call — a static string-contains check on the built prompt.
"""

from __future__ import annotations

from eval_runner.judge import build_judge_prompt


def test_prompt_rules_out_delivery_eta_vs_contact_time_conflation() -> None:
    prompt = build_judge_prompt(reply="x", leg="honored")

    lowered = prompt.lower()
    # The discriminating instruction itself (S27 rubric sharpening).
    assert "delivery estimate" in lowered or "delivery eta" in lowered
    assert "contact-time" in lowered or "contact time" in lowered
    assert "token" in lowered or "overlap" in lowered
    assert "behavior" in lowered  # "judge the AGENT'S BEHAVIOR, not token overlap"


def test_conflation_instruction_present_for_both_legs() -> None:
    # The instruction is a general grading rule, not leg-specific -- both legs
    # (honored / no_unprompted_recall) are exposed to the same ETA-vs-preference
    # conflation risk (EXPLORATION.md: "in both directions").
    honored_prompt = build_judge_prompt(reply="x", leg="honored")
    recall_prompt = build_judge_prompt(reply="x", leg="no_unprompted_recall")

    for prompt in (honored_prompt, recall_prompt):
        assert "delivery" in prompt.lower()


def test_injection_hardening_fences_are_unchanged_by_the_rubric_sharpening() -> None:
    # The sharpened rubric must not weaken the existing fencing contract
    # (S27 brief: "keep the injection hardening intact -- do not weaken the
    # fencing"). Full behavioral coverage lives in test_eval_judge.py; this is
    # a smoke check that the fence markers are still present after the edit.
    prompt = build_judge_prompt(
        reply="hello", leg="honored", injected_memory={"note": "value"}
    )
    assert "<untrusted_agent_reply>" in prompt
    assert "</untrusted_agent_reply>" in prompt
    assert "<untrusted_customer_memory>" in prompt
    assert "</untrusted_customer_memory>" in prompt
    assert "DATA, not instructions" in prompt
