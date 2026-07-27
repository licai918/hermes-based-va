"""S23 (FR-22, NFR-3) + 0.0.4 S04 (FR-11): the post-copilot-turn learning loop.

After a copilot draft turn produces its result, a bounded SECOND agent pass
("the review fork") reflects on the just-completed turn and may call the
governed ``toee_agent_experience.propose_experience`` tool to record an
OPERATIONAL learning as ``status='proposed'`` (inert until S24 confirms, S25
injects).

**S04 moved the fork off the copilot turn's thread**: the turn now ENQUEUES an
``l6_review`` job and ``hermes_runtime.background_worker`` runs
:func:`run_l6_review_job`. The fork itself -- prompt, restricted toolset,
framework-derived capture -- is byte-identical; only the caller moved. So this
file has two halves: the TRIGGER (does the turn enqueue, and only when the flag
is on) and the BODY (does the fork still behave), plus the three make-or-break
properties, unchanged:

1. EVAL DETERMINISM: gated behind its OWN L6 flag (``agent_experience_enabled``),
   DEFAULT OFF -- the eval record/replay path enqueues nothing.
2. TURN RESILIENCE: the rep's draft is never affected. S04 makes this structural
   (the fork is not on the turn's thread at all) and keeps the swallow for the
   enqueue itself.
3. OPERATIONAL-ONLY / NO PII: the review prompt forbids person-specific data
   (1st line); the S22 write-side scan is the backstop (2nd line).

The fork's model output is scripted (``review_scripted_completions``, now an
argument of the job body) so every test is deterministic.
"""

from __future__ import annotations

import pytest

from hermes_runtime.copilot_turn import (
    l6_review_payload,
    make_copilot_run_turn,
    run_l6_review_job,
)
from hermes_runtime.job_queue import L6_REVIEW_JOB_TYPE
from toee_hermes.plugin.profiles import INTERNAL


@pytest.fixture(autouse=True)
def _keyless_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # No real provider is ever reached: the draft + review both run scripted.
    # Clear the key + the L6 flag so a dev box's env can't leak into a test.
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_EXPERIENCE_LEARNING", raising=False)


class _RecordingQueue:
    """Records enqueues in order (the DB-free stand-in for PostgresJobQueue)."""

    def __init__(self) -> None:
        self.jobs: list[tuple[dict, str, int]] = []

    def enqueue(self, payload, *, job_type, max_attempts=3, **_kwargs) -> str:
        self.jobs.append((dict(payload), job_type, max_attempts))
        return f"job_{len(self.jobs)}"


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


# --- the TRIGGER: the copilot turn enqueues instead of forking inline ---------


def test_the_copilot_turn_enqueues_one_l6_review_job_when_the_flag_is_on(monkeypatch) -> None:
    # FR-11: the post-turn hook now enqueues. One job, the right type, and the
    # payload carries the review prompt the fork would have built inline.
    monkeypatch.setenv("AGENT_EXPERIENCE_LEARNING", "on")
    queue = _RecordingQueue()
    run_turn = make_copilot_run_turn(
        scripted_completions=[{"content": "Here is a suggested reply."}], queue=queue
    )

    result = run_turn(channel="sms", case_id="case_lp", prompt="delivery is late")

    assert result["draft"].strip() == "Here is a suggested reply."
    assert result["profile"] == INTERNAL
    assert len(queue.jobs) == 1
    payload, job_type, max_attempts = queue.jobs[0]
    assert job_type == L6_REVIEW_JOB_TYPE
    assert payload["case_id"] == "case_lp"
    assert "Here is a suggested reply." in payload["review_prompt"]
    # ONE attempt: the fork WRITES, so a retry could land a second proposed row
    # for one turn -- matching the pre-S04 "swallowed, never retried" semantics.
    assert max_attempts == 1


