"""Copilot draft agent-turn seam (ADR-0147 Slice 1, resolves #41 drafts).

The draft is a *genuine agent turn* (ADR-0141): an **unbound** ``internal_copilot``
``AIAgent`` run whose ``final_response`` becomes the draft text (Fork E1). The
provider is the existing :mod:`hermes_runtime.live` ``openai_factory`` seam, scripted
here so the loop runs with no model, network, or key (Fork C1, mock-first ADR-0137).

The security crux of the whole design is **structural, not a runtime guard**: the
``internal_copilot`` Profile Tool Allowlist (ADR-0035, default-deny ADR-0034)
**excludes** the send tools, so a draft agent booted here can never send to a
customer (ADR-0067). :func:`test_internal_copilot_agent_turn_excludes_send_tools`
proves it.
"""

from __future__ import annotations

from hermes_runtime.boot import boot_profile
from hermes_runtime.copilot_turn import (
    SCRIPTED_MODEL,
    _system_message,
    make_copilot_run_turn,
)
from toee_hermes.plugin.profiles import INTERNAL, allowlisted_tools

# The two customer-facing write tools a draft agent must never hold (ADR-0067):
# the Textline reply send and the Square payment link. Both are outside the
# internal_copilot allowlist (ADR-0035) and so are never registered for the turn.
SEND_TOOLSETS = ("toee_textline_reply", "toee_square_payment_link")

# The internal_copilot allowlist this no-auto-send design was reviewed against
# (ADR-0147 / ADR-0035). Frozen here as a tripwire snapshot: any toolset added to
# (or removed from) the profile breaks the equality below, forcing a deliberate
# re-review of the no-send guarantee instead of silently widening what a draft
# agent can do. Keep in sync with PROFILE_TOOL_ALLOWLIST[INTERNAL] only via review.
REVIEWED_INTERNAL_ALLOWLIST = frozenset(
    {
        "toee_knowledge_search",
        "toee_shopify_read",
        "toee_qbo_read",
        "toee_easyroutes_read",
        "toee_identity_lookup",
        "toee_case_manage",
        "toee_copilot_draft",
        "toee_workbench_read",
        "toee_customer_memory",
    }
)


def _booted_toolsets(profile: str) -> set[str]:
    # boot_profile().tool_names are ``toolset__action`` names; the toolset is the
    # allowlist unit (ADR-0035), so collapse to the toolset to assert against it.
    return {name.split("__")[0] for name in boot_profile(profile).tool_names}


def test_internal_copilot_agent_turn_excludes_send_tools() -> None:
    # THE governance invariant (ADR-0067/0035/0147): no-auto-send is structural.
    # A draft agent booted unbound under internal_copilot has no send tool in its
    # registered set, so it cannot send — enforced by non-registration, not a guard.
    # The channel never reaches boot_profile, so this booted set is channel-
    # independent: it is the no-send invariant for sms/email/internal_note alike.
    toolsets = _booted_toolsets(INTERNAL)

    # (1) Denylist (kept from the tracer): the two named customer-send /
    # external-payment toolsets are never booted for a draft turn.
    for send in SEND_TOOLSETS:
        assert send not in toolsets, f"{send} must not be booted for a draft turn"

    # (2) Allowlist-equality: the booted set is EXACTLY internal_copilot's declared
    # allowlist — boot registers nothing beyond what the profile declares, so the
    # structural no-send rests entirely on that declaration (no transitive drift).
    assert toolsets == set(allowlisted_tools(INTERNAL))

    # (3) Allowlist tripwire: the declared allowlist still equals the reviewed
    # snapshot. (2) on its own can't catch a send tool *added to the allowlist* —
    # the booted set would grow to match and stay equal — so pinning the
    # declaration to a frozen reviewed set is what makes adding (or removing) ANY
    # toolset break this test and force re-review of the no-send guarantee.
    assert set(allowlisted_tools(INTERNAL)) == REVIEWED_INTERNAL_ALLOWLIST

    # ...and it DOES carry the copilot read tools it needs to gather case context
    # itself (ADR-0147 decision 2), so the draft is grounded, not blind.
    assert "toee_workbench_read" in toolsets
    assert "toee_knowledge_search" in toolsets


def test_scripted_turn_returns_final_response_as_draft() -> None:
    # Fork E1: the agent's final assistant message IS the draft. A scripted text
    # completion drives the real AIAgent loop (booted internal_copilot, unbound) and
    # its final_response comes back as data["draft"] with internal_copilot provenance.
    draft = "Hi! Your order TOEE-1001 ships today; tracking to follow. - Toee Tire"
    run_turn = make_copilot_run_turn(scripted_completions=[{"content": draft}])

    result = run_turn(channel="sms", case_id="case_ar_urgent", prompt="reassure them")

    assert result["draft"].strip() == draft
    assert result["profile"] == INTERNAL
    assert result["model"] == SCRIPTED_MODEL


def test_default_provider_is_a_deterministic_keyless_stub() -> None:
    # Fork C1 mock-first (ADR-0137): with no injected completions and no API key,
    # the turn still yields a deterministic, non-empty draft (a local stub), so the
    # endpoint boots and serves keyless in local dev / CI — exactly as the dispatch
    # server runs against MockDriver without Postgres.
    run_turn = make_copilot_run_turn()

    result = run_turn(channel="sms", case_id="case_x")

    assert isinstance(result["draft"], str) and result["draft"].strip()
    assert result["profile"] == INTERNAL


def test_per_channel_system_messages_are_distinct() -> None:
    # ADR-0147 Slice 2: the single SMS-only system message is replaced by one per
    # channel (sms short reply / email subject+body / internal note staff-facing),
    # so each surface is framed differently. All three are non-empty and distinct.
    messages = [_system_message(c) for c in ("sms", "email", "internal_note")]
    assert all(isinstance(m, str) and m.strip() for m in messages)
    assert len(set(messages)) == 3


def test_email_turn_returns_a_subject() -> None:
    # Email parity needs a subject — the in-process mock returns {channel, subject,
    # draft}. The scripted/keyless turn supplies a deterministic one (Slice 3 wires
    # the real model's subject); the body is still the agent's final_response.
    run_turn = make_copilot_run_turn(scripted_completions=[{"content": "Body text."}])

    result = run_turn(channel="email", case_id="case_email")

    assert result["draft"].strip() == "Body text."
    assert isinstance(result["subject"], str) and result["subject"].strip()
    assert result["profile"] == INTERNAL


def test_internal_note_turn_yields_draft_and_no_subject() -> None:
    # The note envelope keys on `kind`, not a subject; the turn just yields the note
    # text and the endpoint shapes {kind, draft}. No subject is produced.
    run_turn = make_copilot_run_turn(scripted_completions=[{"content": "Internal note."}])

    result = run_turn(channel="internal_note", case_id="case_note")

    assert result["draft"].strip() == "Internal note."
    assert "subject" not in result
    assert result["profile"] == INTERNAL
