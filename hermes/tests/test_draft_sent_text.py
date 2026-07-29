"""0.0.5 S27 (FR-33, D11): ``draft_feedback.sent_text`` -- the second operand.

S27 span-diffs "the draft as generated" against "the text the rep actually
sent". Verified against the shipped quality-feedback code, the second operand
**did not exist**: ``draft_feedback`` stored only ``draft_text`` (the original)
plus a scalar ``edit_distance_ratio``, and ``outbound_send`` has no body column
and no draft-correlation id. D11 took the additive default -- migration 0029
adds a nullable ``sent_text``, written at governed-send time, with NO backfill.

Three properties are pinned here, on the mock twin, because they are the same
shared validators the Postgres handler imports (NFR-7, one resolver both twins):

* a ``sent_edited`` row CARRIES the sent text, or mining has nothing to diff;
* a ``sent_as_is`` row must not, because "nothing was edited" and "here is what
  the edit produced" contradict each other -- the same reject-don't-coerce rule
  ``edit_distance_ratio`` already follows;
* it is OPTIONAL, deliberately. A row written by a browser tab loaded before
  this shipped, or by any caller that has not been updated, must still record
  its outcome rather than 500 on a field the capture is fire-and-forget about.
  That absence is exactly D11's "no backfill": mining skips those rows and says
  so, instead of pretending to historical coverage it does not have.
"""

from __future__ import annotations

import pytest

from toee_hermes.drivers.mock.driver import MockDriver
from toee_hermes.drivers.mock.feedback import (
    _read_sent_text,
    create_feedback_mock_handlers,
)
from toee_hermes.errors import ToolDriverError
from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext

_DRAFT = "We have mud tires in stock for your truck."
_SENT = "We have all-terrain tires in stock for your truck."


def _record(**params):
    params.setdefault("case_id", "case_1")
    params.setdefault("draft_correlation_id", "draft_corr_1")
    params.setdefault("draft_kind", "sms")
    params.setdefault("draft_text", _DRAFT)
    return execute_tool(
        tool="toee_feedback",
        action="record_draft_outcome",
        params=params,
        context=ToolExecutionContext(profile="internal_copilot", user_id="acct_rep_1"),
        driver=MockDriver(create_feedback_mock_handlers()),
    )


def test_an_edited_send_persists_the_text_that_was_actually_sent() -> None:
    result = _record(outcome="sent_edited", edit_distance_ratio=0.2, sent_text=_SENT)

    assert result.ok is True, result.message
    assert result.data["draft_text"] == _DRAFT
    assert result.data["sent_text"] == _SENT


def test_an_edited_send_without_the_sent_text_still_records_its_outcome() -> None:
    """D11's "no backfill", as behaviour rather than as a sentence.

    The capture is fire-and-forget from a SUCCESSFUL customer send. Making this
    field required would turn a stale browser tab into a 500 on a path that must
    never report a false send failure -- so the row lands, and mining skips it.
    """
    result = _record(outcome="sent_edited", edit_distance_ratio=0.2)

    assert result.ok is True, result.message
    assert result.data["sent_text"] is None


def test_an_unedited_send_carrying_a_sent_text_is_refused() -> None:
    """A contradiction, rejected rather than silently dropped -- the same rule
    ``edit_distance_ratio`` follows on the very next line of the validator.

    The envelope sanitizes every ``unexpected_error`` to one generic sentence,
    so "it was refused" is all the tool surface can prove. The REASON is
    asserted directly against the shared validator below, which is the thing
    both twins import -- otherwise this test would pass for any refusal at all,
    including one caused by a typo in the fixture.
    """
    result = _record(outcome="sent_as_is", sent_text=_SENT)
    assert result.ok is False

    with pytest.raises(ToolDriverError) as excinfo:
        _read_sent_text({"sent_text": _SENT}, outcome="sent_as_is")
    assert "sent_as_is" in str(excinfo.value)


def test_an_unedited_send_records_a_null_sent_text() -> None:
    result = _record(outcome="sent_as_is")

    assert result.ok is True, result.message
    assert result.data["sent_text"] is None


def test_a_non_string_sent_text_is_refused() -> None:
    result = _record(outcome="sent_edited", edit_distance_ratio=0.2, sent_text=17)

    assert result.ok is False


def test_a_blank_sent_text_is_refused_rather_than_stored_as_an_empty_diff() -> None:
    """An empty sent body is not a real send, and it would diff as a total
    deletion of the draft -- noise the miner would have to filter downstream."""
    result = _record(outcome="sent_edited", edit_distance_ratio=1.0, sent_text="   ")

    assert result.ok is False
