"""S23 (FR-22, NFR-3): the post-copilot-turn learning-loop review pass.

After a copilot draft turn produces its result, a bounded SECOND agent pass
("the review fork") reflects on the just-completed turn and may call the
governed ``toee_agent_experience.propose_experience`` tool to record an
OPERATIONAL learning as ``status='proposed'`` (inert until S24 confirms, S25
injects). The three make-or-break properties this file pins:

1. EVAL DETERMINISM: the pass is gated behind its OWN L6 flag
   (``agent_experience_enabled``), DEFAULT OFF -- so the eval record/replay path
   (which never sets it and never scripts the fork) is byte-identical to before.
2. TURN RESILIENCE: any exception in the review pass is swallowed -- the rep's
   draft (already produced) is never affected.
3. OPERATIONAL-ONLY / NO PII: the review prompt forbids person-specific data
   (1st line); the S22 write-side scan is the backstop (2nd line). A fork that
   tries to propose PII yields NO proposal.

The fork's model output is scripted (``review_scripted_completions``) so every
test is deterministic, mirroring how the draft turn scripts its completions.
"""

from __future__ import annotations

import pytest

from hermes_runtime.copilot_turn import make_copilot_run_turn
from toee_hermes.plugin.profiles import INTERNAL


@pytest.fixture(autouse=True)
def _keyless_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # No real provider is ever reached: the draft + review both run scripted.
    # Clear the key + the L6 flag so a dev box's env can't leak into a test.
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_EXPERIENCE_LEARNING", raising=False)


_OPERATIONAL_PROPOSE = {
    "tool_calls": [
        {
            "name": "toee_agent_experience__propose_experience",
            "arguments": {
                "kind": "procedure",
                "content": "For EasyRoutes delivery gaps, check get_delivery_status "
                "with the bare order_number before escalating.",
                "proposer_context": {"case_id": "case_lp"},
            },
        }
    ]
}
_REVIEW_DONE = {"content": "Recorded one operational learning."}


def test_review_pass_emits_a_well_formed_operational_proposal_under_the_scripted_path() -> None:
    # Acceptance (a): the review fork calls the governed tool and its
    # framework-derived RESULT (status='proposed') is surfaced on the copilot
    # result as experience_proposals[] -- never the model's free text.
    run_turn = make_copilot_run_turn(
        scripted_completions=[{"content": "Here is a suggested reply."}],
        review_scripted_completions=[_OPERATIONAL_PROPOSE, _REVIEW_DONE],
    )

    result = run_turn(channel="sms", case_id="case_lp", prompt="delivery is late")

    # The draft the rep sees is untouched by the review pass.
    assert result["draft"].strip() == "Here is a suggested reply."
    assert result["profile"] == INTERNAL
    # The proposal is captured framework-derived, as proposed.
    assert result["experience_proposals"] == [
        {
            "kind": "procedure",
            "content": "For EasyRoutes delivery gaps, check get_delivery_status "
            "with the bare order_number before escalating.",
            "status": "proposed",
        }
    ]


def test_review_pass_that_calls_no_tool_proposes_nothing() -> None:
    # A reflection that decides there is no durable learning writes nothing.
    run_turn = make_copilot_run_turn(
        scripted_completions=[{"content": "A plain draft."}],
        review_scripted_completions=[{"content": "Nothing worth recording."}],
    )

    result = run_turn(channel="sms", case_id="case_x")

    assert result["experience_proposals"] == []


def test_review_pass_pii_bearing_proposal_yields_no_proposal() -> None:
    # NFR-3 backstop: even if the fork tries to propose person-specific content
    # (here an email address), the S22 write-side scan rejects the governed call
    # -> the call fails -> nothing is surfaced. The prompt is the 1st line; this
    # proves the 2nd line holds deterministically.
    run_turn = make_copilot_run_turn(
        scripted_completions=[{"content": "Draft."}],
        review_scripted_completions=[
            {
                "tool_calls": [
                    {
                        "name": "toee_agent_experience__propose_experience",
                        "arguments": {
                            "kind": "note",
                            "content": "Reach Jane at jane.doe@example.com after 2pm.",
                        },
                    }
                ]
            },
            {"content": "Tried to record a learning."},
        ],
    )

    result = run_turn(channel="sms", case_id="case_pii")

    assert result["experience_proposals"] == []


