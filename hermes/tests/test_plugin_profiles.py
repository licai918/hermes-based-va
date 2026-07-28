"""P5 profile allowlist + pre_llm_call injection tests.

Profile allowlists (ADR-0034 external, ADR-0035 internal copilot, ADR-0038
supervisor admin) are transcribed here as the test's source of truth; the plugin
must match them exactly. ``pre_llm_call`` injection follows ADR-0140 / ADR-0113:
append the Session Identity Snapshot + a compact Customer Memory block to the
user turn, never the system prompt, and never break the turn on provider error.
"""

from __future__ import annotations

from datetime import date

import pytest

from toee_hermes.plugin.hooks import (
    glossary_entries,
    make_pre_llm_call_hook,
    render_injection,
)
from toee_hermes.plugin.profiles import (
    DEFAULT_PROFILE,
    PROFILE_TOOL_ALLOWLIST,
    PROFILES,
    allowlisted_tools,
    resolve_profile,
)
from toee_hermes.tool_catalog import TOOL_CATALOG

ADR_0034_EXTERNAL = {
    "toee_knowledge_search",
    "toee_shopify_read",
    "toee_qbo_read",
    "toee_easyroutes_read",
    "toee_delivery_promise",
    "toee_square_payment_link",
    "toee_sms_reply",
    "toee_case",
    "toee_identity_lookup",
    "toee_customer_memory",
}
ADR_0035_INTERNAL = {
    "toee_knowledge_search",
    "toee_shopify_read",
    "toee_qbo_read",
    "toee_easyroutes_read",
    "toee_delivery_promise",
    "toee_identity_lookup",
    "toee_case_manage",
    "toee_copilot_draft",
    "toee_workbench_read",
    "toee_customer_memory",
    # 0.0.3 S22 (FR-23): L6 Agent-experience proposals -- internal_copilot only.
    "toee_agent_experience",
    # 0.0.5 S01 (FR-1/FR-3): L7 Semantic Lexicon -- internal_copilot only
    # (S04's capture fork proposes; the admin BFF dispatches over this
    # profile's API). list_lexicon_entries is agent-excluded.
    "toee_semantic_lexicon",
    # 0.0.5 S15 (FR-22): the unified review inbox + `review_item` store. Here
    # rather than supervisor_admin because re-classify dispatches to
    # toee_agent_experience and toee_semantic_lexicon, which are allowlisted on
    # THIS profile only -- one governed action cannot span two profiles'
    # toolsets. All four actions are agent-excluded.
    "toee_review_inbox",
    # 0.0.3 S26 (FR-28): aggregate-metrics admin panel, reached over this
    # profile's API by the admin BFF (same reason get_memory_audit lives here).
    "toee_metrics",
    # 0.0.3 S28 (FR-30): Customer Memory retention sweep admin panel, reached
    # over this profile's API by the admin BFF (same precedent as toee_metrics).
    "toee_retention",
    # 0.0.4 S02 (ADR-0154): the manual scoring feedback tool shell -- the three
    # write actions (submit_interaction_review, record_draft_outcome,
    # submit_draft_rating) are dispatched from copilot/review-fork surfaces.
    # All four actions are agent-excluded (see toee_hermes.plugin), so this
    # allowlisting only opens the dispatch gate for the BFF, never the model.
    "toee_feedback",
}
ADR_0038_SUPERVISOR = {
    "toee_knowledge_ops",
    "toee_eval_review",
    "toee_workbench_admin",
    "toee_workbench_read",
    "toee_knowledge_search",
    # 0.0.4 S05 (FR-13): the dead-letter view + governed Replay -- an OPERATIONS
    # surface reached over this profile's API by the admin BFF. Both actions are
    # agent-excluded, so nothing here reaches a model's tool loop.
    "toee_job_queue",
    # 0.0.4 S15 (FR-23): the /admin/integrations status read -- a CREDENTIAL
    # surface reached over this profile's API by the admin BFF. Agent-excluded.
    "toee_integrations",
    # 0.0.4 S02 (ADR-0154): list_feedback -- the supervisor read over both
    # feedback tables (S10). Agent-excluded like every action on this tool.
    "toee_feedback",
}


