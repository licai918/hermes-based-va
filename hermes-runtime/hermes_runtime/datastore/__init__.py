"""Local Toee Business Datastore: config + migration runner (ADR-0140, ADR-0142).

The datastore is the system-of-record (ADR-0140). It is stood up as local
Postgres first (docker-compose, ADR-0142); Cloud SQL is the deferred target. This
package holds only the connection config and the raw-SQL migration runner; the
per-tool datastore driver that the ``toee_hermes`` handlers call lands in a later
slice. Heavy deps (psycopg) live here in the hermes-runtime venv, never in the
dependency-free ``toee_hermes`` plugin (ADR-0096/0100).
"""

# Only config is re-exported here. The migration runner is used as a module
# (``python -m hermes_runtime.datastore.migrate``) or imported from
# ``hermes_runtime.datastore.migrate`` directly, so it is not eagerly imported
# (avoids the runpy "found in sys.modules" warning when run via -m).
from .config import DEFAULT_DATABASE_URL, database_url

__all__ = ["DEFAULT_DATABASE_URL", "database_url"]
