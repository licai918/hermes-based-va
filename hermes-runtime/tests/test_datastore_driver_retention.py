"""0.0.3 S28 (FR-30): Postgres-backed ``toee_retention`` sweep + status read.

Ages out ``customer_memory_slot`` rows per the ADR-0004/0116 class windows
(``hermes_runtime.datastore.handlers.retention``). Seeds rows directly with an
explicit ``last_interaction_at`` (and, for the "recently refreshed" case, a
deliberately stale ``created_at``) so the tests prove the age basis is
``last_interaction_at``, never ``created_at``, and that the sweep deletes
ONLY the rows past their own class window -- both directions, per the S28
brief's no-over-deletion requirement. Skip-if-no-DB via the shared
``datastore`` fixture (a migrated throwaway schema).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from psycopg.types.json import Jsonb

from toee_hermes.drivers.mock.retention import (
    PROVISIONAL_RETENTION_DAYS,
    VERIFIED_RETENTION_DAYS,
)
from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext

NOW = datetime.now(timezone.utc)


def _sweep(driver):
    return execute_tool(
        tool="toee_retention",
        action="trigger_retention_sweep",
        params={},
        context=ToolExecutionContext(profile="internal_copilot"),
        driver=driver,
    )


def _status(driver):
    return execute_tool(
        tool="toee_retention",
        action="get_retention_status",
        params={},
        context=ToolExecutionContext(profile="internal_copilot"),
        driver=driver,
    )


def _insert_slot(
    conn,
    *,
    binding_key: str,
    binding_kind: str,
    last_interaction_at: datetime,
    created_at: datetime | None = None,
    slot_name: str = "contact_time_preference",
) -> str:
    slot_id = f"mem_{uuid.uuid4().hex}"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO customer_memory_slot
                (id, binding_key, binding_kind, slot_name, slot_value, source,
                 created_at, updated_at, last_interaction_at)
            VALUES (%s, %s, %s, %s, 'x', 'customer_explicit', %s, %s, %s)
            """,
            (
                slot_id,
                binding_key,
                binding_kind,
                slot_name,
                created_at or last_interaction_at,
                last_interaction_at,
                last_interaction_at,
            ),
        )
    conn.commit()
    return slot_id