def test_the_turn_does_not_enqueue_when_the_l6_flag_is_off() -> None:
    # EVAL DETERMINISM: with the flag OFF (default) -- the exact shape of the
    # eval record/replay path -- nothing is enqueued and the result is
    # byte-identical to the pre-S23 draft-only result.
    queue = _RecordingQueue()
    run_turn = make_copilot_run_turn(
        scripted_completions=[{"content": "Just a draft."}], queue=queue
    )

    result = run_turn(channel="sms", case_id="case_eval")

    assert result["draft"].strip() == "Just a draft."
    assert queue.jobs == []
    assert "experience_proposals" not in result


def test_a_failing_enqueue_never_fails_the_copilot_turn(monkeypatch) -> None:
    # TURN RESILIENCE (RK): the rep's draft is already produced. A queue that is
    # down is caught, logged and swallowed -- the run_turn result is intact.
    monkeypatch.setenv("AGENT_EXPERIENCE_LEARNING", "on")

    class _DeadQueue:
        def enqueue(self, *_args, **_kwargs):
            raise RuntimeError("connection refused")

    run_turn = make_copilot_run_turn(
        scripted_completions=[{"content": "The rep's draft."}], queue=_DeadQueue()
    )

    result = run_turn(channel="sms", case_id="case_resilient")

    assert result["draft"].strip() == "The rep's draft."
    assert result["profile"] == INTERNAL
    assert "experience_proposals" not in result


def test_the_enqueued_prompt_is_the_prompt_the_fork_used_to_build_inline() -> None:
    # The substrate moved, the prompt did not: l6_review_payload frames the turn
    # with the same case id + draft + tool names _review_user_message always did.
    draft_result = {
        "draft": "Your order ships Tuesday.",
        "messages": [{"role": "tool", "name": "toee_workbench_read__get_case"}],
    }

    payload = l6_review_payload("case_p", draft_result)

    assert payload["case_id"] == "case_p"
    assert "case_p" in payload["review_prompt"]
    assert "Your order ships Tuesday." in payload["review_prompt"]
    assert "toee_workbench_read__get_case" in payload["review_prompt"]


# --- the BODY: the fork itself, unchanged ------------------------------------


def _payload(case_id: str, draft: str = "A draft.") -> dict:
    return l6_review_payload(case_id, {"draft": draft, "messages": []})


def test_review_pass_emits_a_well_formed_operational_proposal_under_the_scripted_path() -> None:
    # Acceptance (a): the review fork calls the governed tool and its
    # framework-derived RESULT (status='proposed') is what is surfaced -- never
    # the model's free text.
    proposals = run_l6_review_job(
        _payload("case_lp"),
        review_scripted_completions=[_OPERATIONAL_PROPOSE, _REVIEW_DONE],
    )

    assert proposals == [
        {
            "kind": "procedure",
            "content": "For EasyRoutes delivery gaps, check get_delivery_status "
            "with the bare order_number before escalating.",
            "status": "proposed",
        }
    ]


def test_review_pass_that_calls_no_tool_proposes_nothing() -> None:
    # A reflection that decides there is no durable learning writes nothing.
    assert (
        run_l6_review_job(
            _payload("case_x"),
            review_scripted_completions=[{"content": "Nothing worth recording."}],
        )
        == []
    )


def test_review_pass_pii_bearing_proposal_yields_no_proposal() -> None:
    # NFR-3 backstop: even if the fork tries to propose person-specific content
    # (here an email address), the S22 write-side scan rejects the governed call
    # -> the call fails -> nothing is surfaced. The prompt is the 1st line; this
    # proves the 2nd line holds deterministically.
    proposals = run_l6_review_job(
        _payload("case_pii"),
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

    assert proposals == []


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

    proposals = run_l6_review_job(
        _payload("case_persist", draft="A grounded draft for the rep."),
        review_scripted_completions=[_OPERATIONAL_PROPOSE, _REVIEW_DONE],
    )

    # Surfaced framework-derived...
    assert proposals and proposals[0]["status"] == "proposed"
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