# --- profiles --------------------------------------------------------------


def test_profiles_are_the_three_adr_profiles() -> None:
    assert set(PROFILES) == {
        "customer_service_external",
        "internal_copilot",
        "supervisor_admin",
    }
    assert DEFAULT_PROFILE == "customer_service_external"


def test_allowlists_match_adrs() -> None:
    assert set(PROFILE_TOOL_ALLOWLIST["customer_service_external"]) == ADR_0034_EXTERNAL
    assert set(PROFILE_TOOL_ALLOWLIST["internal_copilot"]) == ADR_0035_INTERNAL
    assert set(PROFILE_TOOL_ALLOWLIST["supervisor_admin"]) == ADR_0038_SUPERVISOR


def test_every_allowlisted_tool_exists_in_catalog() -> None:
    for profile in PROFILES:
        for tool in allowlisted_tools(profile):
            assert tool in TOOL_CATALOG


def test_profiles_union_covers_all_catalog_tools() -> None:
    union: set[str] = set()
    for profile in PROFILES:
        union |= set(allowlisted_tools(profile))
    assert union == set(TOOL_CATALOG)


def test_toee_feedback_resolves_for_internal_copilot_and_supervisor_admin() -> None:
    # S02 acceptance: the tool must resolve (be dispatchable) for BOTH profiles --
    # internal_copilot for the three write actions, supervisor_admin for
    # list_feedback. Model exclusion is a separate guarantee, asserted in
    # test_plugin.py against _AGENT_EXCLUDED_ACTIONS.
    assert "toee_feedback" in allowlisted_tools("internal_copilot")
    assert "toee_feedback" in allowlisted_tools("supervisor_admin")
    assert "toee_feedback" not in allowlisted_tools("customer_service_external")


def test_allowlisted_tools_rejects_unknown_profile() -> None:
    with pytest.raises(ValueError):
        allowlisted_tools("not_a_profile")


def test_resolve_profile_prefers_ctx_then_env_then_default(monkeypatch) -> None:
    class Ctx:
        profile = "internal_copilot"

    monkeypatch.delenv("TOEE_HERMES_PROFILE", raising=False)
    assert resolve_profile(Ctx()) == "internal_copilot"
    monkeypatch.setenv("TOEE_HERMES_PROFILE", "supervisor_admin")
    assert resolve_profile(None) == "supervisor_admin"
    monkeypatch.delenv("TOEE_HERMES_PROFILE", raising=False)
    assert resolve_profile(None) == DEFAULT_PROFILE


def test_resolve_profile_rejects_unknown(monkeypatch) -> None:
    monkeypatch.setenv("TOEE_HERMES_PROFILE", "nope")
    with pytest.raises(ValueError):
        resolve_profile(None)


# --- pre_llm_call injection (ADR-0140, ADR-0113) ---------------------------


def test_render_injection_returns_none_when_empty() -> None:
    assert render_injection(None, None) is None
    assert render_injection({}, []) is None


def test_pre_llm_call_injects_identity_and_memory() -> None:
    hook = make_pre_llm_call_hook(
        snapshot_provider=lambda sid: {
            "shopify_customer_id": "cust_1",
            "verified": True,
        },
        memory_provider=lambda sid: [{"slot": "preferred_name", "value": "Sam"}],
    )
    out = hook(
        session_id="s1",
        user_message="hi",
        conversation_history=[],
        is_first_turn=True,
        model="m",
        platform="simpletexting",
    )
    assert out is not None
    assert "context" in out
    assert "cust_1" in out["context"]
    assert "preferred_name" in out["context"]


