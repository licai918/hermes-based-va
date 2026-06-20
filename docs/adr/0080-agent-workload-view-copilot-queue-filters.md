# Agent Workload View as Copilot queue filters for supervisors

**Workbench Supervisor** and **Workbench Admin** users review team case ownership from the same `/copilot` **Case Queue** used for their own case handling. v1 does not add a separate workload route or admin-only workload report page.

Supervisor-only queue controls appear in the **Case Queue** header on `/copilot`:

- **Assignee filter** — filter by a specific **Workbench Account**, plus an **All team** option that shows every open or in-progress **Human Intervention Case**
- **Status filter** — default remains open and in progress; supervisors may optionally include resolved cases for recent workload review
- existing **Contact Reason** and urgency filters remain available on the same queue surface

**Customer Service Rep** users do not receive the **All team** assignee option or resolved-case widening in the default view. Their default filters remain mine plus unassigned per ADR-0079.

The v1 column set and default sort rules do not change when a supervisor applies workload filters. Selecting a case still loads **Case Thread Context** on the left and scopes the **Copilot Gateway** on the right.

**Considered options:** separate `/copilot/workload` page with per-rep counts (rejected—adds navigation overhead for a small launch team); admin-only workload reporting under `/admin` (rejected—workload review is operational case oversight, not governance configuration); grant reps all-team visibility (rejected—unnecessary exposure of peer queues).
