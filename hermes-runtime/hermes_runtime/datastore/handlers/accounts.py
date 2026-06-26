"""Datastore handlers for ``toee_workbench_admin`` (ADR-0069/0089).

Workbench account administration is a Supervisor Admin governance surface, so
every mutation appends a Workbench Audit Log row in the same transaction. Reads
never return ``password_hash``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from psycopg.rows import dict_row

from toee_hermes.errors import ToolDriverError

from ._common import insert_audit, new_id, read_string, serialize_row

if TYPE_CHECKING:  # pragma: no cover - typing only
    from toee_hermes.tool_gate import ToolExecutionContext


def _require_actor(context: "ToolExecutionContext") -> str:
    """The acting Supervisor Admin for a governed write, or a governed denial.

    Account/governance mutations are the point of actor-attributed audit (ADR-0029/
    0089/0141): the actor rides ``ToolExecutionContext.user_id``, asserted by the
    BFF under the shared bearer. Trusting an absent actor would write the mutation
    *and* a NULL-actor audit row while returning success — a silent wrong-success.
    Fail closed here so every admin write handler is protected at once: no
    attributed actor, no write. (Mirrors ``handlers/cases._require_actor``.)
    """
    actor = context.user_id
    if not actor:
        raise ToolDriverError(
            "policy_blocked", "A governed admin write requires an attributed actor."
        )
    return actor


def _account_row(conn, account_id: str) -> Any:
    """The account read model the BFF maps onto PublicAccount.

    Selects only the wire-safe columns — ``password_hash`` is never read here, so a
    mutation's returned row cannot leak the hash.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id, username, role, status, created_at, updated_at"
            " FROM workbench_account WHERE id = %s",
            (account_id,),
        )
        row = cur.fetchone()
    serialized = serialize_row(row)
    if serialized is not None:
        serialized["account_id"] = serialized["id"]
    return serialized


def _ensure_account(conn, account_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM workbench_account WHERE id = %s", (account_id,))
        if cur.fetchone() is None:
            # not_found (BFF -> 404), store-path "account not found" parity; a 502
            # unexpected_error would mislabel a plain missing row as a server fault.
            raise ToolDriverError("not_found", f"account {account_id} not found.")


def _create_account(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    actor = _require_actor(context)
    username = read_string(params, "username")
    password_hash = read_string(params, "password_hash", "passwordHash")
    role = read_string(params, "role")
    if username is None or password_hash is None or role is None:
        raise ToolDriverError(
            "unexpected_error", "username, password_hash, and role are required."
        )
    account_id = new_id("acct")
    with conn.cursor() as cur:
        # Atomic uniqueness gate (ADR-0089): ON CONFLICT keeps the duplicate-username
        # check in SQL, so two concurrent creates can't both win — the loser inserts
        # no row. A non-atomic pre-read would race. Maps to governed conflict -> 409
        # (store-path parity), and the raise rolls back so no audit row is written.
        cur.execute(
            "INSERT INTO workbench_account (id, username, password_hash, role)"
            " VALUES (%s, %s, %s, %s) ON CONFLICT (username) DO NOTHING",
            (account_id, username, password_hash, role),
        )
        created = cur.rowcount == 1
    if not created:
        raise ToolDriverError("conflict", f"username {username} already exists.")
    insert_audit(
        conn,
        profile=context.profile,
        account_id=actor,
        action="create_account",
        target_type="account",
        target_id=account_id,
        details={"username": username, "role": role},
    )
    return {"account_id": account_id, "created": True, "account": _account_row(conn, account_id)}


def _list_accounts(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, username, role, status, created_at, updated_at
            FROM workbench_account ORDER BY created_at
            """
        )
        rows = cur.fetchall()
    accounts = []
    for row in rows:
        serialized = serialize_row(row)
        serialized["account_id"] = serialized["id"]
        accounts.append(serialized)
    return {"accounts": accounts}


def _update_account_role(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    actor = _require_actor(context)
    account_id = read_string(params, "account_id", "accountId")
    role = read_string(params, "role")
    if account_id is None or role is None:
        raise ToolDriverError("unexpected_error", "account_id and role are required.")
    _ensure_account(conn, account_id)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE workbench_account SET role = %s, updated_at = now() WHERE id = %s",
            (role, account_id),
        )
    insert_audit(
        conn,
        profile=context.profile,
        account_id=actor,
        action="update_account_role",
        target_type="account",
        target_id=account_id,
        details={"role": role},
    )
    return {
        "account_id": account_id,
        "role": role,
        "updated": True,
        "account": _account_row(conn, account_id),
    }


def _disable_account(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    actor = _require_actor(context)
    account_id = read_string(params, "account_id", "accountId")
    if account_id is None:
        raise ToolDriverError("unexpected_error", "account_id is required.")
    _ensure_account(conn, account_id)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE workbench_account SET status = 'disabled', updated_at = now() WHERE id = %s",
            (account_id,),
        )
    insert_audit(
        conn,
        profile=context.profile,
        account_id=actor,
        action="disable_account",
        target_type="account",
        target_id=account_id,
        details={},
    )
    return {
        "account_id": account_id,
        "disabled": True,
        "account": _account_row(conn, account_id),
    }


def account_handlers() -> dict[str, dict[str, Any]]:
    """Registry fragment for the workbench-admin datastore tool."""
    return {
        "toee_workbench_admin": {
            "list_accounts": _list_accounts,
            "create_account": _create_account,
            "update_account_role": _update_account_role,
            "disable_account": _disable_account,
        }
    }
