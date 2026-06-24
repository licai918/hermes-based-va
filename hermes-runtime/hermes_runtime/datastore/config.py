"""Datastore connection configuration (ADR-0140, ADR-0142).

Resolved from the environment with a local-first default so development needs no
GCP credentials. Deployed envs inject ``DATABASE_URL`` from Secret Manager
(Cloud SQL) in the deferred cloud slice; the URL shape is identical.
"""

from __future__ import annotations

import os

# Matches the docker-compose service (user/password/db = toee / toee / toee_va).
DEFAULT_DATABASE_URL = "postgresql://toee:toee@localhost:5432/toee_va"


def database_url() -> str:
    """The Postgres DSN, from ``DATABASE_URL`` or the local docker-compose default."""
    url = os.environ.get("DATABASE_URL", "").strip()
    return url or DEFAULT_DATABASE_URL
