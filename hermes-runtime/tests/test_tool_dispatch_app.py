"""Per-profile tool-dispatch HTTP API (ADR-0141).

The deterministic half of the per-profile Hermes surface the workbench BFF calls:
``POST /v1/tools:dispatch`` runs the same governed ``execute_tool`` the channel
pipeline uses — no LLM — under one fixed profile. Bearer auth gates the route; the
Profile Tool Allowlist (ADR-0034/0035/0038) is enforced as a Tool Gate, so a tool
outside the profile comes back as a governed ``{"error": ...}`` (ADR-0020), never a
raised exception. Tool Gate denials are HTTP 200 governed JSON; only auth/shape
problems are 4xx.
"""

from __future__ import annotations

from starlette.testclient import TestClient

from hermes_runtime.tool_dispatch_app import create_tool_dispatch_app

API_TOKEN = "test-copilot-api-token"


def _client(profile: str = "internal_copilot") -> TestClient:
    return TestClient(create_tool_dispatch_app(api_token=API_TOKEN, profile=profile))


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_TOKEN}"}


class _CapturingDriver:
    """Records the ToolExecutionContext the dispatch app builds for execute_tool."""

    kind = "mock"

    def __init__(self) -> None:
        self.context = None

    def execute(self, request, context):  # noqa: ANN001 (ToolDriver signature)
        self.context = context
        return {"ok": True}


def _client_with_driver(driver, profile: str = "internal_copilot", store=None) -> TestClient:
    return TestClient(
        create_tool_dispatch_app(
            api_token=API_TOKEN, profile=profile, driver=driver, store=store
        )
    )


def test_healthz_returns_ok() -> None:
    response = _client().get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dispatch_requires_bearer_token() -> None:
    # No Authorization header → 401; the tool never runs (fail-closed, ADR-0106).
    response = _client().post(
        "/v1/tools:dispatch",
        json={"tool": "toee_workbench_read", "action": "list_cases"},
    )

    assert response.status_code == 401


def test_dispatch_rejects_wrong_bearer_token() -> None:
    response = _client().post(
        "/v1/tools:dispatch",
        headers={"Authorization": "Bearer wrong-token"},
        json={"tool": "toee_workbench_read", "action": "list_cases"},
    )

    assert response.status_code == 401