def _remaining_ids(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM customer_memory_slot")
        return {row[0] for row in cur.fetchall()}


def _insert_merge_audit(conn) -> str:
    audit_id = f"merge_{uuid.uuid4().hex}"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO customer_memory_merge_audit (id, provisional_key, verified_key, details)
            VALUES (%s, 'provisional:sms:+1', 'gid://shopify/Customer/1', %s)
            """,
            (audit_id, Jsonb({})),
        )
    conn.commit()
    return audit_id


def test_empty_datastore_sweep_deletes_nothing_and_records_zero_counts(datastore) -> None:
    driver, _conn, _ = datastore
    result = _sweep(driver)

    assert result.ok, result
    assert result.data["counts"] == {"verified": 0, "provisional": 0}
    assert result.data["total_deleted"] == 0
    assert result.data["windows_days"] == {
        "verified": VERIFIED_RETENTION_DAYS,
        "provisional": PROVISIONAL_RETENTION_DAYS,
    }
    assert result.data["run_at"]


def test_sweep_deletes_exactly_the_aged_rows_per_class_no_over_deletion(datastore) -> None:
    driver, conn, _ = datastore

    aged_verified = _insert_slot(
        conn,
        binding_key="cust_verified_aged",
        binding_kind="verified",
        last_interaction_at=NOW - timedelta(days=VERIFIED_RETENTION_DAYS + 5),
    )
    in_window_verified = _insert_slot(
        conn,
        binding_key="cust_verified_fresh",
        binding_kind="verified",
        # Older than the provisional window but well inside the verified one --
        # must be retained (proves the per-class window, not a single cutoff).
        last_interaction_at=NOW - timedelta(days=PROVISIONAL_RETENTION_DAYS + 5),
    )
    aged_provisional = _insert_slot(
        conn,
        binding_key="provisional:sms:+15551230000",
        binding_kind="provisional",
        last_interaction_at=NOW - timedelta(days=PROVISIONAL_RETENTION_DAYS + 5),
    )
    in_window_provisional = _insert_slot(
        conn,
        binding_key="provisional:sms:+15551230001",
        binding_kind="provisional",
        last_interaction_at=NOW - timedelta(days=5),
    )
    # Age basis is last_interaction_at, NOT created_at: this row was CREATED
    # long before either class window, but a recent interaction refreshed it
    # (ADR-0116) -- must be retained.
    recently_refreshed_verified = _insert_slot(
        conn,
        binding_key="cust_verified_refreshed",
        binding_kind="verified",
        created_at=NOW - timedelta(days=VERIFIED_RETENTION_DAYS + 100),
        last_interaction_at=NOW - timedelta(minutes=5),
    )

    result = _sweep(driver)

    assert result.ok, result
    assert result.data["counts"] == {"verified": 1, "provisional": 1}
    assert result.data["total_deleted"] == 2

    remaining = _remaining_ids(conn)
    assert aged_verified not in remaining
    assert aged_provisional not in remaining
    assert in_window_verified in remaining
    assert in_window_provisional in remaining
    assert recently_refreshed_verified in remaining


def test_sweep_never_touches_merge_audit_seven_year_table(datastore) -> None:
    driver, conn, _ = datastore
    merge_audit_id = _insert_merge_audit(conn)
    _insert_slot(
        conn,
        binding_key="cust_verified_aged",
        binding_kind="verified",
        last_interaction_at=NOW - timedelta(days=VERIFIED_RETENTION_DAYS + 5),
    )

    result = _sweep(driver)
    assert result.ok, result
    assert result.data["total_deleted"] == 1

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM customer_memory_merge_audit WHERE id = %s", (merge_audit_id,)
        )
        assert cur.fetchone() is not None


def test_second_run_right_after_is_idempotent(datastore) -> None:
    driver, conn, _ = datastore
    _insert_slot(
        conn,
        binding_key="cust_verified_aged",
        binding_kind="verified",
        last_interaction_at=NOW - timedelta(days=VERIFIED_RETENTION_DAYS + 5),
    )

    first = _sweep(driver)
    assert first.ok and first.data["total_deleted"] == 1

    second = _sweep(driver)
    assert second.ok, second
    assert second.data["counts"] == {"verified": 0, "provisional": 0}
    assert second.data["total_deleted"] == 0


def test_get_retention_status_before_any_run_reports_never_run(datastore) -> None:
    driver, _conn, _ = datastore
    result = _status(driver)

    assert result.ok, result
    assert result.data["last_run_at"] is None
    assert result.data["counts"] == {"verified": 0, "provisional": 0}
    assert result.data["total_deleted"] == 0


def test_get_retention_status_reads_back_last_run_and_per_class_counts(datastore) -> None:
    driver, conn, _ = datastore
    _insert_slot(
        conn,
        binding_key="cust_verified_aged",
        binding_kind="verified",
        last_interaction_at=NOW - timedelta(days=VERIFIED_RETENTION_DAYS + 5),
    )
    _insert_slot(
        conn,
        binding_key="provisional:sms:+15551230002",
        binding_kind="provisional",
        last_interaction_at=NOW - timedelta(days=PROVISIONAL_RETENTION_DAYS + 5),
    )

    sweep_result = _sweep(driver)
    assert sweep_result.ok, sweep_result

    status = _status(driver)
    assert status.ok, status
    assert status.data["last_run_at"] == sweep_result.data["run_at"]
    assert status.data["counts"] == {"verified": 1, "provisional": 1}
    assert status.data["total_deleted"] == 2
    assert status.data["windows_days"] == {
        "verified": VERIFIED_RETENTION_DAYS,
        "provisional": PROVISIONAL_RETENTION_DAYS,
    }
