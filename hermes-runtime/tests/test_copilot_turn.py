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

import json

import pytest

from hermes_runtime.boot import boot_profile
from hermes_runtime.copilot_turn import (
    SCRIPTED_MODEL,
    _system_message,
    _user_message,
    make_copilot_run_turn,
)
from hermes_runtime.live import _scripted_openai_factory, run_scripted_agent
from hermes_runtime.openrouter import OPENROUTER_PRIMARY_MODEL, OpenRouterConfig
from toee_hermes.plugin import _AGENT_EXCLUDED_ACTIONS
from toee_hermes.plugin.profiles import INTERNAL, allowlisted_tools
from toee_hermes.tool_catalog import TOOL_CATALOG


@pytest.fixture(autouse=True)
def _keyless_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Fork C1 is keyed off OPENROUTER_API_KEY; clear it so the default-provider
    # tests exercise the deterministic keyless stub even on a dev box that exports
    # a real key — the real OpenRouter path is only ever reached via injected
    # config/factory below, so CI never makes a network call.
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


class _RetryableBoom(Exception):
    """A test-only retryable error standing in for an OpenRouter primary outage."""

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
        # 0.0.3 S22 (FR-23): reviewed addition. toee_agent_experience's
        # propose_experience writes a status="proposed" L6 row (inert until an
        # admin confirms it, S24) -- it never contacts the customer or moves
        # money, so it does not weaken the no-auto-send invariant this
        # tripwire guards. list_agent_experience is admin-only and excluded
        # from LLM registration entirely (_AGENT_EXCLUDED_ACTIONS).
        "toee_agent_experience",
        # 0.0.3 S26 (FR-28): reviewed addition. toee_metrics.get_aggregate_metrics
        # is a read-only aggregate-counts/rates report (never a customer value,
        # never money) and is WHOLLY excluded from LLM registration
        # (_AGENT_EXCLUDED_ACTIONS) -- it is the toolset's ONLY catalog action, so
        # it never registers a handler and never appears in a booted tool_names()
        # set (see _wholly_excluded_toolsets below). Declared here purely so the
        # allowlist gate lets the admin BFF's deterministic tools:dispatch call
        # reach it (ADR-0140 precedent: toee_customer_memory.get_memory_audit).
        "toee_metrics",
        # 0.0.3 S28 (FR-30): reviewed addition. toee_retention's two actions
        # (trigger_retention_sweep, get_retention_status) delete/read
        # customer_memory_slot rows -- never contacts the customer and never
        # moves money, so it does not weaken the no-auto-send invariant this
        # tripwire guards. BOTH actions are its ONLY catalog actions and BOTH
        # are WHOLLY excluded from LLM registration (_AGENT_EXCLUDED_ACTIONS),
        # so it never registers a handler and never appears in a booted
        # tool_names() set (see _wholly_excluded_toolsets below). Declared here
        # purely so the allowlist gate lets the admin BFF's deterministic
        # tools:dispatch call (and the schedulable CLI entrypoint) reach it.
        "toee_retention",
    }
)


def _wholly_excluded_toolsets() -> set[str]:
    """Toolsets whose EVERY catalog action is in ``_AGENT_EXCLUDED_ACTIONS``.

    Such a toolset never registers a single handler in ``_register()`` (every
    action is skipped), so it never appears in a booted ``tool_names()`` set
    regardless of profile-allowlist membership -- 0.0.3 S26's ``toee_metrics``
    is the first (a single admin-only aggregate-metrics read). Assertion (2)
    below subtracts this set so a wholly-admin-only toolset doesn't break the
    booted-set-equals-allowlist equality it isn't structurally able to satisfy.
    """
    return {
        tool
        for tool, actions in TOOL_CATALOG.items()
        if all((tool, action) in _AGENT_EXCLUDED_ACTIONS for action in actions)
    }


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
    # allowlist minus any WHOLLY-excluded toolset (see _wholly_excluded_toolsets)
    # — boot registers nothing beyond what the profile declares, so the
    # structural no-send rests entirely on that declaration (no transitive drift).
    assert toolsets == set(allowlisted_tools(INTERNAL)) - _wholly_excluded_toolsets()

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