def test_review_prompt_explicitly_forbids_person_specific_data() -> None:
    # The 1st line of defense (NFR-3): the review prompt must ask for operational
    # learnings only and explicitly forbid person-specific data / customer PII.
    from hermes_runtime.copilot_turn import _REVIEW_SYSTEM_MESSAGE

    lowered = _REVIEW_SYSTEM_MESSAGE.lower()
    assert "operational" in lowered
    assert "never" in lowered
    # Forbids person-specific data explicitly (names / order numbers / contacts).
    assert "person-specific" in lowered or "personal" in lowered
    assert "propose_experience" in _REVIEW_SYSTEM_MESSAGE


def test_a_review_pass_failure_never_fails_the_copilot_turn(monkeypatch) -> None:
    # TURN RESILIENCE (RK): the rep's draft is already produced before the review
    # pass runs. A review pass that raises is caught, logged, and swallowed -- the
    # run_turn result is intact and carries no proposals.
    import hermes_runtime.copilot_turn as copilot_mod

    def _boom(**_kwargs):
        raise RuntimeError("review model blew up")

    monkeypatch.setattr(copilot_mod, "_run_review_pass", _boom)

    run_turn = make_copilot_run_turn(
        scripted_completions=[{"content": "The rep's draft."}],
        review_scripted_completions=[_OPERATIONAL_PROPOSE, _REVIEW_DONE],
    )

    result = run_turn(channel="sms", case_id="case_resilient")

    assert result["draft"].strip() == "The rep's draft."
    assert result["profile"] == INTERNAL
    # Swallowed: no proposals surfaced, and the turn did not raise.
    assert "experience_proposals" not in result


def test_review_pass_does_not_run_when_disabled_and_unscripted() -> None:
    # EVAL DETERMINISM: with the L6 flag OFF (default) and no scripted fork -- the
    # exact shape of the eval record/replay path -- the review pass never runs, so
    # the copilot result is byte-identical to the pre-S23 draft-only result.
    run_turn = make_copilot_run_turn(scripted_completions=[{"content": "Just a draft."}])

    result = run_turn(channel="sms", case_id="case_eval")

    assert result["draft"].strip() == "Just a draft."
    assert "experience_proposals" not in result


# --- Live Postgres: the proposal actually persists as a proposed row (FR-22) ----


def test_review_pass_persists_a_proposed_row_to_the_datastore(datastore, monkeypatch) -> None:
    # Acceptance (a), persistence leg: with the L6 flag ON, the review fork's
    # overlay routes toee_agent_experience to the datastore driver, so the
    # governed propose_experience call lands a status='proposed' row in Postgres.
    # select_tool_driver is patched to the fixture's schema-bound driver (the
    # test_copilot_memory_write_overlay.py convention) so the write lands in THIS
    # throwaway schema and the readback is real.
    driver, conn, _ = datastore
    monkeypatch.setenv("AGENT_EXPERIENCE_LEARNING", "on")
    import hermes_runtime.tool_backend as tool_backend_mod

    monkeypatch.setattr(tool_backend_mod, "select_tool_driver", lambda *_a, **_k: driver)

    run_turn = make_copilot_run_turn(
        scripted_completions=[{"content": "A grounded draft for the rep."}],
        review_scripted_completions=[_OPERATIONAL_PROPOSE, _REVIEW_DONE],
    )

    result = run_turn(channel="sms", case_id="case_persist")

    # Surfaced framework-derived...
    assert result["experience_proposals"] and result["experience_proposals"][0]["status"] == "proposed"
    # ...and actually persisted as a proposed row with the framework-derived source.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT kind, status, content, source, decider_account_id, decided_at "
            "FROM agent_experience"
        )
        rows = cur.fetchall()
    assert len(rows) == 1
    kind, status, content, source, decider, decided_at = rows[0]
    assert kind == "procedure"
    assert status == "proposed"
    assert "get_delivery_status" in content
    assert source == "copilot_agent"  # never forged by the model
    assert decider is None and decided_at is None  # inert until S24