def test_memory_block_is_framed_as_untrusted_data_not_instructions() -> None:
    # FR-6/RK-2: a stored preference is customer-authored free text re-injected every
    # turn — a persistent prompt-injection surface. The block must be wrapped in an
    # explicit untrusted-data delimiter and framed as preferences to honor, never as
    # instructions to obey, while the slot value itself stays intact and unmodified.
    memory = [{"slot": "contact_time_preference", "value": "after 5pm"}]
    out = render_injection(None, memory)

    assert out is not None
    assert "<untrusted_customer_memory>" in out
    assert "</untrusted_customer_memory>" in out
    assert "not instructions to obey" in out
    assert "- contact_time_preference: after 5pm" in out

    # Genuine wrapping, not just incidental substrings anywhere in the string.
    open_tag = out.index("<untrusted_customer_memory>")
    header = out.index("Customer Memory (preferences):")
    slot_line = out.index("- contact_time_preference: after 5pm")
    close_tag = out.index("</untrusted_customer_memory>")
    assert open_tag < header < slot_line < close_tag


def test_confirmed_experience_block_is_fenced_as_approved_guidance() -> None:
    # S25 (FR-25): confirmed L6 entries are human-approved but model-ORIGINATED
    # operational guidance. They must be fenced (like Customer Memory) and framed
    # as guidance to apply, not unconditional instructions -- consistent with the
    # hooks fencing discipline. Only the content is rendered.
    experience = [
        {"content": "For EasyRoutes gaps, check get_delivery_status first.", "kind": "procedure"},
        {"content": "Confirm the ship-to ZIP before quoting freight.", "kind": "note"},
    ]
    out = render_injection(None, None, experience)

    assert out is not None
    assert "<confirmed_operational_learnings>" in out
    assert "</confirmed_operational_learnings>" in out
    assert "guidance" in out.lower()
    assert "- For EasyRoutes gaps, check get_delivery_status first." in out
    assert "- Confirm the ship-to ZIP before quoting freight." in out

    open_tag = out.index("<confirmed_operational_learnings>")
    first_line = out.index("- For EasyRoutes gaps")
    close_tag = out.index("</confirmed_operational_learnings>")
    assert open_tag < first_line < close_tag


def test_render_injection_without_experience_is_unchanged() -> None:
    # Eval-pin invariant: the eval path calls render_injection(snapshot, memory)
    # with no experience arg, so its output must be byte-identical to before S25.
    memory = [{"slot": "contact_time_preference", "value": "after 5pm"}]
    assert render_injection(None, memory) == render_injection(None, memory, None)
    assert render_injection(None, None, []) is None
    assert render_injection(None, None, None) is None


def test_pre_llm_call_returns_none_when_nothing_to_inject() -> None:
    hook = make_pre_llm_call_hook()
    out = hook(
        session_id="s1",
        user_message="hi",
        conversation_history=[],
        is_first_turn=True,
        model="m",
        platform="simpletexting",
    )
    assert out is None


def test_pre_llm_call_swallows_provider_errors() -> None:
    def boom(_sid: str):
        raise RuntimeError("provider down")

    hook = make_pre_llm_call_hook(snapshot_provider=boom, memory_provider=boom)
    out = hook(session_id="s1", user_message="hi")
    assert out is None


# --- glossary_entries: the SELECTION rules, driven directly (S06, FR-6/FR-7) ---
#
# Everything above reaches this function through a renderer, so its rules were
# only ever asserted as formatted text. `glossary_entries` decides WHAT enters
# the prompt -- the status re-check, the both-forms requirement for mapping
# rows, and the `default_rule` condition evaluated against a DATE -- and
# `_render_lexicon` only formats what it returns. These drive the selector.


def _lex(entry_id, kind, surface, canonical, *, status="confirmed", domain="tire"):
    """A row in the shape ``load_confirmed_lexicon`` returns."""
    return {
        "id": entry_id,
        "domain": domain,
        "entry_kind": kind,
        "surface_form": surface,
        "canonical_form": canonical,
        "status": status,
    }