def test_run_turn_result_carries_the_governed_messages_transcript() -> None:
    # S07 (FR-3/R4): the copilot return must thread the governed tool-call
    # transcript through so an eval scenario's mechanical no-inferred-write
    # assertion (forbid_inferred_upsert) can inspect it -- this was computed but
    # silently dropped before (S05 spike finding 5). Additive: agent_turn_app.py,
    # the only production consumer, never reads result["messages"].
    draft = "Hi there, thanks for reaching out."
    run_turn = make_copilot_run_turn(scripted_completions=[{"content": draft}])

    result = run_turn(channel="sms", case_id="case_msgs", prompt="need help")

    assert isinstance(result.get("messages"), list) and result["messages"]
    assert result["messages"][0]["role"] == "user"
    assistant_messages = [m for m in result["messages"] if m.get("role") == "assistant"]
    assert assistant_messages[-1]["content"].strip() == draft


# --- S14 (FR-15): structured proposals[] extracted from the propose-only write ---


class _VerifiedIdentityStore:
    """A store with a fixed verified identity and no memory rows.

    Keeps the proposal-extraction test hermetic (no Postgres) while still giving
    the scripted upsert_preference call a resolvable binding to succeed against --
    mirrors test_copilot_memory_write_overlay.py's ``_NullStore`` pattern, one step
    further (a real identity instead of ``None``).
    """

    def load_case_identity(self, case_id: str) -> dict:
        return {
            "outcome": "verified_customer",
            "shopify_customer_id": "gid://shopify/Customer/1",
        }

    def load_customer_memory(self, binding_key: str) -> list:
        return []


def test_run_turn_result_extracts_memory_proposals_from_the_transcript() -> None:
    # S14 (FR-15): the draft turn's toee_customer_memory.upsert_preference call is
    # inert (S13/ADR-0150) -- the write never reaches a datastore -- but its
    # framework-validated result still becomes a structured proposal on
    # result["proposals"]. Pure extraction: no new write path, no model free-text.
    run_turn = make_copilot_run_turn(
        scripted_completions=[
            {
                "tool_calls": [
                    {
                        "name": "toee_customer_memory__upsert_preference",
                        "arguments": {"key": "contact_time_preference", "value": "after 2pm"},
                    }
                ]
            },
            {"content": "Noted, we'll reach out after 2pm."},
        ],
        store=_VerifiedIdentityStore(),
    )

    result = run_turn(channel="sms", case_id="case_pref", prompt="only call after 2pm please")

    assert result["proposals"] == [
        {"slot": "contact_time_preference", "value": "after 2pm", "evidence_turn": None}
    ]


def test_run_turn_result_has_no_proposals_when_no_memory_tool_calls() -> None:
    run_turn = make_copilot_run_turn(scripted_completions=[{"content": "Just a plain draft."}])

    result = run_turn(channel="sms", case_id="case_x")

    assert result["proposals"] == []


def test_default_provider_is_a_deterministic_keyless_stub() -> None:
    # Fork C1 mock-first (ADR-0137): with no injected completions and no API key,
    # the turn still yields a deterministic, non-empty draft (a local stub), so the
    # endpoint boots and serves keyless in local dev / CI — exactly as the dispatch
    # server runs against MockDriver without Postgres.
    run_turn = make_copilot_run_turn()

    result = run_turn(channel="sms", case_id="case_x")

    assert isinstance(result["draft"], str) and result["draft"].strip()
    assert result["profile"] == INTERNAL
    # Keyless: provenance reports the scripted/stub model, never a real slug.
    assert result["model"] == SCRIPTED_MODEL


