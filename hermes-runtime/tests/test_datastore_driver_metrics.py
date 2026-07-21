"""0.0.3 S26 (FR-28): Postgres-backed ``toee_metrics.get_aggregate_metrics``.

Admin-only aggregate-metrics read behind the same governed datastore-dispatch
seam ``get_memory_audit``/``list_agent_experience`` use (never LLM-callable --
see ``_AGENT_EXCLUDED_ACTIONS``). Seeds rows directly into the existing tables
(``customer_memory_slot``, ``customer_memory_merge_audit``,
``workbench_audit_log``, ``agent_experience``, ``metric_event``) and asserts
the SQL aggregation reads them back correctly. Skip-if-no-DB via the shared
``datastore`` fixture (a migrated throwaway schema).
"""

from __future__ import annotations

import uuid

from psycopg.types.json import Jsonb

from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext


def _get_metrics(driver):
    return execute_tool(
        tool="toee_metrics",
        action="get_aggregate_metrics",
        params={},
        context=ToolExecutionContext(profile="internal_copilot"),
        driver=driver,
    )


def _insert_slot(conn, *, binding_key: str, slot_name: str, source: str = "customer_explicit") -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO customer_memory_slot
                (id, binding_key, binding_kind, slot_name, slot_value, source)
            VALUES (%s, %s, 'verified', %s, 'x', %s)
            """,
            (f"mem_{uuid.uuid4().hex}", binding_key, slot_name, source),
        )
    conn.commit()


def _insert_merge_audit(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO customer_memory_merge_audit (id, provisional_key, verified_key, details)
            VALUES (%s, 'provisional:sms:+1', 'gid://shopify/Customer/1', %s)
            """,
            (f"merge_{uuid.uuid4().hex}", Jsonb({})),
        )
    conn.commit()


def _insert_audit_log(conn, *, action: str, details: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO workbench_audit_log (id, profile, action, details)
            VALUES (%s, 'internal_copilot', %s, %s)
            """,
            (f"audit_{uuid.uuid4().hex}", action, Jsonb(details)),
        )
    conn.commit()


def _insert_agent_experience(conn, *, status: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_experience (id, kind, status, content, source)
            VALUES (%s, 'note', %s, 'x', 'copilot_agent')
            """,
            (f"aexp_{uuid.uuid4().hex}", status),
        )
    conn.commit()


def _insert_metric_event(conn, *, metric: str, flag: bool) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO metric_event (id, metric, flag) VALUES (%s, %s, %s)",
            (f"metric_{uuid.uuid4().hex}", metric, flag),
        )
    conn.commit()


def test_empty_datastore_returns_zeroed_metrics_not_an_error(datastore) -> None:
    driver, _conn, _ = datastore
    result = _get_metrics(driver)

    assert result.ok, result
    data = result.data
    assert data["memory_injection"] == {"injected": 0, "total": 0, "rate": None}
    assert data["knowledge_search"] == {"found": 0, "total": 0, "rate": None}
    assert data["slots_populated_distribution"] == {"1": 0, "2": 0, "3": 0, "4": 0}
    assert data["merge_count"] == 0
    assert data["correction_count"] == 0
    assert data["proposal_outcomes"] == {"accepted": 0, "dismissed": 0, "rate": None}
    assert data["self_service_usage"]["count"] == 0
    assert data["self_service_usage"]["proxy"] is True
    assert data["l6_confirmed_entries"]["count"] == 0
    assert data["l6_confirmed_entries"]["proxy"] is True
    # Advisory, judge-sampled, never gating -- honestly labeled non-live.
    assert data["honored_rate"]["live"] is False
    assert data["honored_rate"]["rate"] is None
    assert "advisory" in data["honored_rate"]["label"].lower()


def test_aggregate_metrics_over_seeded_rows(datastore) -> None:
    driver, conn, _ = datastore

    # slots-populated distribution: two bindings with 1 slot each, one with 2.
    _insert_slot(conn, binding_key="cust_a", slot_name="contact_time_preference")
    _insert_slot(conn, binding_key="cust_b", slot_name="contact_time_preference")
    _insert_slot(conn, binding_key="cust_b", slot_name="delivery_habit_note")
    # correction_count: one employee_confirmed write.
    _insert_slot(conn, binding_key="cust_c", slot_name="contact_time_preference", source="employee_confirmed")

    _insert_merge_audit(conn)
    _insert_merge_audit(conn)

    _insert_audit_log(conn, action="proposal_dismissed", details={"slot": "x"})
    _insert_audit_log(conn, action="preference_cleared", details={"initiator": "customer"})
    _insert_audit_log(conn, action="preference_cleared", details={"initiator": "rep"})  # not self-service

    _insert_agent_experience(conn, status="confirmed")
    _insert_agent_experience(conn, status="proposed")  # excluded

    _insert_metric_event(conn, metric="memory_injection", flag=True)
    _insert_metric_event(conn, metric="memory_injection", flag=True)
    _insert_metric_event(conn, metric="memory_injection", flag=False)
    _insert_metric_event(conn, metric="knowledge_search", flag=True)
    _insert_metric_event(conn, metric="knowledge_search", flag=False)
    _insert_metric_event(conn, metric="knowledge_search", flag=False)

    result = _get_metrics(driver)
    assert result.ok, result
    data = result.data

    assert data["memory_injection"] == {"injected": 2, "total": 3, "rate": round(2 / 3, 4)}
    assert data["knowledge_search"] == {"found": 1, "total": 3, "rate": round(1 / 3, 4)}
    assert data["slots_populated_distribution"] == {"1": 2, "2": 1, "3": 0, "4": 0}
    assert data["merge_count"] == 2
    assert data["correction_count"] == 1
    assert data["proposal_outcomes"]["dismissed"] == 1
    # accept is inferred from employee_confirmed writes (no distinct audit action).
    assert data["proposal_outcomes"]["accepted"] == 1
    assert data["self_service_usage"]["count"] == 1  # only the customer-initiated clear
    assert data["l6_confirmed_entries"]["count"] == 1  # only the confirmed row
