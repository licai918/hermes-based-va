"""Datastore connection configuration (ADR-0140, ADR-0142).

Resolved from the environment with a local-first default so development needs no
GCP credentials. Deployed envs inject ``DATABASE_URL`` from Secret Manager
(Cloud SQL) in the deferred cloud slice; the URL shape is identical.
"""

from __future__ import annotations

import os

# Matches the docker-compose service (user/password/db = toee / toee / toee_va).
DEFAULT_DATABASE_URL = "postgresql://toee:toee@localhost:5432/toee_va"

# --- connect timeouts -------------------------------------------------------
# EVERY connection this codebase opens must bound its TCP connect, because the
# default does not. A Postgres that REFUSES fails in milliseconds and fail-open
# works exactly as designed; a Postgres that is UNREACHABLE WITHOUT REFUSING --
# a dropped network, a firewall that blackholes, a host up but not listening --
# blocks until the OS TCP timeout, which on Linux is well over a minute. Every
# fail-open path in this codebase is written as though failure is fast. Fail-open
# only works if the failure is BOUNDED; unbounded fail-open is just a hang with a
# reassuring docstring.
#
# Two values, because the two situations have genuinely different budgets.

# Anything on the path that produces a customer reply. NFR-5 says memory and
# metrics must never stall a reply, so the ceiling is "shorter than a person
# notices", not "long enough to probably succeed". A connect that has not
# completed in two seconds against a healthy database is not going to.
CONNECT_TIMEOUT_TURN_SECONDS = 2

# Migrations, ingestion and probes: nobody is waiting on a reply, and a slow
# link should not turn into a spurious failure. Still bounded -- an unattended
# job that hangs forever is a job nobody notices has stopped.
CONNECT_TIMEOUT_OFFLINE_SECONDS = 10


def database_url() -> str:
    """The Postgres DSN, from ``DATABASE_URL`` or the local docker-compose default."""
    url = os.environ.get("DATABASE_URL", "").strip()
    return url or DEFAULT_DATABASE_URL