def test_per_channel_system_messages_are_distinct() -> None:
    # ADR-0147 Slice 2: the single SMS-only system message is replaced by one per
    # channel (sms short reply / email subject+body / internal note staff-facing),
    # so each surface is framed differently. All three are non-empty and distinct.
    messages = [_system_message(c) for c in ("sms", "email", "internal_note")]
    assert all(isinstance(m, str) and m.strip() for m in messages)
    assert len(set(messages)) == 3


def test_email_turn_without_a_subject_line_falls_back_deterministically() -> None:
    # Email parity needs a subject — the in-process mock returns {channel, subject,
    # draft}. When the turn's final_response carries no `Subject:` line (the keyless
    # stub, or a model that skipped the convention), the derivation falls back to a
    # deterministic case-scoped subject and keeps the whole body as the draft.
    run_turn = make_copilot_run_turn(scripted_completions=[{"content": "Body text."}])

    result = run_turn(channel="email", case_id="case_email")

    assert result["draft"].strip() == "Body text."
    assert result["subject"] == "Re: your Toee Tire case case_email"
    assert result["profile"] == INTERNAL


def test_email_turn_with_an_empty_subject_line_strips_it_and_uses_the_fallback() -> None:
    # M2 (Slice 3 review): when the final_response leads with a BARE `Subject:` line
    # (empty subject — a model that left it blank), the derivation must STILL strip
    # that line from the body and fall back to the deterministic case-scoped subject.
    # Previously the bare `Subject:` line leaked into the draft body the staff edits.
    run_turn = make_copilot_run_turn(
        scripted_completions=[
            {"content": "Subject:\n\nHi there,\n\nWe're on it.\n\n- Toee Tire"}
        ]
    )

    result = run_turn(channel="email", case_id="case_empty_subj")

    assert result["subject"] == "Re: your Toee Tire case case_empty_subj"
    assert result["draft"] == "Hi there,\n\nWe're on it.\n\n- Toee Tire"
    assert "Subject:" not in result["draft"]  # the bare subject line is gone
    assert result["profile"] == INTERNAL


def test_email_subject_is_derived_from_a_leading_subject_line() -> None:
    # Slice 3: the real subject derivation. When the turn's final_response leads with
    # a `Subject:` line, that line becomes the subject and the remaining text is the
    # body (the draft the staff member edits) — so the body has no stray subject
    # line. Deterministic under the scripted path; the same seam serves the real model.
    run_turn = make_copilot_run_turn(
        scripted_completions=[
            {"content": "Subject: Your order TOEE-1001 shipped\n\nHi there,\n\nIt's on the way.\n\n- Toee Tire"}
        ]
    )

    result = run_turn(channel="email", case_id="case_email")

    assert result["subject"] == "Your order TOEE-1001 shipped"
    assert result["draft"] == "Hi there,\n\nIt's on the way.\n\n- Toee Tire"
    assert result["profile"] == INTERNAL


# --- Slice 3: governed context reads + the no-send invariant under a real loop ---


def test_governed_workbench_read_executes_through_the_real_multistep_loop() -> None:
    # THE core Slice 3 value (ADR-0147 decision 2): a copilot draft turn pulls case
    # context itself via a governed read in a real multi-step AIAgent loop. Booting
    # internal_copilot UNBOUND (exactly what make_copilot_run_turn composes) admits
    # toee_workbench_read; a scripted get_case tool_call dispatches through the FULL
    # governed path (catalog -> Tool Gate -> driver -> audit sink), its result feeds
    # back, and a SECOND scripted completion returns the draft grounded in it (E1).
    booted = boot_profile(INTERNAL)
    assert "toee_workbench_read__get_case" in booted.tool_names  # the read is admitted

    draft = "Hi! Your case c1 is open and we're on it - an update is on the way."
    turn = run_scripted_agent(
        user_message=_user_message("sms", "c1", None),
        system_message=_system_message("sms"),
        scripted_completions=[
            {"tool_calls": [{"name": "toee_workbench_read__get_case", "arguments": {"case_id": "c1"}}]},
            {"content": draft},
        ],
        governed_tool_names=booted.tool_names,
    )

    # The governed read actually executed: its tool-result message carries the real
    # driver output, proving catalog -> gate -> driver ran inside the loop. (The
    # datastore driver writes the audit ROW it commits — test_datastore_driver_cases;
    # the keyless mock audit sink is a no-op, so here we prove execution + gating,
    # not a persisted row.)
    tool_results = [
        m
        for m in turn["messages"]
        if isinstance(m, dict) and m.get("role") == "tool"
    ]
    read = next(m for m in tool_results if m.get("name") == "toee_workbench_read__get_case")
    assert json.loads(read["content"]) == {"case_id": "c1", "status": "open"}

    # ...and the draft is the post-read completion: the result fed back and the loop
    # continued to a grounded final_response (a genuine multi-step turn, not a stub).
    assert turn["final_response"].strip() == draft