# BOTH seasonal rows confirmed and present -- the seeded situation, and the only
# fixture in which "evaluated at render" has something it must EXCLUDE. With one
# seasonal row, selecting and not-selecting return the same list.
_BOTH_SEASONS = [
    _lex("lex_alias", "alias", "TOEE", "TOEE TIRE", domain="company"),
    _lex("lex_winter", "default_rule", "season=winter", "winter tires"),
    _lex("lex_all_season", "default_rule", "season=all_season", "all-season tires"),
]

_JANUARY = date(2026, 1, 15)  # inside WINTER_MONTHS
_JULY = date(2026, 7, 15)  # outside it


@pytest.mark.parametrize(
    ("today", "applied", "losing"),
    [
        (_JANUARY, "lex_winter", "lex_all_season"),
        (_JULY, "lex_all_season", "lex_winter"),
    ],
)
def test_glossary_entries_admits_only_the_season_the_date_picks(
    today: date, applied: str, losing: str
) -> None:
    # Fixed dates, not date.today(): the two cases sit on either side of the
    # WINTER_MONTHS boundary, so a selector that ignored `today` cannot satisfy
    # both. The losing season's row is not merely unformatted -- it is not
    # returned at all, which is what keeps the provenance ledger from crediting
    # an entry the prompt never carried.
    ids = [entry["id"] for entry in glossary_entries(_BOTH_SEASONS, today)]
    assert ids == ["lex_alias", applied]
    assert losing not in ids


def test_a_confirmed_season_override_row_beats_the_date_derived_season() -> None:
    # S03's admin escape hatch, resolved here. Driven in JANUARY, where the
    # calendar's own answer is `winter` -- so `lex_all_season` can only be in the
    # list because the override outranked current_season(today).
    entries = [
        *_BOTH_SEASONS,
        _lex("lex_override", "default_rule", "season=override", "all_season"),
    ]
    ids = [entry["id"] for entry in glossary_entries(entries, _JANUARY)]

    assert "lex_all_season" in ids
    assert "lex_winter" not in ids
    # The override row is CONSULTED, never SELECTED: it is configuration, not
    # vocabulary, so `season=override` never becomes a glossary line.
    assert "lex_override" not in ids


def test_running_glossary_entries_over_its_own_output_loses_the_override() -> None:
    # The documented NOT-idempotent property, pinned rather than promised: because
    # the override row is consulted but not returned, a caller that pre-narrows
    # the lexicon and re-runs falls back to the calendar -- and in JULY the
    # calendar has no `season=winter` row left to apply, so the seasonal default
    # disappears entirely. This is why both turn seams hand render_injection the
    # RAW store read and call the selector separately for the ledger.
    entries = [
        *_BOTH_SEASONS,
        _lex("lex_override", "default_rule", "season=override", "winter"),
    ]
    once = glossary_entries(entries, _JULY)
    assert [entry["id"] for entry in once] == ["lex_alias", "lex_winter"]
    assert [entry["id"] for entry in glossary_entries(once, _JULY)] == ["lex_alias"]


def test_glossary_entries_selects_nothing_without_admissible_rows() -> None:
    assert glossary_entries(None, _JANUARY) == []
    assert glossary_entries([], _JANUARY) == []
    # Non-empty, but nothing admissible: the status re-check (the store read
    # already filters, but a row that arrived by any other route must not become
    # prompt text) and the both-forms requirement for mapping rows. An empty
    # selection is what makes _render_lexicon return None instead of emitting a
    # fence with a header and no lines.
    assert (
        glossary_entries(
            [
                _lex("lex_p", "alias", "GOODYEAR", "GOODYEAR TIRE", status="proposed"),
                _lex("lex_r", "default_rule", "season=winter", "winter tires", status="retired"),
                _lex("lex_no_canonical", "alias", "TOEE", None),
            ],
            _JANUARY,
        )
        == []
    )
