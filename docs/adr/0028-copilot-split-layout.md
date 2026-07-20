# Copilot Workbench split layout for MVP

> **Storage substrate superseded by ADR-0140/0142.** The split layout holds. Only the
> substrate changes: the left-pane queue, thread summaries, and resolution status
> read from the **Toee Business Datastore** (Postgres), not **Hermes Native Memory**,
> which is conversation-only.
> Current direction → [`docs/architecture/memory-layers.md`](../architecture/memory-layers.md).

The first-version **Copilot Workbench** uses a single-page split layout:

- **Left pane — Operations Dashboard**: case queue, filters, urgency, customer thread summary, and resolution status from **Hermes Native Memory**
- **Right pane — Copilot Gateway**: internal chat with **Hermes Core** through the **Internal Copilot Profile**, scoped to the case or customer thread selected on the left

Selecting a case on the left loads its context into the right-side Copilot chat. Employees draft replies and inspect tool evidence without leaving the page.

**Considered options:** separate dashboard and chat apps (rejected—slower case handling); chat-only workbench without queue (rejected—weak operations view).