def test_a_send_tool_call_is_rejected_under_the_real_multistep_loop() -> None:
    # Security crux (ADR-0067/0035): the no-send invariant must hold against a REAL
    # multi-step loop, not just at boot. A scripted tool_call for the customer-send
    # tool is rejected — it is not in the booted internal_copilot tool set, so it is
    # never admitted (valid_tool_names) and never dispatched — and the turn falls
    # through to proposed text. No send is ever executed.
    booted = boot_profile(INTERNAL)
    assert "toee_textline_reply__send_message" not in booted.tool_names

    draft = "Here is a suggested reply for you to review and send."
    turn = run_scripted_agent(
        user_message=_user_message("sms", "c1", None),
        system_message=_system_message("sms"),
        scripted_completions=[
            {
                "tool_calls": [
                    {
                        "name": "toee_textline_reply__send_message",
                        "arguments": {"conversation_id": "conv1", "body": "sneaky auto-send"},
                    }
                ]
            },
            {"content": draft},
        ],
        governed_tool_names=booted.tool_names,
    )

    # The send tool_call did NOT dispatch: its tool-result reports the tool does not
    # exist for this session (rejected before any driver), and the available-tools
    # list the rejection enumerates never includes the send toolset.
    send_results = [
        m
        for m in turn["messages"]
        if isinstance(m, dict)
        and m.get("role") == "tool"
        and m.get("name") == "toee_textline_reply__send_message"
    ]
    assert send_results, "the send tool_call should produce a (rejection) tool result"
    rejection = send_results[0]["content"]
    assert "does not exist" in rejection  # rejected, not dispatched to a driver
    # The send toolset is not even offered: it is absent from the available-tools
    # list the rejection enumerates (the prefix names the rejected tool; the gate
    # is the available set after it).
    available = rejection.split("Available tools:", 1)[-1]
    assert "toee_textline_reply" not in available

    # The turn still produced the proposed draft; no send happened.
    assert turn["final_response"].strip() == draft


# --- Slice 3: real OpenRouter provider wiring (Fork C1), proven keyless in CI ---


def test_keyed_path_runs_through_the_real_openrouter_boundary_via_injected_provider() -> None:
    # WITH a key (here: an injected config + scripted provider, so CI stays keyless),
    # make_copilot_run_turn routes through the real run_agent_turn OpenRouter boundary
    # booted internal_copilot UNBOUND, NOT the scripted/stub branch. Provenance reports
    # the resolved model slug (ADR-0009 primary), proving the keyed path was taken.
    run_turn = make_copilot_run_turn(
        config=OpenRouterConfig(
            base_url="https://openrouter.ai/api/v1",
            api_key="sk-or-test",
            model=OPENROUTER_PRIMARY_MODEL,
        ),
        openai_factory=_scripted_openai_factory(
            [{"content": "Drafted through the keyed OpenRouter path."}]
        ),
    )

    result = run_turn(channel="sms", case_id="case_keyed")

    assert result["draft"].strip() == "Drafted through the keyed OpenRouter path."
    assert result["model"] == OPENROUTER_PRIMARY_MODEL  # real slug, not "scripted"
    assert result["profile"] == INTERNAL


