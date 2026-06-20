"""Launch Eval fixture loader + merge tests (ADR-0071, ADR-0073, ADR-0119).

Ports packages/eval-runner fixtures.test.ts to the Python runner: base.yaml
identity presets, scenario parse/validation, baseline->preset->overrides merge,
and suite discovery against the real repository fixtures under <repo>/eval.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eval_runner.fixtures import (
    RESOLVED_AT,
    load_base_mocks,
    load_scenario,
    load_suite,
    parse_scenario_content,
    resolve_scenario,
)

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"


def _base():
    return load_base_mocks(EVAL_DIR)


# --- load_base_mocks -------------------------------------------------------


def test_reads_identity_presets_from_base_yaml() -> None:
    mocks = _base()
    assert mocks.identities["verified_customer_a"]["phone"] == "+14165550101"
    assert (
        mocks.identities["verified_customer_a"]["shopify_customer_id"]
        == "gid://shopify/Customer/1001"
    )
    assert mocks.identities["unmatched_phone"]["phone"] == "+14165550999"
    assert len(mocks.identities["ambiguous_phone"]["shopify_customer_ids"]) == 2
    assert (
        mocks.identities["email_verified_a"]["from_address"]
        == "accounts@acme-fleet.example"
    )


# --- parse_scenario_content ------------------------------------------------


def test_parses_sms_scenario_with_tool_assertions() -> None:
    fixture = parse_scenario_content(
        'scenario_id: "01"\ntitle: t\nsuite: text_first_launch\nchannel: textline\n'
        "identity_preset: verified_customer_a\nturns:\n  - inbound: hi\n"
        "mock_overrides: {}\nassertions:\n  tool:\n    expect_calls:\n"
        "      - tool: toee_shopify_read\n        action: get_order\n"
        "  max_severity: medium\n",
        "01-x.yaml",
    )
    assert fixture.scenario_id == "01"
    assert fixture.suite == "text_first_launch"
    assert fixture.assertions.tool["expect_calls"][0] == {
        "tool": "toee_shopify_read",
        "action": "get_order",
    }


def test_parses_email_object_form_turn() -> None:
    fixture = parse_scenario_content(
        'scenario_id: "19"\ntitle: t\nsuite: email_go_live\nchannel: email\n'
        "identity_preset: email_verified_a\nturns:\n  - inbound:\n      body: hello\n"
        "      subject: hi\nmock_overrides: {}\nassertions:\n  disclosure:\n"
        "    requires_email_support_signature: true\n  max_severity: medium\n",
        "email/19-x.yaml",
    )
    assert fixture.turns[0].inbound == {"body": "hello", "subject": "hi"}


def test_rejects_missing_scenario_id() -> None:
    with pytest.raises(ValueError, match=r"bad\.yaml.*scenario_id"):
        parse_scenario_content(
            "title: t\nsuite: text_first_launch\nchannel: textline\n"
            "identity_preset: x\nturns: []\nmock_overrides: {}\nassertions:\n"
            "  max_severity: medium\n",
            "bad.yaml",
        )


def test_rejects_scenario_id_filename_prefix_mismatch() -> None:
    with pytest.raises(ValueError, match=r"99-mismatch\.yaml.*05"):
        parse_scenario_content(
            'scenario_id: "05"\ntitle: t\nsuite: text_first_launch\nchannel: textline\n'
            "identity_preset: verified_customer_a\nturns:\n  - inbound: hi\n"
            "mock_overrides: {}\nassertions:\n  max_severity: medium\n",
            "99-mismatch.yaml",
        )


def test_rejects_missing_max_severity() -> None:
    with pytest.raises(ValueError, match=r"max_severity"):
        parse_scenario_content(
            'scenario_id: "07"\ntitle: t\nsuite: text_first_launch\nchannel: textline\n'
            "identity_preset: verified_customer_a\nturns:\n  - inbound: hi\n"
            'mock_overrides: {}\nassertions:\n  text:\n    must_contain: ["x"]\n',
            "07-x.yaml",
        )


# --- resolve_scenario ------------------------------------------------------


def _resolve(content: str, label: str):
    return resolve_scenario(parse_scenario_content(content, label), _base(), label)


def test_resolves_verified_customer_with_snapshot_and_linked_accounting() -> None:
    merged = _resolve(
        'scenario_id: "01"\ntitle: t\nsuite: text_first_launch\nchannel: textline\n'
        "identity_preset: verified_customer_a\nturns:\n  - inbound: hi\n"
        "mock_overrides: {}\nassertions:\n  behavioral:\n    case_created: false\n"
        "  max_severity: medium\n",
        "01-x.yaml",
    )
    assert merged.session_identity == {
        "outcome": "verified_customer",
        "shopify_customer_id": "gid://shopify/Customer/1001",
        "resolved_at": RESOLVED_AT,
    }
    assert merged.mock_context.qbo.email_links["gid://shopify/Customer/1001"] == "linked"
    assert len(merged.mock_context.square.payables) > 0
    assert merged.mock_context.domain_errors == {}


def test_resolves_unmatched_caller() -> None:
    merged = _resolve(
        'scenario_id: "02"\ntitle: t\nsuite: text_first_launch\nchannel: textline\n'
        "identity_preset: unmatched_phone\nturns:\n  - inbound: hi\n"
        "mock_overrides: {}\nassertions:\n  disclosure:\n    no_account_disclosure: true\n"
        "  max_severity: high\n",
        "02-x.yaml",
    )
    assert merged.session_identity["outcome"] == "unmatched_caller"


def test_resolves_ambiguous_phone_match_with_both_ids() -> None:
    merged = _resolve(
        'scenario_id: "03"\ntitle: t\nsuite: text_first_launch\nchannel: textline\n'
        "identity_preset: ambiguous_phone\nturns:\n  - inbound: hi\n"
        'mock_overrides: {}\nassertions:\n  text:\n    must_contain: ["order number"]\n'
        "  max_severity: medium\n",
        "03-x.yaml",
    )
    assert merged.session_identity["outcome"] == "ambiguous_phone_match"
    assert len(merged.session_identity["shopify_customer_ids"]) == 2


def test_applies_email_link_failure_override() -> None:
    merged = _resolve(
        'scenario_id: "04"\ntitle: t\nsuite: text_first_launch\nchannel: textline\n'
        "identity_preset: verified_customer_a\nturns:\n  - inbound: hi\n"
        "mock_overrides:\n  qbo:\n    email_links:\n      verified_customer_a: failed\n"
        "assertions:\n  behavioral:\n    case_created: true\n  max_severity: high\n",
        "04-x.yaml",
    )
    assert (
        merged.mock_context.qbo.email_links["gid://shopify/Customer/1001"] == "unlinked"
    )


def test_carries_domain_error_override() -> None:
    merged = _resolve(
        'scenario_id: "13"\ntitle: t\nsuite: text_first_launch\nchannel: textline\n'
        "identity_preset: unmatched_phone\nturns:\n  - inbound: hi\n"
        "mock_overrides:\n  shopify:\n    error: unavailable\nassertions:\n"
        "  behavioral:\n    case_created: true\n  max_severity: medium\n",
        "13-x.yaml",
    )
    assert merged.mock_context.domain_errors["shopify"] == "unavailable"


def test_injects_memory_preset_into_memory_mock_data() -> None:
    merged = _resolve(
        'scenario_id: "25"\ntitle: t\nsuite: text_first_launch\nchannel: textline\n'
        "identity_preset: verified_customer_a\nmemory_preset:\n"
        '  contact_time_preference: "after 2pm Eastern"\nturns:\n  - inbound: hi\n'
        "mock_overrides: {}\nassertions:\n  memory_assertions:\n"
        "    honor_injected_preference: true\n  max_severity: medium\n",
        "25-x.yaml",
    )
    assert merged.memory_preset["contact_time_preference"] == "after 2pm Eastern"
    assert (
        merged.mock_context.memory.preferences["contact_time_preference"]
        == "after 2pm Eastern"
    )


def test_throws_for_unknown_identity_preset() -> None:
    with pytest.raises(ValueError, match=r"nope_preset"):
        _resolve(
            'scenario_id: "01"\ntitle: t\nsuite: text_first_launch\nchannel: textline\n'
            "identity_preset: nope_preset\nturns:\n  - inbound: hi\n"
            "mock_overrides: {}\nassertions:\n  max_severity: medium\n",
            "01-x.yaml",
        )


# --- load_suite / load_scenario against real fixtures ----------------------


def test_loads_text_first_launch_suite_sorted_sms_only() -> None:
    scenarios = load_suite("text_first_launch", EVAL_DIR)
    ids = [s.scenario_id for s in scenarios]
    assert "01" in ids
    assert "24" in ids
    assert "26" in ids
    assert all(s.suite == "text_first_launch" for s in scenarios)
    assert ids == sorted(ids)
    assert len(scenarios) >= 20


def test_loads_email_go_live_suite_from_subfolder() -> None:
    scenarios = load_suite("email_go_live", EVAL_DIR)
    assert all(s.suite == "email_go_live" for s in scenarios)
    assert all(s.channel == "email" for s in scenarios)
    assert "19" in [s.scenario_id for s in scenarios]


def test_loads_single_scenario_by_suite_and_id() -> None:
    merged = load_scenario("text_first_launch", "05", EVAL_DIR)
    assert merged.scenario_id == "05"
    assert "payment link" in merged.title.lower()


def test_throws_when_scenario_id_not_found() -> None:
    with pytest.raises(ValueError, match=r"99"):
        load_scenario("text_first_launch", "99", EVAL_DIR)
