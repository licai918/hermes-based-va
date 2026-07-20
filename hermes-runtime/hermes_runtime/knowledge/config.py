"""Knowledge store connection configuration (FR-1, PRD §7.4).

Resolved from the environment with a local-first default, mirroring the
business datastore's DSN seam (``hermes_runtime/datastore/config.py``). The
knowledge store is a SEPARATE Postgres database (``toee_knowledge``) from the
business datastore (``toee_va``) -- the S-ISO isolation invariant proved in
the 0.0.3 spike: the knowledge DSN never defaults to the business DB, and
nothing here shares a connection with ``hermes_runtime.datastore``.
"""

from __future__ import annotations

import os

# Matches the docker-compose service (user/password = toee/toee); the DB name
# is the separate toee_knowledge database, never toee_va.
DEFAULT_KNOWLEDGE_DATABASE_URL = "postgresql://toee:toee@localhost:5432/toee_knowledge"


def knowledge_database_url() -> str:
    """The knowledge-store Postgres DSN, from ``KNOWLEDGE_DATABASE_URL`` or the
    local docker-compose default. Lazy: reading this makes no connection."""
    url = os.environ.get("KNOWLEDGE_DATABASE_URL", "").strip()
    return url or DEFAULT_KNOWLEDGE_DATABASE_URL