def test_keyed_path_falls_back_to_the_secondary_model_on_a_retryable_error() -> None:
    # ADR-0009 deepseek primary / qwen fallback, on the copilot turn: a retryable
    # primary-model failure retries the same completion on the fallback model, so the
    # draft is still produced. Reuses openrouter.py's per-completion fallback verbatim.
    config = OpenRouterConfig(
        base_url="https://openrouter.ai/api/v1",
        api_key="sk-or-test",
        model="deepseek/primary",
        fallback_model="qwen/fallback",
    )
    scripted = _scripted_openai_factory([{"content": "Draft served by the fallback model."}])
    state = {"failed": False}

    def base_factory(*args: object, **kwargs: object) -> object:
        inner = scripted(*args, **kwargs)
        serve = inner.chat.completions.create

        def create(**call_kwargs: object) -> object:
            if not state["failed"]:
                state["failed"] = True
                raise _RetryableBoom()
            return serve(**call_kwargs)

        inner.chat.completions.create = create
        return inner

    run_turn = make_copilot_run_turn(
        config=config,
        openai_factory=base_factory,
        is_retryable=lambda exc: isinstance(exc, _RetryableBoom),
    )

    result = run_turn(channel="sms", case_id="case_fallback")

    assert result["draft"].strip() == "Draft served by the fallback model."
    assert result["profile"] == INTERNAL


def test_internal_note_turn_yields_draft_and_no_subject() -> None:
    # The note envelope keys on `kind`, not a subject; the turn just yields the note
    # text and the endpoint shapes {kind, draft}. No subject is produced.
    run_turn = make_copilot_run_turn(scripted_completions=[{"content": "Internal note."}])

    result = run_turn(channel="internal_note", case_id="case_note")

    assert result["draft"].strip() == "Internal note."
    assert "subject" not in result
    assert result["profile"] == INTERNAL


# --- Slice 4: the conversational `chat` turn-mode (ADR-0147, closes #39) ----------
# /api/copilot/chat cuts over onto the SAME unbound internal_copilot agent-turn seam
# the drafts use, but framed conversationally (not "draft a reply") — the in-memory
# handleChat is single-shot (one message + case context -> one reply, no history), so
# the cutover is the draft path's twin with a chat system message. The reply is the
# turn's final_response; no subject is derived; the structural no-send invariant holds
# verbatim (same boot), proven below under a real multi-step loop.


def test_chat_channel_has_a_distinct_conversational_system_message() -> None:
    # Chat is framed differently from the three draft channels (decision: chat helps
    # the staff member work the case, not "draft a {channel} reply"). Non-empty and
    # distinct from every draft channel's message.
    chat_message = _system_message("chat")
    assert isinstance(chat_message, str) and chat_message.strip()
    draft_messages = {_system_message(c) for c in ("sms", "email", "internal_note")}
    assert chat_message not in draft_messages


def test_scripted_chat_turn_returns_final_response_as_reply() -> None:
    # Single-shot parity (Fork E1, reused): the agent's final assistant message IS the
    # chat reply. A scripted completion drives the real AIAgent loop (booted
    # internal_copilot, unbound) and its final_response comes back as the draft text
    # the endpoint relabels `reply`. No subject is produced for chat.
    reply = "Case case_ar_urgent is an open SMS order-status case — the customer is waiting on tracking."
    run_turn = make_copilot_run_turn(scripted_completions=[{"content": reply}])

    result = run_turn(channel="chat", case_id="case_ar_urgent", prompt="what's going on here?")

    assert result["draft"].strip() == reply
    assert "subject" not in result
    assert result["profile"] == INTERNAL
    assert result["model"] == SCRIPTED_MODEL


