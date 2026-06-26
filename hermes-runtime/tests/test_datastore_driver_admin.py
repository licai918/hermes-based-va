"""Slice 33 / #36: Postgres-backed Supervisor Admin governance tools.

Covers ``toee_workbench_admin`` (accounts, ADR-0069/0089), ``toee_knowledge_ops``
(policy-slot versions, ADR-0003/0040), and ``toee_eval_review`` (eval runs,
ADR-0074/0088) doing real CRUD with governance audit writes. Skip-if-no-DB.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext

# A real scrypt hash produced by the workbench TS ``hashPassword`` (Node
# ``scryptSync`` defaults: N=16384, r=8, p=1, 64-byte key) for ``TS_HASH_PASSWORD``.
# Pins the Python verify (``hashlib.scrypt``) against the TS hasher so the two
# cannot silently drift (ADR-0144 cross-runtime hash compatibility).
TS_HASH_PASSWORD = "Workbench123!"
TS_GENERATED_HASH = (
    "scrypt$60c8747ae0e3f7c886acbe7ab039fa86$"
    "92025de04d801fded8382fbfae1e0eaa0bebea5b04e0a1057c582980c01e538c"
    "2615ebb5332bac5d1cbe0d9cc59bebc603c921dc9d8e36ed3501db742a4fc7a8"
)


def _scrypt_hash(plain: str, salt: bytes = b"\x01" * 16) -> str:
    """A workbench-format ``scrypt$saltHex$hashHex`` using the TS hashPassword
    parameters, so the handler verifies it exactly as it would a real one."""
    derived = hashlib.scrypt(
        plain.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=64,
        maxmem=64 * 1024 * 1024,
    )
    return f"scrypt${salt.hex()}${derived.hex()}"


def _run(driver, tool, action, params, user_id="acct_admin"):
    return execute_tool(
        tool=tool,
        action=action,
        params=params,
        context=ToolExecutionContext(profile="supervisor_admin", user_id=user_id),
        driver=driver,
    )


def _audit_actions(conn, target_type, target_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT action FROM workbench_audit_log WHERE target_type = %s AND target_id = %s",
            (target_type, target_id),
        )
        return [r[0] for r in cur.fetchall()]


def _audit_actor(conn, target_type, target_id, action):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT account_id FROM workbench_audit_log"
            " WHERE target_type = %s AND target_id = %s AND action = %s",
            (target_type, target_id, action),
        )
        row = cur.fetchone()
    return row[0] if row else None


# --- accounts ---------------------------------------------------------------


def test_account_crud_with_audit(datastore) -> None:
    driver, conn, _ = datastore
    created = _run(
        driver, "toee_workbench_admin", "create_account",
        {"username": "rep1", "password_hash": "hash", "role": "customer_service_rep"},
    )
    assert created.ok
    assert created.data["created"] is True
    account_id = created.data["account_id"]
    # The mutation returns the fresh account read model so the BFF renders it
    # without a second round-trip (store-path parity); the password hash never
    # rides that row.
    acct = created.data["account"]
    assert acct["account_id"] == account_id
    assert acct["username"] == "rep1"
    assert acct["role"] == "customer_service_rep"
    assert acct["status"] == "active"
    assert "password_hash" not in acct

    listed = _run(driver, "toee_workbench_admin", "list_accounts", {})
    assert any(a["username"] == "rep1" for a in listed.data["accounts"])
    # password hashes never leave the datastore handler.
    assert all("password_hash" not in a for a in listed.data["accounts"])

    updated = _run(
        driver, "toee_workbench_admin", "update_account_role",
        {"account_id": account_id, "role": "supervisor_admin"},
    )
    assert updated.data["role"] == "supervisor_admin"
    assert updated.data["account"]["role"] == "supervisor_admin"

    disabled = _run(
        driver, "toee_workbench_admin", "disable_account", {"account_id": account_id}
    )
    assert disabled.data["disabled"] is True
    assert disabled.data["account"]["status"] == "disabled"

    row = next(
        a for a in _run(driver, "toee_workbench_admin", "list_accounts", {}).data["accounts"]
        if a["id"] == account_id
    )
    assert row["role"] == "supervisor_admin"
    assert row["status"] == "disabled"

    actions = _audit_actions(conn, "account", account_id)
    assert "create_account" in actions
    assert "update_account_role" in actions
    assert "disable_account" in actions
    # Audit is attributed to the acting account (ADR-0029/0141), not NULL.
    assert _audit_actor(conn, "account", account_id, "create_account") == "acct_admin"
    assert _audit_actor(conn, "account", account_id, "disable_account") == "acct_admin"


def test_create_account_requires_fields(datastore) -> None:
    driver, _, _ = datastore
    result = _run(driver, "toee_workbench_admin", "create_account", {"role": "r"})
    assert not result.ok
    assert result.error_class == "unexpected_error"


def test_duplicate_username_is_governed(datastore) -> None:
    # Uniqueness is enforced atomically in SQL (ON CONFLICT), so a duplicate
    # username is a governed `conflict` (BFF maps to 409, store-path parity), not a
    # raw unique-violation surfaced as unexpected_error.
    driver, conn, _ = datastore
    name = f"dup_{uuid.uuid4().hex[:6]}"
    first = _run(
        driver, "toee_workbench_admin", "create_account",
        {"username": name, "password_hash": "h", "role": "r"},
    )
    assert first.ok
    second = _run(
        driver, "toee_workbench_admin", "create_account",
        {"username": name, "password_hash": "h2", "role": "r"},
    )
    assert not second.ok
    assert second.error_class == "conflict"
    # The rejected create left exactly one account + one create_account audit row.
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM workbench_account WHERE username = %s", (name,))
        assert cur.fetchone()[0] == 1
        cur.execute(
            "SELECT count(*) FROM workbench_audit_log WHERE action = 'create_account'"
            " AND target_id = %s",
            (first.data["account_id"],),
        )
        assert cur.fetchone()[0] == 1


def test_account_writes_require_actor(datastore) -> None:
    # I1 (ADR-0141 fail-closed actor): a governed admin write with NO actor is a
    # governed denial — no row, no NULL-actor audit — never a silent success. Every
    # admin mutation (create/update/disable) is guarded at this one boundary.
    driver, conn, _ = datastore
    res = _run(
        driver, "toee_workbench_admin", "create_account",
        {"username": "ghostmaker", "password_hash": "h", "role": "customer_service_rep"},
        user_id=None,
    )
    assert not res.ok
    assert res.error_class == "policy_blocked"
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM workbench_account WHERE username = %s", ("ghostmaker",))
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM workbench_audit_log WHERE action = 'create_account'")
        assert cur.fetchone()[0] == 0

    # An account created *with* an actor is the target for the update/disable checks.
    account_id = _run(
        driver, "toee_workbench_admin", "create_account",
        {"username": "realacct", "password_hash": "h", "role": "customer_service_rep"},
    ).data["account_id"]

    upd = _run(
        driver, "toee_workbench_admin", "update_account_role",
        {"account_id": account_id, "role": "workbench_admin"}, user_id=None,
    )
    assert not upd.ok
    assert upd.error_class == "policy_blocked"
    dis = _run(
        driver, "toee_workbench_admin", "disable_account",
        {"account_id": account_id}, user_id=None,
    )
    assert not dis.ok
    assert dis.error_class == "policy_blocked"
    # The denied actor-less writes mutated nothing and wrote no audit row: the
    # account keeps its created role + active status, and only create_account logged.
    assert _audit_actions(conn, "account", account_id) == ["create_account"]
    row = next(
        a for a in _run(driver, "toee_workbench_admin", "list_accounts", {}).data["accounts"]
        if a["id"] == account_id
    )
    assert row["role"] == "customer_service_rep"
    assert row["status"] == "active"


def test_update_or_disable_missing_account_is_not_found(datastore) -> None:
    # A governed write against a missing account is a governed not_found (BFF maps
    # to 404, store-path "account not found" parity), not an unexpected_error 502.
    driver, _, _ = datastore
    upd = _run(
        driver, "toee_workbench_admin", "update_account_role",
        {"account_id": "acct_ghost", "role": "workbench_admin"},
    )
    assert not upd.ok
    assert upd.error_class == "not_found"
    dis = _run(
        driver, "toee_workbench_admin", "disable_account", {"account_id": "acct_ghost"}
    )
    assert not dis.ok
    assert dis.error_class == "not_found"


# --- authenticate (login cutover, ADR-0144) ---------------------------------


def _last_login(conn, account_id: str):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT last_login_at FROM workbench_account WHERE id = %s", (account_id,)
        )
        row = cur.fetchone()
    return row[0] if row else None


def _seed_account(driver, username, password, role="customer_service_rep", disabled=False):
    created = _run(
        driver, "toee_workbench_admin", "create_account",
        {"username": username, "password_hash": _scrypt_hash(password), "role": role},
    )
    account_id = created.data["account_id"]
    if disabled:
        _run(driver, "toee_workbench_admin", "disable_account", {"account_id": account_id})
    return account_id


def test_authenticate_valid_credentials_returns_public_account_and_records_last_login(
    datastore,
) -> None:
    driver, conn, _ = datastore
    account_id = _seed_account(driver, "loginrep", "CorrectHorse9!")
    assert _last_login(conn, account_id) is None  # never logged in yet

    result = _run(
        driver, "toee_workbench_admin", "authenticate",
        {"username": "loginrep", "password": "CorrectHorse9!"},
    )
    assert result.ok
    acct = result.data["account"]
    assert acct["account_id"] == account_id
    assert acct["username"] == "loginrep"
    assert acct["role"] == "customer_service_rep"
    assert acct["status"] == "active"
    # The stored hash NEVER rides the authenticate result.
    assert "password_hash" not in acct
    assert "password" not in result.data
    # Success records last_login_at (resolves M-1) in the same transaction.
    assert acct["last_login_at"] is not None
    assert _last_login(conn, account_id) is not None


def test_authenticate_bad_password_is_generic_unauthenticated_and_leaves_last_login(
    datastore,
) -> None:
    driver, conn, _ = datastore
    account_id = _seed_account(driver, "loginrep2", "CorrectHorse9!")
    result = _run(
        driver, "toee_workbench_admin", "authenticate",
        {"username": "loginrep2", "password": "wrong-password"},
    )
    assert not result.ok
    assert result.error_class == "unauthenticated"
    # A rejected login does not touch last_login_at (the handler raised -> rollback).
    assert _last_login(conn, account_id) is None


def test_authenticate_unknown_user_is_the_same_generic_failure(datastore) -> None:
    # No user-enumeration: an unknown username returns the SAME class as a bad
    # password, so neither status nor body leaks which (in-memory 401 parity).
    driver, _, _ = datastore
    result = _run(
        driver, "toee_workbench_admin", "authenticate",
        {"username": "nobody-here", "password": "whatever-Pass1!"},
    )
    assert not result.ok
    assert result.error_class == "unauthenticated"


def test_authenticate_disabled_account_is_policy_blocked_even_with_right_password(
    datastore,
) -> None:
    # Disabled is checked before the password (in-memory order) and blocks login;
    # the BFF maps policy_blocked -> 403 "account disabled".
    driver, _, _ = datastore
    _seed_account(driver, "gone", "CorrectHorse9!", disabled=True)
    result = _run(
        driver, "toee_workbench_admin", "authenticate",
        {"username": "gone", "password": "CorrectHorse9!"},
    )
    assert not result.ok
    assert result.error_class == "policy_blocked"


def test_authenticate_needs_no_actor_it_establishes_one(datastore) -> None:
    # Pre-auth: no acting account exists yet, so authenticate is fail-open on actor
    # (unlike the governed admin writes); it must succeed with user_id=None.
    driver, _, _ = datastore
    _seed_account(driver, "preauth", "CorrectHorse9!")
    result = _run(
        driver, "toee_workbench_admin", "authenticate",
        {"username": "preauth", "password": "CorrectHorse9!"},
        user_id=None,
    )
    assert result.ok
    assert result.data["account"]["username"] == "preauth"


def test_authenticate_accepts_a_typescript_generated_hash(datastore) -> None:
    # Cross-runtime guard (ADR-0144): a hash produced by the TS hashPassword must
    # verify in Python, or login would reject every real account.
    driver, _, _ = datastore
    _run(
        driver, "toee_workbench_admin", "create_account",
        {"username": "tsuser", "password_hash": TS_GENERATED_HASH, "role": "customer_service_rep"},
    )
    result = _run(
        driver, "toee_workbench_admin", "authenticate",
        {"username": "tsuser", "password": TS_HASH_PASSWORD},
    )
    assert result.ok
    assert result.data["account"]["username"] == "tsuser"


def test_authenticate_never_writes_an_audit_row_or_leaks_the_hash(datastore) -> None:
    # Login is recorded by last_login_at, not a governed audit row (in-memory
    # parity), and the stored hash appears nowhere in the result or the audit log.
    driver, conn, _ = datastore
    stored_hash = _scrypt_hash("CorrectHorse9!")
    created = _run(
        driver, "toee_workbench_admin", "create_account",
        {"username": "audituser", "password_hash": stored_hash, "role": "customer_service_rep"},
    )
    account_id = created.data["account_id"]
    result = _run(
        driver, "toee_workbench_admin", "authenticate",
        {"username": "audituser", "password": "CorrectHorse9!"},
    )
    assert result.ok
    assert stored_hash not in json.dumps(result.data)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM workbench_audit_log WHERE action = 'authenticate'"
        )
        assert cur.fetchone()[0] == 0
        # Only the create_account audit exists; authenticate writes none.
        cur.execute(
            "SELECT count(*) FROM workbench_audit_log WHERE target_id = %s", (account_id,)
        )
        assert cur.fetchone()[0] == 1


# --- knowledge ops (ADR-0145 authoring table) ------------------------------


def _seed_published_history(conn, slot_id, published_text):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO workbench_policy_slot_history (id, slot_id, published_text)"
            " VALUES (%s, %s, %s)",
            (f"pshist_{uuid.uuid4().hex}", slot_id, published_text),
        )
    conn.commit()


def test_policy_slots_lists_six_kebab_placeholders_in_order(datastore) -> None:
    driver, _, _ = datastore
    # listSlots() parity: the six Required Operational Policy Slots (ADR-0003) keyed
    # by the kebab UI ids the store uses, in the fixed list order, empty at onboarding.
    slots = _run(driver, "toee_knowledge_ops", "get_policy_slots", {}).data["slots"]
    assert [s["slot_id"] for s in slots] == [
        "business-hours",
        "payment-methods",
        "order-delivery",
        "accounting-inquiry",
        "returns-exchanges",
        "exception-scripts",
    ]
    assert all(s["status"] == "empty" for s in slots)
    # The full PolicySlot read model is projected (no leaked columns).
    assert set(slots[0]) == {
        "slot_id", "title", "status", "draft_text", "published_text",
        "owner", "review_date", "has_gap_prompt",
    }


def test_save_draft_sets_text_and_flips_empty_to_draft(datastore) -> None:
    driver, conn, _ = datastore
    res = _run(
        driver, "toee_knowledge_ops", "update_policy_slot",
        {"slot_id": "returns-exchanges", "draft_text": "Returns within 30 days.", "owner": "ops"},
    )
    slot = res.data["slot"]
    assert slot["status"] == "draft"
    assert slot["draft_text"] == "Returns within 30 days."
    assert slot["owner"] == "ops"
    # Governed write -> actor-attributed audit (the store lacked this; ADR-0145).
    assert _audit_actor(conn, "policy_slot", "returns-exchanges", "update_policy_slot") == "acct_admin"


def test_save_draft_unknown_slot_is_not_found(datastore) -> None:
    driver, _, _ = datastore
    result = _run(
        driver, "toee_knowledge_ops", "update_policy_slot",
        {"slot_id": "ghost-slot", "draft_text": "x"},
    )
    assert not result.ok
    assert result.error_class == "not_found"


def test_save_draft_without_actor_is_denied_no_mutation(datastore) -> None:
    # I1 parity on the knowledge surface: no attributed actor -> policy_blocked, no
    # mutation, no NULL-actor audit row.
    driver, conn, _ = datastore
    result = _run(
        driver, "toee_knowledge_ops", "update_policy_slot",
        {"slot_id": "order-delivery", "draft_text": "should not persist"},
        user_id="",
    )
    assert not result.ok
    assert result.error_class == "policy_blocked"
    slots = _run(driver, "toee_knowledge_ops", "get_policy_slots", {}).data["slots"]
    order = next(s for s in slots if s["slot_id"] == "order-delivery")
    assert order["status"] == "empty"
    assert order["draft_text"] is None
    assert _audit_actions(conn, "policy_slot", "order-delivery") == []


def test_submit_for_eval_pending_then_conflict_and_not_found(datastore) -> None:
    driver, conn, _ = datastore
    _run(
        driver, "toee_knowledge_ops", "update_policy_slot",
        {"slot_id": "order-delivery", "draft_text": "Confirm order number first."},
    )
    submitted = _run(driver, "toee_knowledge_ops", "submit_for_eval", {"slot_id": "order-delivery"})
    assert submitted.data["slot"]["status"] == "pending_eval"
    assert _audit_actor(conn, "policy_slot", "order-delivery", "submit_for_eval") == "acct_admin"

    # A known slot with no draft -> conflict (409), not not_found (store parity).
    no_draft = _run(driver, "toee_knowledge_ops", "submit_for_eval", {"slot_id": "returns-exchanges"})
    assert no_draft.error_class == "conflict"
    # An unknown slot -> not_found (404).
    unknown = _run(driver, "toee_knowledge_ops", "submit_for_eval", {"slot_id": "ghost-slot"})
    assert unknown.error_class == "not_found"


def test_rollback_no_previous_is_conflict_and_unknown_is_not_found(datastore) -> None:
    driver, _, _ = datastore
    # Fresh slot: no published history -> conflict (409).
    no_prev = _run(driver, "toee_knowledge_ops", "rollback_published_policy", {"slot_id": "payment-methods"})
    assert no_prev.error_class == "conflict"
    unknown = _run(driver, "toee_knowledge_ops", "rollback_published_policy", {"slot_id": "ghost-slot"})
    assert unknown.error_class == "not_found"


def test_rollback_restores_previous_published_text(datastore) -> None:
    driver, conn, _ = datastore
    _seed_published_history(conn, "business-hours", "Open Mon-Fri 9am-5pm.")
    res = _run(driver, "toee_knowledge_ops", "rollback_published_policy", {"slot_id": "business-hours"})
    slot = res.data["slot"]
    assert slot["status"] == "published"
    assert slot["published_text"] == "Open Mon-Fri 9am-5pm."
    assert _audit_actor(conn, "policy_slot", "business-hours", "rollback_published_policy") == "acct_admin"
    # The history entry was popped: a second rollback now finds nothing.
    again = _run(driver, "toee_knowledge_ops", "rollback_published_policy", {"slot_id": "business-hours"})
    assert again.error_class == "conflict"


# --- eval review (ADR-0146 Postgres cutover; EvalStore parity) -------------


def _eval_report(
    run_id, *, suite, failed_high=0, failed_medium=0, signoff_required=False,
    timestamp="2026-06-01T00:00:00Z",
):
    # The on-disk ADR-0074 report shape the EvalStore (source of truth) projects.
    total = 1 + failed_high + failed_medium
    return {
        "run_id": run_id,
        "suite": suite,
        "model_slug": "deepseek/deepseek-v4-pro",
        "prompt_version": "persona-v1",
        "knowledge_version": "kb-v1",
        "timestamp": timestamp,
        "scenarios": [],
        "summary": {
            "total": total, "passed": total - failed_high - failed_medium,
            "failed_high": failed_high, "failed_medium": failed_medium,
        },
        "signoff_required": signoff_required,
    }


def _seed_eval_run(
    conn, run_id, *, suite="text_first_launch", failed_high=0, failed_medium=0,
    signoff_required=False, signed_off=False, slot_key=None,
    timestamp="2026-06-01T00:00:00Z",
):
    from psycopg.types.json import Jsonb

    report = _eval_report(
        run_id, suite=suite, failed_high=failed_high, failed_medium=failed_medium,
        signoff_required=signoff_required, timestamp=timestamp,
    )
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO eval_run"
            " (id, suite, status, failed_high, report, signed_off, slot_key)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (run_id, suite, "recorded", failed_high, Jsonb(report), signed_off, slot_key),
        )
    conn.commit()


def _eval_slot(driver, slot_id):
    slots = _run(driver, "toee_knowledge_ops", "get_policy_slots", {}).data["slots"]
    return next(s for s in slots if s["slot_id"] == slot_id)


def test_eval_runs_list_is_most_recent_first_with_summary_projection(datastore) -> None:
    # listRuns parity: most-recent-first (timestamp desc), the compact summary read
    # model, passed = no high AND no medium failures.
    driver, conn, _ = datastore
    _seed_eval_run(conn, "r-old", timestamp="2026-06-01T00:00:00Z")
    _seed_eval_run(
        conn, "r-new", suite="policy_publish", failed_medium=1, signoff_required=True,
        timestamp="2026-06-03T00:00:00Z",
    )
    runs = _run(driver, "toee_eval_review", "list_eval_runs", {}).data["runs"]
    ids = [r["run_id"] for r in runs]
    assert ids.index("r-new") < ids.index("r-old")  # most recent first
    new = next(r for r in runs if r["run_id"] == "r-new")
    assert new["passed"] is False  # one medium failure
    assert new["failed_medium"] == 1
    old = next(r for r in runs if r["run_id"] == "r-old")
    assert old["passed"] is True
    assert set(new) == {
        "run_id", "suite", "timestamp", "passed", "failed_high", "failed_medium",
        "knowledge_version", "prompt_version",
    }


def test_get_eval_run_returns_full_report_with_overlay_and_404s_unknown(datastore) -> None:
    driver, conn, _ = datastore
    _seed_eval_run(conn, "r1", suite="policy_publish")
    run = _run(driver, "toee_eval_review", "get_eval_run", {"run_id": "r1"}).data["run"]
    assert run["run_id"] == "r1"
    assert run["suite"] == "policy_publish"
    assert run["summary"]["failed_high"] == 0
    # The governance overlay rides the report (not part of the on-disk shape).
    assert run["signed_off"] is False
    assert run["promoted"] is False
    unknown = _run(driver, "toee_eval_review", "get_eval_run", {"run_id": "ghost"})
    assert not unknown.ok
    assert unknown.error_class == "not_found"


def test_sign_off_medium_run_reflects_overlay_with_audit(datastore) -> None:
    driver, conn, _ = datastore
    _seed_eval_run(conn, "pp1", suite="policy_publish", failed_medium=1, signoff_required=True)
    res = _run(driver, "toee_eval_review", "sign_off_medium_failure", {"run_id": "pp1"})
    assert res.data["run"]["signed_off"] is True
    assert _audit_actor(conn, "eval_run", "pp1", "sign_off_medium_failure") == "acct_admin"
    # Reflected on a subsequent read, and idempotent (re-sign-off still succeeds).
    again = _run(driver, "toee_eval_review", "sign_off_medium_failure", {"run_id": "pp1"})
    assert again.data["run"]["signed_off"] is True


def test_sign_off_refuses_not_required_failed_high_and_not_found(datastore) -> None:
    driver, conn, _ = datastore
    _seed_eval_run(conn, "clean", signoff_required=False)
    _seed_eval_run(conn, "high", failed_high=1, signoff_required=True)
    not_required = _run(driver, "toee_eval_review", "sign_off_medium_failure", {"run_id": "clean"})
    assert not_required.error_class == "conflict"  # no medium sign-off required (409)
    failed_high = _run(driver, "toee_eval_review", "sign_off_medium_failure", {"run_id": "high"})
    assert failed_high.error_class == "conflict"  # high-severity blocks sign-off (409)
    not_found = _run(driver, "toee_eval_review", "sign_off_medium_failure", {"run_id": "ghost"})
    assert not_found.error_class == "not_found"


def test_sign_off_without_actor_is_denied_no_mutation(datastore) -> None:
    # I1 parity on the eval surface: no attributed actor -> policy_blocked, the run
    # stays not-signed-off and no NULL-actor audit row is written.
    driver, conn, _ = datastore
    _seed_eval_run(conn, "pp1", suite="policy_publish", failed_medium=1, signoff_required=True)
    res = _run(
        driver, "toee_eval_review", "sign_off_medium_failure", {"run_id": "pp1"}, user_id=""
    )
    assert res.error_class == "policy_blocked"
    assert _run(
        driver, "toee_eval_review", "get_eval_run", {"run_id": "pp1"}
    ).data["run"]["signed_off"] is False
    assert _audit_actions(conn, "eval_run", "pp1") == []


def test_promote_refuses_non_policy_publish_failed_high_and_not_found(datastore) -> None:
    driver, conn, _ = datastore
    _seed_eval_run(conn, "tfl", suite="text_first_launch")
    _seed_eval_run(conn, "high", suite="policy_publish", failed_high=1)
    not_promotable = _run(driver, "toee_eval_review", "promote_pending_policy", {"run_id": "tfl"})
    assert not_promotable.error_class == "conflict"  # not a promotable policy_publish run
    failed_high = _run(driver, "toee_eval_review", "promote_pending_policy", {"run_id": "high"})
    assert failed_high.error_class == "conflict"  # high-severity blocks promotion
    not_found = _run(driver, "toee_eval_review", "promote_pending_policy", {"run_id": "ghost"})
    assert not_found.error_class == "not_found"


def test_promote_blocks_until_signed_off_then_promotes_overlapping(datastore) -> None:
    # promotePending parity: a medium policy_publish run is blocked until signed off,
    # then promotes; signed_off and promoted are OVERLAPPING (both true after).
    driver, conn, _ = datastore
    _seed_eval_run(conn, "pp1", suite="policy_publish", failed_medium=1, signoff_required=True)
    blocked = _run(driver, "toee_eval_review", "promote_pending_policy", {"run_id": "pp1"})
    assert blocked.error_class == "conflict"  # medium must be signed off first
    _run(driver, "toee_eval_review", "sign_off_medium_failure", {"run_id": "pp1"})
    promoted = _run(driver, "toee_eval_review", "promote_pending_policy", {"run_id": "pp1"})
    assert promoted.data["run"]["promoted"] is True
    assert promoted.data["run"]["signed_off"] is True
    assert _audit_actor(conn, "eval_run", "pp1", "promote_pending_policy") == "acct_admin"
    # Idempotent: re-promote of an already-promoted run still succeeds.
    assert _run(
        driver, "toee_eval_review", "promote_pending_policy", {"run_id": "pp1"}
    ).data["run"]["promoted"] is True


def test_promote_without_actor_is_denied_no_mutation(datastore) -> None:
    driver, conn, _ = datastore
    _seed_eval_run(conn, "pp1", suite="policy_publish")
    res = _run(
        driver, "toee_eval_review", "promote_pending_policy", {"run_id": "pp1"}, user_id=""
    )
    assert res.error_class == "policy_blocked"
    assert _run(
        driver, "toee_eval_review", "get_eval_run", {"run_id": "pp1"}
    ).data["run"]["promoted"] is False
    assert _audit_actions(conn, "eval_run", "pp1") == []


def test_promote_publishes_authoring_slot_and_enables_rollback(datastore) -> None:
    # ADR-0146 publish bridge (closes ADR-0145 divergence #2): a real authoring
    # submit -> recorded policy_publish run -> promote PUBLISHES the kebab authoring
    # slot, and a second cycle pushes the prior published text onto history so a
    # later rollback restores it. The knowledge increment could not test this -- the
    # publish path was decoupled, so rollback always 409'd on a fresh DB.
    driver, conn, _ = datastore

    # v1: author + submit business-hours (kebab); record a clean policy_publish run
    # gating it (snake slot_key); promote -> publishes v1 onto workbench_policy_slot.
    _run(
        driver, "toee_knowledge_ops", "update_policy_slot",
        {"slot_id": "business-hours", "draft_text": "v1 hours"},
    )
    _run(driver, "toee_knowledge_ops", "submit_for_eval", {"slot_id": "business-hours"})
    _seed_eval_run(conn, "pp-v1", suite="policy_publish", slot_key="business_hours_service_boundaries")
    promoted = _run(driver, "toee_eval_review", "promote_pending_policy", {"run_id": "pp-v1"})
    assert promoted.data["run"]["promoted"] is True
    slot = _eval_slot(driver, "business-hours")
    assert slot["status"] == "published"
    assert slot["published_text"] == "v1 hours"
    # Only one publish so far -> no prior version on history -> rollback conflicts.
    assert _run(
        driver, "toee_knowledge_ops", "rollback_published_policy", {"slot_id": "business-hours"}
    ).error_class == "conflict"

    # v2: author + submit + record + promote -> pushes v1 to history, publishes v2.
    _run(
        driver, "toee_knowledge_ops", "update_policy_slot",
        {"slot_id": "business-hours", "draft_text": "v2 hours"},
    )
    _run(driver, "toee_knowledge_ops", "submit_for_eval", {"slot_id": "business-hours"})
    _seed_eval_run(conn, "pp-v2", suite="policy_publish", slot_key="business_hours_service_boundaries")
    _run(driver, "toee_eval_review", "promote_pending_policy", {"run_id": "pp-v2"})
    assert _eval_slot(driver, "business-hours")["published_text"] == "v2 hours"

    # Rollback now restores v1 from the history the publish bridge populated.
    rolled = _run(
        driver, "toee_knowledge_ops", "rollback_published_policy", {"slot_id": "business-hours"}
    )
    assert rolled.data["slot"]["status"] == "published"
    assert rolled.data["slot"]["published_text"] == "v1 hours"


def test_promote_policy_publish_without_slot_key_marks_run_only(datastore) -> None:
    # A policy_publish run with no slot_key promotes (run marked) but publishes
    # nothing -- the bridge engages only when the authoring link exists (ADR-0146
    # divergence #2). No authoring slot is touched.
    driver, conn, _ = datastore
    _seed_eval_run(conn, "pp-nolink", suite="policy_publish")
    promoted = _run(driver, "toee_eval_review", "promote_pending_policy", {"run_id": "pp-nolink"})
    assert promoted.data["run"]["promoted"] is True
    assert all(s["status"] == "empty" for s in
               _run(driver, "toee_knowledge_ops", "get_policy_slots", {}).data["slots"])
