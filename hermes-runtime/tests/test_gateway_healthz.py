"""Gateway liveness probe (/healthz) for Cloud Run (ADR-0098, issue #33).

Cloud Run gates traffic on a cheap liveness endpoint. It must answer 200 without
any secret or turn-runner wiring, so the same minimal ``create_app`` the other
gateway tests boot is enough to exercise it (no real secrets required).
"""

from __future__ import annotations

from starlette.testclient import TestClient

from hermes_runtime.gateway_app import create_app

WEBHOOK_SECRET = "test-textline-shared-secret"


def test_healthz_returns_ok_without_secrets_or_turn_runner() -> None:
    # Liveness only: build the app with nothing but the webhook secret the other
    # tests use — no reply sender, store, queue, or internal-job secret — and the
    # probe still answers 200 {"status": "ok"}.
    client = TestClient(create_app(webhook_secret=WEBHOOK_SECRET))

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