def test_chat_default_provider_is_a_deterministic_keyless_stub() -> None:
    # Mock-first (ADR-0137): with no completions and no key, the chat turn still yields
    # a deterministic, non-empty reply (a local stub), so the endpoint serves chat
    # keyless in local dev / CI exactly like the draft channels.
    run_turn = make_copilot_run_turn()

    result = run_turn(channel="chat", case_id="case_x", prompt="help")

    assert isinstance(result["draft"], str) and result["draft"].strip()
    assert result["profile"] == INTERNAL
    assert result["model"] == SCRIPTED_MODEL


def test_a_send_tool_call_is_rejected_in_a_chat_turn_under_the_real_loop() -> None:
    # Security crux for chat (ADR-0067/0035): the no-send invariant must hold for the
    # chat path too, against a REAL multi-step loop, not just at boot. A chat turn
    # boots the SAME unbound internal_copilot set (no send tool), so a scripted send
    # tool_call is rejected — never admitted, never dispatched — and the turn falls
    # through to proposed conversational text. No send is ever executed.
    booted = boot_profile(INTERNAL)
    assert "toee_textline_reply__send_message" not in booted.tool_names

    reply = "I can't send messages — here's a suggested reply for you to review and send."
    turn = run_scripted_agent(
        user_message=_user_message("chat", "c1", "just send the customer an apology"),
        system_message=_system_message("chat"),
        scripted_completions=[
            {
                "tool_calls": [
                    {
                        "name": "toee_textline_reply__send_message",
                        "arguments": {"conversation_id": "conv1", "body": "sneaky auto-send"},
                    }
                ]
            },
            {"content": reply},
        ],
        governed_tool_names=booted.tool_names,
    )

    send_results = [
        m
        for m in turn["messages"]
        if isinstance(m, dict)
        and m.get("role") == "tool"
        and m.get("name") == "toee_textline_reply__send_message"
    ]
    assert send_results, "the send tool_call should produce a (rejection) tool result"
    rejection = send_results[0]["content"]
    assert "does not exist" in rejection  # rejected, not dispatched to a driver
    available = rejection.split("Available tools:", 1)[-1]
    assert "toee_textline_reply" not in available
    assert turn["final_response"].strip() == reply


# --- S03 (FR-1): draft-persona write discipline for toee_customer_memory ---------
# The draft agent KEEPS upsert_preference in its allowlist (propose-only since
# S13/ADR-0150 -- the call never persists, see test_copilot_memory_write_overlay.py),
# so the persona still carries the same no-inferred discipline the external
# persona already proved (persona.py:99-103: "ONLY when the customer explicitly
# asks... NEVER save a preference you merely inferred") as defense in depth. All
# four channels boot the identical internal_copilot allowlist (REVIEWED_
# INTERNAL_ALLOWLIST above includes toee_customer_memory, and boot_profile never
# sees the channel), so every channel's system message must carry the guard.


def test_system_messages_carry_the_no_inferred_memory_write_rule() -> None:
    for channel in ("sms", "email", "internal_note", "chat"):
        message = _system_message(channel)
        assert "toee_customer_memory" in message
        assert "explicitly stated" in message
        assert "this case's conversation" in message
        lowered = message.lower()
        assert "never" in lowered and "infer" in lowered


def test_system_messages_document_read_tool_param_conventions() -> None:
    # Fix (task_8525be3c): the copilot draft prompts documented no tool parameter
    # names, while build_tool_schema gives every governed tool an OPEN schema, so the
    # draft agent guessed `order_id` for get_order and gave up when the sanitized
    # "temporarily unavailable" error hid the real cause. Mirror the External
    # persona's convention (persona.py) so every channel names order_number.
    for channel in ("sms", "email", "internal_note", "chat"):
        message = _system_message(channel)
        assert "order_number" in message
        assert "get_order" in message
        assert "get_delivery_status" in message
        # the load-bearing framing: exact names matter, wrong name == missing value.
        lowered = message.lower()
        assert "exact" in lowered and "parameter name" in lowered
