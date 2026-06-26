"""Slice 33 / #36: Postgres-backed ``toee_identity_lookup`` through ``execute_tool``.

Resolves Ingress Phone Match / Email Sender Match against the Identity Graph
(``identity_link``, ADR-0043/0060) and reports Customer Email Link readiness for
accounting reads. Read-only: tests seed ``identity_link`` directly. Skip-if-no-DB.
"""

from __future__ import annotations

import uuid

from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext


def _link(conn, channel, channel_identity, shopify_customer_id, match_status="verified"):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO identity_link
                (id, channel, channel_identity, shopify_customer_id, match_status)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (f"idl_{uuid.uuid4().hex}", channel, channel_identity, shopify_customer_id, match_status),
        )
    conn.commit()


def _run(driver, action, params):
    return execute_tool(
        tool="toee_identity_lookup",
        action=action,
        params=params,
        context=ToolExecutionContext(profile="customer_service_external"),
        driver=driver,
    )


def test_match_phone_unmatched_returns_unmatched_caller(datastore) -> None:
    driver, _, _ = datastore
    result = _run(driver, "match_phone", {"phone": "+14165559999"})
    assert result.ok
    assert result.data["outcome"] == "unmatched_caller"


def test_match_phone_single_link_is_verified_customer(datastore) -> None:
    driver, conn, _ = datastore
    _link(conn, "sms", "+14165550101", "gid://shopify/Customer/1001")
    result = _run(driver, "match_phone", {"phone": "+14165550101"})
    assert result.ok
    assert result.data["outcome"] == "verified_customer"
    assert result.data["shopify_customer_id"] == "gid://shopify/Customer/1001"


def test_match_phone_multiple_links_is_ambiguous(datastore) -> None:
    driver, conn, _ = datastore
    _link(conn, "sms", "+14165550222", "gid://shopify/Customer/2001")
    _link(conn, "sms", "+14165550222", "gid://shopify/Customer/2002")
    result = _run(driver, "match_phone", {"phone": "+14165550222"})
    assert result.ok
    assert result.data["outcome"] == "ambiguous_phone_match"
    assert set(result.data["shopify_customer_ids"]) == {
        "gid://shopify/Customer/2001",
        "gid://shopify/Customer/2002",
    }


def test_match_email_sender_resolves_customer(datastore) -> None:
    driver, conn, _ = datastore
    _link(conn, "email", "accounts@acme-fleet.example", "gid://shopify/Customer/1001")
    result = _run(driver, "match_email_sender", {"from_address": "accounts@acme-fleet.example"})
    assert result.ok
    assert result.data["outcome"] == "verified_customer"
    assert result.data["shopify_customer_id"] == "gid://shopify/Customer/1001"


def test_get_email_link_status_linked_and_unlinked(datastore) -> None:
    driver, conn, _ = datastore
    _link(conn, "email", "accounts@acme-fleet.example", "gid://shopify/Customer/1001")

    linked = _run(driver, "get_email_link_status", {"shopify_customer_id": "gid://shopify/Customer/1001"})
    assert linked.data["status"] == "linked"

    unlinked = _run(driver, "get_email_link_status", {"shopify_customer_id": "gid://shopify/Customer/9999"})
    assert unlinked.data["status"] == "unlinked"
