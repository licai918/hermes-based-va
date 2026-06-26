# toee_workbench_read.get_thread for Case Thread Context

`toee_workbench_read` gains a fourth v1 **Domain Adapter Tool Action**, `get_thread`, extending ADR-0068. It returns one **Follow-up Case** together with its full read-only **Case Thread Context** timeline (ADR-0082) so the `/copilot` thread panel reads case header metadata and message history in a single governed dispatch.

## Decision

- `get_thread` takes a `case_id` and returns `{ case, messages }`: the full WorkbenchCase read model (ADR-0064/0115) plus the ordered timeline of the case's customer thread.
- It is available to the same profiles as the rest of `toee_workbench_read` — the **Internal Copilot Profile** (ADR-0035) and **Supervisor Admin Profile** (ADR-0038). The Profile Tool Allowlist gates by toolset, so no allowlist change is needed (ADR-0034).
- Each `message_turn` is mapped to a `ThreadMessage`. `message_turn` is single-channel per thread, so the case/thread channel is applied to every turn. `active_case_segment` is the inverse of `auto_handled`: the active **Human Intervention Case** segment is the non-auto-handled turns, and prior **Auto-Handled Interaction** turns stay visible but de-emphasized (ADR-0082).
- Opening or refreshing Case Thread Context writes one `case_view` **Workbench Audit Log** entry in the same transaction as the read (ADR-0042). A missing case is a legitimate empty read (`{ case: null, messages: [] }`) and is **not** audited (ADR-0020).

## Consequences

- The catalog (`@toee/shared` and `toee_hermes`), the deterministic mock stubs for both runtimes, and the plugin manifest all carry `toee_workbench_read__get_thread`; the Postgres datastore implements the real read + audit write.
- The Workbench BFF thread route (`GET /api/copilot/cases/[id]/thread`) dispatches `get_thread` over the per-profile API when configured (ADR-0141) and otherwise falls back to the in-memory store.

**Considered options:** keep reading the case header and timeline as two separate dispatches `get_case` + a new `list_thread` (rejected—the thread panel always loads both together, and one action keeps the single `case_view` audit atomic with the read); store `active_case_segment` as a `message_turn` column (rejected—it is derivable from `auto_handled`, so a column would duplicate state that could drift); audit thread reads from the BFF instead of the datastore (rejected—the governed datastore transaction is the system-of-record boundary, and BFF-side auditing would not commit with the read).