def test_dispatch_runs_allowlisted_action_and_returns_governed_json() -> None:
    # Allowlisted copilot read → execute_tool runs the mock handler and its JSON
    # comes back under ok/data (ADR-0141 deterministic dispatch).
    response = _client().post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={"tool": "toee_workbench_read", "action": "list_cases"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"] == {"cases": []}


def test_dispatch_passes_params_through_to_handler() -> None:
    # params reach the handler: get_case echoes the requested case_id.
    response = _client().post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={
            "tool": "toee_workbench_read",
            "action": "get_case",
            "params": {"case_id": "case_42"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["case_id"] == "case_42"


def test_dispatch_denies_tool_outside_profile_allowlist() -> None:
    # toee_workbench_admin is supervisor-only (ADR-0038). Under the internal
    # copilot profile it is a governed denial — HTTP 200, ok False, not raised.
    response = _client().post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={"tool": "toee_workbench_admin", "action": "list_accounts"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["class"] == "policy_blocked"


def test_dispatch_unknown_tool_is_governed_not_raised() -> None:
    # Unknown tool is caught by execute_tool's catalog check before the gate, so it
    # is a governed unknown_tool failure (HTTP 200), still never a raised exception.
    response = _client().post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={"tool": "toee_not_a_tool", "action": "list_cases"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["class"] == "unknown_tool"


def test_dispatch_threads_actor_account_id_into_context() -> None:
    # ADR-0141 actor attribution: the BFF-asserted acting account rides the request
    # body and must reach ToolExecutionContext.user_id so governed writes (and the
    # case_view read audit) attribute to the real employee instead of NULL.
    driver = _CapturingDriver()
    response = _client_with_driver(driver).post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={
            "tool": "toee_workbench_read",
            "action": "list_cases",
            "actor_account_id": "acct_rep_7",
        },
    )

    assert response.status_code == 200
    assert driver.context is not None
    assert driver.context.user_id == "acct_rep_7"


def test_dispatch_without_actor_runs_with_no_actor() -> None:
    # Absent actor stays fail-open (user_id None), matching the prior behavior for
    # reads that tolerate it; the BFF always supplies one for governed writes.
    driver = _CapturingDriver()
    _client_with_driver(driver).post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={"tool": "toee_workbench_read", "action": "list_cases"},
    )

    assert driver.context is not None
    assert driver.context.user_id is None


class _FakeIdentityStore:
    """Injected in place of PostgresGatewayStore for DB-free identity-gate tests."""

    def __init__(self, identity):
        self._identity = identity

    def load_case_identity(self, case_id):
        return self._identity


class _ExplodingIdentityStore:
    """A store whose read must never run (memory-disabled gate proof)."""

    def load_case_identity(self, case_id):  # pragma: no cover - must not run
        raise AssertionError(f"load_case_identity must not be called (case_id={case_id!r})")


def _mock_driver():
    from toee_hermes.drivers.mock import MockDriver, create_all_mock_handlers

    return MockDriver(create_all_mock_handlers())


def _seed_verified_case(conn, *, case_id, thread_id, shopify_customer_id, channel_identity):
    """Seed a customer_thread + case bound to a VERIFIED Shopify customer (S16/PAC-4).

    Mirrors ``_seed_case`` in test_copilot_memory_injection.py (the S08 precedent
    for the same case->thread identity lookup, there for the Copilot draft turn).
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO customer_thread (id, channel, channel_identity, shopify_customer_id)"
            " VALUES (%s, 'sms', %s, %s)",
            (thread_id, channel_identity, shopify_customer_id),
        )
        cur.execute(
            "INSERT INTO cases (id, channel, customer_thread_id) VALUES (%s, 'sms', %s)",
            (case_id, thread_id),
        )
    conn.commit()


def test_dispatch_customer_memory_sets_identity_from_case_id(monkeypatch) -> None:
    # S16/PAC-4 core wiring, DB-free: a case_id in params + memory_enabled() ->
    # the injected store resolves the case's identity onto the context, scoped to
    # toee_customer_memory. Any other tool's context.identity stays untouched.
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    identity = {"outcome": "verified_customer", "shopify_customer_id": "gid://shopify/Customer/1"}
    driver = _CapturingDriver()

    _client_with_driver(driver, store=_FakeIdentityStore(identity)).post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={
            "tool": "toee_customer_memory",
            "action": "get_preferences",
            "params": {"case_id": "case-1"},
        },
    )

    assert driver.context is not None
    assert driver.context.identity == identity


def test_dispatch_identity_population_scoped_to_customer_memory_tool_only(monkeypatch) -> None:
    # Minimal blast radius (explicit S16 requirement): even with a case_id present
    # and memory enabled, a DIFFERENT tool never gets identity populated.
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    identity = {"outcome": "verified_customer", "shopify_customer_id": "gid://shopify/Customer/1"}
    driver = _CapturingDriver()

    _client_with_driver(driver, store=_FakeIdentityStore(identity)).post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={
            "tool": "toee_workbench_read",
            "action": "list_cases",
            "params": {"case_id": "case-1"},
        },
    )

    assert driver.context is not None
    assert driver.context.identity is None


def test_dispatch_customer_memory_disabled_never_touches_the_store(monkeypatch) -> None:
    # RK-6: memory disabled (TOOL_BACKEND unset) -> the case_id lookup is never
    # attempted at all (the store would raise if touched) -> identity stays None.
    monkeypatch.delenv("TOOL_BACKEND", raising=False)
    driver = _CapturingDriver()

    _client_with_driver(driver, store=_ExplodingIdentityStore()).post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={
            "tool": "toee_customer_memory",
            "action": "get_preferences",
            "params": {"case_id": "case-1"},
        },
    )

    assert driver.context is not None
    assert driver.context.identity is None


def test_dispatch_customer_memory_without_case_id_fails_closed_no_crash(monkeypatch) -> None:
    # S16 requirement: a dispatch with no case_id still works -- fails closed to
    # the pre-existing policy_blocked denial, never a raised exception. DB-free:
    # an explicitly injected MockDriver backs the actual write.
    monkeypatch.setenv("TOOL_BACKEND", "datastore")

    response = _client_with_driver(_mock_driver()).post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={
            "tool": "toee_customer_memory",
            "action": "upsert_preference",
            "params": {"key": "contact_time_preference", "value": "mornings only"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["class"] == "policy_blocked"


def test_dispatch_customer_memory_correction_binds_to_verified_customers_read_key(
    datastore, monkeypatch
) -> None:
    # S16/PAC-4 real-path round trip: a Workbench employee correction dispatched
    # over the HTTP route with a case_id must persist under the SAME key the
    # verified customer's own next turn reads (the bare shopify_customer_id, no
    # "provisional:" prefix) -- proving the dispatch-server 2-part-key bug
    # (test_dispatch_route_correction_persists_but_misses_a_verified_customers_
    # read_key in test_datastore_driver_memory.py) is closed on the real HTTP
    # dispatch route, not just at the execute_tool layer.
    monkeypatch.setenv("TOOL_BACKEND", "datastore")
    from hermes_runtime.postgres_gateway_store import PostgresGatewayStore

    driver, conn, _ = datastore
    shopify_customer_id = "gid://shopify/Customer/9001"
    _seed_verified_case(
        conn,
        case_id="case-pac4-verified",
        thread_id="thr-pac4-verified",
        shopify_customer_id=shopify_customer_id,
        channel_identity="+14165550199",
    )

    response = _client_with_driver(
        driver, store=PostgresGatewayStore(connection=conn)
    ).post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={
            "tool": "toee_customer_memory",
            "action": "upsert_preference",
            "params": {
                "case_id": "case-pac4-verified",
                "key": "contact_time_preference",
                "value": "mornings only",
            },
            "actor_account_id": "acct_rep_pac4",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["binding_key"] == shopify_customer_id  # bare id, no prefix
    assert body["data"]["source"] == "employee_confirmed"

    # Read Postgres directly: the row genuinely persisted under the customer's own
    # verified read key -- the SAME key openrouter._load_turn_memory derives for
    # that customer's next external turn (binding_key_from_identity on a verified
    # identity, no prefix) -- proving the round trip closes, not just the response.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT slot_value FROM customer_memory_slot"
            " WHERE binding_key = %s AND slot_name = %s",
            (shopify_customer_id, "contact_time_preference"),
        )
        assert cur.fetchone() == ("mornings only",)


def test_dispatch_actor_attributes_the_audit_actor_end_to_end(datastore) -> None:
    # End-to-end (ADR-0141): an HTTP dispatch carrying actor_account_id runs the
    # governed claim through the real datastore and the audit row it writes is
    # attributed to that actor — proving the actor flows request -> context -> audit,
    # not just into the context. Skip-if-no-DB via the shared fixture (ADR-0142).
    from toee_hermes.execute import execute_tool
    from toee_hermes.tool_gate import ToolExecutionContext

    driver, _, _ = datastore
    case_id = execute_tool(
        tool="toee_case",
        action="create_case",
        params={"contact_reason": "x"},
        context=ToolExecutionContext(profile="internal_copilot"),
        driver=driver,
    ).data["case_id"]

    response = _client_with_driver(driver).post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={
            "tool": "toee_case_manage",
            "action": "claim_case",
            "params": {"case_id": case_id},
            "actor_account_id": "acct_actor_e2e",
        },
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True

    entries = execute_tool(
        tool="toee_workbench_read",
        action="get_audit_log",
        params={"case_id": case_id},
        context=ToolExecutionContext(profile="internal_copilot"),
        driver=driver,
    ).data["entries"]
    claim = next(e for e in entries if e["action"] == "claim_case")
    assert claim["account_id"] == "acct_actor_e2e"


def test_dispatch_governed_write_without_actor_is_denied(datastore) -> None:
    # I1 regression end-to-end (ADR-0141): a governed case write dispatched with NO
    # actor_account_id is a governed denial (HTTP 200, ok False), and it leaves NO
    # mutation and NO NULL-actor audit row behind — the silent wrong-success the
    # cutover must not allow. Reads stay fail-open; only writes require the actor.
    from toee_hermes.execute import execute_tool
    from toee_hermes.tool_gate import ToolExecutionContext

    driver, _, _ = datastore
    case_id = execute_tool(
        tool="toee_case",
        action="create_case",
        params={"contact_reason": "x"},
        context=ToolExecutionContext(profile="internal_copilot"),
        driver=driver,
    ).data["case_id"]

    response = _client_with_driver(driver).post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={
            "tool": "toee_case_manage",
            "action": "claim_case",
            "params": {"case_id": case_id},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["class"] == "policy_blocked"

    case = execute_tool(
        tool="toee_workbench_read",
        action="get_case",
        params={"case_id": case_id},
        context=ToolExecutionContext(profile="internal_copilot"),
        driver=driver,
    ).data["case"]
    assert case["assignee_account_id"] is None
    assert case["status"] == "open"

    entries = execute_tool(
        tool="toee_workbench_read",
        action="get_audit_log",
        params={"case_id": case_id},
        context=ToolExecutionContext(profile="internal_copilot"),
        driver=driver,
    ).data["entries"]
    assert [e for e in entries if e["action"] == "claim_case"] == []


def test_dispatch_admin_write_attributes_audit_actor_end_to_end(datastore) -> None:
    # End-to-end (ADR-0141) on the Supervisor Admin surface: an HTTP dispatch under
    # the supervisor_admin profile carrying actor_account_id runs a governed
    # create_account through the real datastore, and the audit row it writes is
    # attributed to that actor — proving the actor flows request -> context -> audit
    # for admin governance, not just copilot case writes. Skip-if-no-DB.
    driver, conn, _ = datastore
    response = _client_with_driver(driver, profile="supervisor_admin").post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={
            "tool": "toee_workbench_admin",
            "action": "create_account",
            "params": {
                "username": "e2e_admin_user",
                "password_hash": "scrypt$dead$beef",
                "role": "customer_service_rep",
            },
            "actor_account_id": "acct_admin_e2e",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    account_id = body["data"]["account_id"]

    with conn.cursor() as cur:
        cur.execute(
            "SELECT account_id FROM workbench_audit_log"
            " WHERE action = 'create_account' AND target_id = %s",
            (account_id,),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "acct_admin_e2e"


def test_dispatch_admin_write_without_actor_is_denied(datastore) -> None:
    # I1 regression end-to-end on the admin surface: a governed create_account with
    # NO actor_account_id is a governed denial (HTTP 200, ok False, policy_blocked)
    # that leaves NO account row and NO NULL-actor audit row behind.
    driver, conn, _ = datastore
    response = _client_with_driver(driver, profile="supervisor_admin").post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={
            "tool": "toee_workbench_admin",
            "action": "create_account",
            "params": {
                "username": "noactor_admin_user",
                "password_hash": "scrypt$dead$beef",
                "role": "customer_service_rep",
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["class"] == "policy_blocked"

    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM workbench_account WHERE username = %s",
            ("noactor_admin_user",),
        )
        assert cur.fetchone()[0] == 0
        cur.execute(
            "SELECT count(*) FROM workbench_audit_log WHERE action = 'create_account'"
        )
        assert cur.fetchone()[0] == 0


def test_dispatch_authenticate_verifies_login_end_to_end(datastore) -> None:
    # End-to-end (ADR-0144) login cutover: seed an account via the governed
    # create_account, then dispatch authenticate with NO actor_account_id — it is
    # pre-auth and fail-open on actor (it establishes the actor). Valid creds return
    # the public account (with last_login_at, never the hash); a bad password is a
    # governed `unauthenticated` (HTTP 200, ok False; BFF -> 401). Skip-if-no-DB.
    import hashlib

    def _scrypt_hash(plain: str, salt: bytes = b"\x02" * 16) -> str:
        derived = hashlib.scrypt(
            plain.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=64,
            maxmem=64 * 1024 * 1024,
        )
        return f"scrypt${salt.hex()}${derived.hex()}"

    driver, _, _ = datastore
    client = _client_with_driver(driver, profile="supervisor_admin")
    stored = _scrypt_hash("RightPass1!")
    client.post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={
            "tool": "toee_workbench_admin",
            "action": "create_account",
            "params": {
                "username": "e2e_login",
                "password_hash": stored,
                "role": "customer_service_rep",
            },
            "actor_account_id": "acct_admin_e2e",
        },
    )

    ok = client.post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={
            "tool": "toee_workbench_admin",
            "action": "authenticate",
            "params": {"username": "e2e_login", "password": "RightPass1!"},
        },
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["ok"] is True
    account = body["data"]["account"]
    assert account["username"] == "e2e_login"
    assert account["last_login_at"] is not None
    assert "password_hash" not in account
    # The stored hash never appears anywhere in the dispatched response.
    assert "password_hash" not in ok.text
    assert stored not in ok.text

    bad = client.post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={
            "tool": "toee_workbench_admin",
            "action": "authenticate",
            "params": {"username": "e2e_login", "password": "WRONG"},
        },
    )
    assert bad.status_code == 200
    bad_body = bad.json()
    assert bad_body["ok"] is False
    assert bad_body["error"]["class"] == "unauthenticated"


def test_dispatch_knowledge_write_attributes_audit_actor_end_to_end(datastore) -> None:
    # End-to-end (ADR-0141/0145) on the KnowledgeOps surface: a supervisor_admin
    # dispatch of a governed update_policy_slot carrying actor_account_id writes the
    # audit attributed to that actor. The six slots are seeded by the 0003 migration.
    driver, conn, _ = datastore
    response = _client_with_driver(driver, profile="supervisor_admin").post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={
            "tool": "toee_knowledge_ops",
            "action": "update_policy_slot",
            "params": {"slot_id": "order-delivery", "draft_text": "Confirm order number."},
            "actor_account_id": "acct_know_e2e",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["slot"]["status"] == "draft"

    with conn.cursor() as cur:
        cur.execute(
            "SELECT account_id FROM workbench_audit_log"
            " WHERE action = 'update_policy_slot' AND target_id = %s",
            ("order-delivery",),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "acct_know_e2e"


def test_dispatch_knowledge_write_without_actor_is_denied(datastore) -> None:
    # I1 regression end-to-end on the KnowledgeOps surface: a governed
    # update_policy_slot with NO actor_account_id is a governed denial that leaves
    # the slot unchanged and writes NO audit row.
    driver, conn, _ = datastore
    response = _client_with_driver(driver, profile="supervisor_admin").post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={
            "tool": "toee_knowledge_ops",
            "action": "update_policy_slot",
            "params": {"slot_id": "order-delivery", "draft_text": "should not persist"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["class"] == "policy_blocked"

    with conn.cursor() as cur:
        cur.execute(
            "SELECT status, draft_text FROM workbench_policy_slot WHERE slot_id = %s",
            ("order-delivery",),
        )
        status, draft_text = cur.fetchone()
        assert status == "empty"
        assert draft_text is None
        cur.execute(
            "SELECT count(*) FROM workbench_audit_log WHERE action = 'update_policy_slot'"
        )
        assert cur.fetchone()[0] == 0


def _seed_policy_publish_run(conn, run_id: str, slot_key: str) -> None:
    """Seed a clean (promotable) policy_publish eval run gating ``slot_key``."""
    from psycopg.types.json import Jsonb

    report = {
        "run_id": run_id, "suite": "policy_publish", "model_slug": "m",
        "prompt_version": "p", "knowledge_version": "k",
        "timestamp": "2026-06-01T00:00:00Z", "scenarios": [],
        "summary": {"total": 1, "passed": 1, "failed_high": 0, "failed_medium": 0},
        "signoff_required": False,
    }
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO eval_run (id, suite, status, failed_high, report, slot_key)"
            " VALUES (%s, 'policy_publish', 'recorded', 0, %s, %s)",
            (run_id, Jsonb(report), slot_key),
        )
    conn.commit()


def test_dispatch_eval_promote_publishes_and_attributes_audit_end_to_end(datastore) -> None:
    # End-to-end (ADR-0146) on the eval surface: a supervisor_admin dispatch of a
    # governed promote_pending_policy carrying actor_account_id runs the publish
    # bridge through the real datastore -- the kebab authoring slot is published and
    # the audit row is attributed to that actor (request -> context -> audit + bridge).
    driver, conn, _ = datastore
    client = _client_with_driver(driver, profile="supervisor_admin")
    client.post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={
            "tool": "toee_knowledge_ops", "action": "update_policy_slot",
            "params": {"slot_id": "business-hours", "draft_text": "Open 9-5"},
            "actor_account_id": "acct_eval_e2e",
        },
    )
    _seed_policy_publish_run(conn, "pp-e2e", "business_hours_service_boundaries")

    response = client.post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={
            "tool": "toee_eval_review", "action": "promote_pending_policy",
            "params": {"run_id": "pp-e2e"},
            "actor_account_id": "acct_eval_e2e",
        },
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True

    with conn.cursor() as cur:
        cur.execute(
            "SELECT status, published_text FROM workbench_policy_slot WHERE slot_id = %s",
            ("business-hours",),
        )
        assert cur.fetchone() == ("published", "Open 9-5")
        cur.execute(
            "SELECT account_id FROM workbench_audit_log"
            " WHERE action = 'promote_pending_policy' AND target_id = %s",
            ("pp-e2e",),
        )
        assert cur.fetchone()[0] == "acct_eval_e2e"


def test_dispatch_eval_write_without_actor_is_denied(datastore) -> None:
    # I1 regression end-to-end on the eval surface: a governed promote with NO
    # actor_account_id is a governed denial (policy_blocked) that leaves the run
    # un-promoted and writes NO audit row.
    driver, conn, _ = datastore
    _seed_policy_publish_run(conn, "pp-noactor", "business_hours_service_boundaries")
    response = _client_with_driver(driver, profile="supervisor_admin").post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={
            "tool": "toee_eval_review", "action": "promote_pending_policy",
            "params": {"run_id": "pp-noactor"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["class"] == "policy_blocked"

    with conn.cursor() as cur:
        cur.execute("SELECT promoted FROM eval_run WHERE id = %s", ("pp-noactor",))
        assert cur.fetchone()[0] is False
        cur.execute(
            "SELECT count(*) FROM workbench_audit_log WHERE action = 'promote_pending_policy'"
        )
        assert cur.fetchone()[0] == 0


def test_dispatch_rejects_malformed_body() -> None:
    # Missing tool/action is a transport/shape problem, not a tool outcome → 400.
    response = _client().post(
        "/v1/tools:dispatch",
        headers=_auth(),
        json={"action": "list_cases"},
    )

    assert response.status_code == 400
