"""0.0.4 S16 (FR-24): scheduled integration health probes.

Two layers, mirroring the T4 drivers' own test posture:

- The dispatch/classify/deadline logic + the not-configured / failed / ok states
  are exercised against FAKE probes (no network, no live backend) -- the same way
  the drivers unit-test governance against a fake client. A wrong live-wire guess
  can only ever record ``failed``, never a false ``ok``.
- Storage + the page fill are exercised live-Postgres against an isolated schema
  (the ``datastore`` fixture applies migration 0015).

The seven real probes are proven to record ``not_configured`` (SKIPPED, never
failed/ok) when owner-blocked -- which is every credential today.
"""

from __future__ import annotations

import time

from hermes_runtime.datastore.handlers.integrations import _get_integrations_status
from hermes_runtime.integration_probe import (
    PROBES,
    Probe,
    ProbeResult,
    record_probe_results,
    run_integration_probe_job,
    run_probes,
)
from toee_hermes.errors import ToolDriverError
from toee_hermes.tool_gate import ToolExecutionContext

_CTX = ToolExecutionContext(profile="supervisor_admin")

# Every credential env the real probes gate on -- cleared so a stray dev-shell var
# cannot make an "owner-blocked" assertion pass by accident.
_CRED_ENVS = [
    "COMPOSIO_API_KEY",
    "COMPOSIO_SHOPIFY_CONNECTED_ACCOUNT_ID",
    "COMPOSIO_QBO_CONNECTED_ACCOUNT_ID",
    "COMPOSIO_SQUARE_CONNECTED_ACCOUNT_ID",
    "COMPOSIO_TOOLKIT_VERSION_SHOPIFY",
    "COMPOSIO_TOOLKIT_VERSION_QUICKBOOKS",
    "COMPOSIO_TOOLKIT_VERSION_SQUARE",
    "EASYROUTES_SECRET",
    "EASYROUTES_API_TOKEN",
    "EASYROUTES_CLIENT_ID",
    "SIMPLETEXTING_API_TOKEN",
    "OPENROUTER_API_KEY",
    "GADGET_API_KEY",
]


def _clear_creds(monkeypatch):
    for name in _CRED_ENVS:
        monkeypatch.delenv(name, raising=False)


def _configured(value: bool):
    return lambda: value


def _raises(exc: Exception):
    def _check() -> None:
        raise exc

    return _check


# --------------------------------------------------------------------------
# the three honest states, never conflated (dispatch logic, DB-free)
# --------------------------------------------------------------------------


def test_not_configured_is_skipped_never_failed_never_ok():
    probe = Probe(
        key="k",
        configured=_configured(False),
        check=_raises(RuntimeError("must never be called when unconfigured")),
        not_configured_reason="not configured: SET_ME",
    )
    [result] = run_probes([probe])
    assert result == ProbeResult("k", "not_configured", "not configured: SET_ME")


def test_a_clean_check_is_ok():
    probe = Probe("k", _configured(True), lambda: None, "n/a")
    [result] = run_probes([probe])
    assert result == ProbeResult("k", "ok", None)


def test_a_governed_error_is_failed_with_its_reason():
    probe = Probe(
        "k", _configured(True), _raises(ToolDriverError("auth_expired", "HTTP 401")), "n/a"
    )
    [result] = run_probes([probe])
    assert result.status == "failed"
    assert "auth_expired" in result.reason and "401" in result.reason


def test_an_arbitrary_error_is_failed_never_ok():
    # The empty-vs-error spine: any unexpected fault records failed, not a false ok.
    probe = Probe("k", _configured(True), _raises(ValueError("weird")), "n/a")
    [result] = run_probes([probe])
    assert result.status == "failed"
    assert "ValueError" in result.reason


def test_a_hung_check_hits_the_deadline_and_is_failed():
    probe = Probe("k", _configured(True), lambda: time.sleep(5), "n/a")
    [result] = run_probes([probe], deadline_ms=50)
    assert result.status == "failed"
    assert "deadline" in result.reason


# --------------------------------------------------------------------------
# the seven real probes -- owner-blocked reality
# --------------------------------------------------------------------------


def test_the_seven_real_probes_are_all_not_configured_when_owner_blocked(monkeypatch):
    _clear_creds(monkeypatch)
    results = run_probes(PROBES)
    assert {r.key for r in results} == {
        "shopify",
        "qbo",
        "square",
        "easyroutes",
        "simpletexting",
        "openrouter",
        "gadget",
    }
    # Every one is SKIPPED (no credential), never a fabricated healthy/failed, and
    # no live backend was touched to decide that.
    for r in results:
        assert r.status == "not_configured", r
        assert r.reason and "not configured" in r.reason


# --------------------------------------------------------------------------
# storage + the S15 page fill (live Postgres, isolated schema)
# --------------------------------------------------------------------------


def _last_probe(conn, key):
    rows = _get_integrations_status(conn, {}, _CTX)["integrations"]
    return {row["key"]: row["last_probe"] for row in rows}[key]


def test_page_shows_never_probed_before_any_probe(datastore):
    _driver, conn, _schema = datastore
    assert _last_probe(conn, "gadget") is None


def test_record_fills_the_pages_last_probe_with_the_latest_per_integration(datastore):
    _driver, conn, _schema = datastore

    record_probe_results(
        [
            ProbeResult("gadget", "failed", "auth_expired: HTTP 401"),
            ProbeResult("openrouter", "not_configured", "not configured: OPENROUTER_API_KEY"),
        ],
        conn=conn,
    )
    # A later cycle supersedes the earlier gadget row (page reads the LATEST).
    record_probe_results([ProbeResult("gadget", "ok", None)], conn=conn)

    gadget = _last_probe(conn, "gadget")
    assert gadget["status"] == "ok" and gadget["reason"] is None
    assert gadget["checked_at"]  # an ISO timestamp string

    openrouter = _last_probe(conn, "openrouter")
    assert openrouter["status"] == "not_configured"
    # An integration with no probe row at all stays "never probed".
    assert _last_probe(conn, "shopify") is None


def test_retention_prunes_probe_history_beyond_the_window(datastore):
    _driver, conn, _schema = datastore
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO integration_probe (integration_key, status, reason, checked_at) "
            "VALUES ('gadget', 'ok', NULL, now() - interval '90 days')"
        )
    conn.commit()

    record_probe_results([ProbeResult("gadget", "failed", "boom")], conn=conn, retention_days=30)

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM integration_probe WHERE integration_key = 'gadget'")
        # The 90-day-old row is pruned; only the just-written one remains.
        assert cur.fetchone()[0] == 1


def test_the_job_body_records_a_row_the_page_reads_when_owner_blocked(
    datastore, monkeypatch
):
    """End-to-end minus the live wire: owner-blocked, so the job records seven
    not_configured rows and the page reads them (no network)."""
    _driver, conn, _schema = datastore
    _clear_creds(monkeypatch)

    # The job body opens its own connection in production; here, pin it to the
    # isolated-schema fixture connection so the write and the read share a schema.
    import hermes_runtime.integration_probe as probe_mod

    real_record = probe_mod.record_probe_results
    monkeypatch.setattr(
        probe_mod,
        "record_probe_results",
        lambda results, **kw: real_record(results, conn=conn),
    )

    run_integration_probe_job({"schedule_window": 1})

    gadget = _last_probe(conn, "gadget")
    assert gadget is not None and gadget["status"] == "not_configured"
