"""Datastore handlers for ``toee_workbench_admin`` (ADR-0069/0089).

Workbench account administration is a Supervisor Admin governance surface, so
every mutation appends a Workbench Audit Log row in the same transaction. Reads
never return ``password_hash``.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import TYPE_CHECKING, Any

from psycopg.rows import dict_row

from toee_hermes.errors import ToolDriverError

from ._common import insert_audit, new_id, read_string, serialize_row

# scrypt KDF parameters — must match the workbench TS hashPassword (Node
# scryptSync defaults) so a hash written by the BFF verifies here (ADR-0144).
_SCRYPT_N = 16384
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_MAXMEM = 64 * 1024 * 1024

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
            "SELECT id, username, role, status, created_at, updated_at, last_login_at"
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
            SELECT id, username, role, status, created_at, updated_at, last_login_at
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


def _verify_password(plain: str, stored: str) -> bool:
    """Constant-time scrypt verify of ``plain`` against a stored ``scrypt$salt$hash``.

    Mirrors the workbench TS ``verifyPassword`` exactly (same format, same scrypt
    params, same length-checked timing-safe compare) so a hash written by either
    runtime verifies in the other. A malformed stored hash returns False rather
    than raising, so a corrupt row is a failed login, never a 502.
    """
    parts = stored.split("$")
    if len(parts) != 3:
        return False
    scheme, salt_hex, hash_hex = parts
    if scheme != "scrypt" or not salt_hex or not hash_hex:
        return False
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    if not salt or not expected:
        return False
    try:
        actual = hashlib.scrypt(
            plain.encode("utf-8"),
            salt=salt,
            n=_SCRYPT_N,
            r=_SCRYPT_R,
            p=_SCRYPT_P,
            dklen=len(expected),
            maxmem=_SCRYPT_MAXMEM,
        )
    except (ValueError, OverflowError):  # pragma: no cover - defensive on bad params
        return False
    return hmac.compare_digest(actual, expected)


def _authenticate(conn, params: dict[str, Any], context: "ToolExecutionContext") -> Any:
    """Pre-auth login verification for the workbench login path (ADR-0144).

    Reads the stored scrypt hash, verifies it server-side, and on success returns
    the public account (``_account_row`` — NEVER the hash) while recording
    ``last_login_at`` in the same transaction (resolves M-1). This is *pre-auth*:
    no acting account exists yet, so it does NOT call :func:`_require_actor` — it
    establishes the actor. Unknown user and bad password raise the SAME governed
    ``unauthenticated`` (BFF -> 401) so neither leaks which (in-memory parity); a
    disabled account is blocked *before* the password check (``policy_blocked`` ->
    403), matching the in-memory order. The handler never returns or logs the hash.
    """
    username = read_string(params, "username")
    password = params.get("password")
    if username is None or not isinstance(password, str) or not password:
        # A malformed attempt is still a credential failure, not a 502, and stays
        # indistinguishable from a wrong password (no shape/word leak).
        raise ToolDriverError("unauthenticated", "invalid credentials.")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id, status, password_hash FROM workbench_account WHERE username = %s",
            (username,),
        )
        row = cur.fetchone()
    if row is None:
        raise ToolDriverError("unauthenticated", "invalid credentials.")
    if row["status"] == "disabled":
        raise ToolDriverError("policy_blocked", "account disabled.")
    if not _verify_password(password, row["password_hash"]):
        raise ToolDriverError("unauthenticated", "invalid credentials.")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE workbench_account SET last_login_at = now() WHERE id = %s",
            (row["id"],),
        )
    return {"account": _account_row(conn, row["id"])}


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
            "authenticate": _authenticate,
        }
    }
