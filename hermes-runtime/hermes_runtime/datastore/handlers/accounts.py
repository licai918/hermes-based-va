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

# ADR-0018 lockout ladder, moved here in 0.0.4 S08 (FR-2). These MUST stay equal to
# MAX_FAILED_ATTEMPTS / LOCKOUT_MS in apps/workbench/lib/auth/account-store.ts until
# S09 deletes that file, after which this is the only definition of the policy.
_MAX_FAILED_ATTEMPTS = 5
_LOCKOUT_MINUTES = 15

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


def _record_failed_login(conn, account_id: str) -> None:
    """Advance the ADR-0018 failure ladder and commit it before the caller raises.

    Two things are load-bearing here:

    * **The commit.** :meth:`PostgresDriver.execute` rolls back on a
      ``ToolDriverError``, and a rejected login always raises — so an increment
      left to the driver's commit would vanish and five wrong passwords would
      count as zero, silently disabling lockout. This owns its unit of work; the
      driver's subsequent rollback then finds an empty transaction.
    * **The single statement.** ``failed_attempts + 1`` is evaluated by Postgres
      against the row it locks, so concurrent wrong passwords cannot both read
      the same count and write the same increment (a read-then-write in Python
      would let an attacker outrun the ladder).

    Crossing the threshold opens the window and resets the counter to 0, exactly
    as ``account-store.ts`` ``recordFailedLogin`` does.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE workbench_account SET
                failed_attempts = CASE WHEN failed_attempts + 1 >= %(max)s
                                       THEN 0 ELSE failed_attempts + 1 END,
                locked_until    = CASE WHEN failed_attempts + 1 >= %(max)s
                                       THEN now() + make_interval(mins => %(mins)s)
                                       ELSE locked_until END
            WHERE id = %(id)s
            """,
            {"max": _MAX_FAILED_ATTEMPTS, "mins": _LOCKOUT_MINUTES, "id": account_id},
        )
    conn.commit()


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

    Since 0.0.4 S08 this is also the *only* enforcement point for the ADR-0018
    lockout ladder (FR-2): disabled -> locked -> password, five consecutive
    failures open a 15-minute window (``locked`` -> 423), and a success clears both
    the counter and the window. The wall clock is always the database's ``now()``,
    never a caller-supplied timestamp — a client-controlled clock would let an
    attacker date their way out of a lockout.
    """
    username = read_string(params, "username")
    password = params.get("password")
    if username is None or not isinstance(password, str) or not password:
        # A malformed attempt is still a credential failure, not a 502, and stays
        # indistinguishable from a wrong password (no shape/word leak).
        raise ToolDriverError("unauthenticated", "invalid credentials.")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id, status, password_hash, locked_until > now() AS locked"
            " FROM workbench_account WHERE username = %s",
            (username,),
        )
        row = cur.fetchone()
    if row is None:
        raise ToolDriverError("unauthenticated", "invalid credentials.")
    if row["status"] == "disabled":
        raise ToolDriverError("policy_blocked", "account disabled.")
    if row["locked"]:
        # Checked BEFORE the password, matching the in-memory order: the correct
        # password does not rescue a locked account, and the attempt returns here
        # without touching the ladder, so a locked-out attacker cannot slide the
        # window forward. NULL locked_until compares to NULL -> falsy -> not locked,
        # and so does an elapsed window, which is why expiry needs no sweep job.
        raise ToolDriverError("locked", "account temporarily locked.")
    if not _verify_password(password, row["password_hash"]):
        _record_failed_login(conn, row["id"])
        raise ToolDriverError("unauthenticated", "invalid credentials.")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE workbench_account SET last_login_at = now(), failed_attempts = 0,"
            " locked_until = NULL WHERE id = %s",
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
