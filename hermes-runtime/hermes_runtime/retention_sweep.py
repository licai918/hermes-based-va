"""Manual/scheduled entrypoint for the Customer Memory retention sweep (0.0.3
S28, FR-30, ADR-0004/0116).

Ages out ``customer_memory_slot`` rows per the class windows in
``hermes_runtime.datastore.handlers.retention``, printing per-class counts.
Runs the SAME governed dispatch path (``execute_tool``) the admin BFF's
``tools:dispatch`` trigger button uses, so the audit trail
(``workbench_audit_log`` action ``retention_sweep``) -- and therefore the
admin panel's "last run" -- reflects a scheduled run exactly like a manual one.

"Schedulable" (FR-30) means any external cron/scheduler invokes this module,
e.g.::

    0 3 * * * cd hermes-runtime && python -m hermes_runtime.retention_sweep

No in-repo scheduler is built for this (out of scope, S28 brief) -- this is
the documented entrypoint one wires up.
"""

from __future__ import annotations

from toee_hermes.execute import execute_tool
from toee_hermes.tool_gate import ToolExecutionContext

from .datastore.driver import PostgresDriver


def main() -> int:
    driver = PostgresDriver()
    # internal_copilot: the only profile toee_retention is allowlisted under
    # (hermes/toee_hermes/plugin/profiles.py) -- no attributed actor for an
    # unattended scheduled run, same as any other cron-triggered batch job.
    result = execute_tool(
        tool="toee_retention",
        action="trigger_retention_sweep",
        params={},
        context=ToolExecutionContext(profile="internal_copilot"),
        driver=driver,
    )
    if not result.ok:
        print(f"retention sweep FAILED: {result.error_class}: {result.message}")
        return 1
    print(f"retention sweep OK: {result.data}")
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI shell
    raise SystemExit(main())
