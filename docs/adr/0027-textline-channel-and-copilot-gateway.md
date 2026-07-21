# Textline channel binding and Copilot internal gateway

> **Storage substrate superseded by ADR-0140/0142.** Textline as a channel rather than a
> profile, the **Customer Thread** + **SMS Session** two-level model, the thin **Channel
> Gateway**, and the two **Copilot Workbench** surfaces all still hold. Superseded: both
> substrate claims — the long-lived **Customer Thread** (L2) and the **Operations
> Dashboard** reads both come from the **Toee Business Datastore** (Postgres), and the ban
> on "a parallel case database" now prohibits exactly what shipped. Hermes memory is
> conversation-only.
> Current direction → [`docs/architecture/memory-layers.md`](../architecture/memory-layers.md).

> **Provider retired (2026-07-21).** Textline was cancelled for SimpleTexting; the SMS
> channel, its webhook, and its outbound **Tool** carry provider-neutral names now.
> Superseding decision → [ADR-0153](0153-provider-neutral-sms-tool-naming.md).

Textline is not its own Hermes Profile. It is a **channel** that routes inbound SMS into the **External Customer Service Profile**.

For each customer phone number, Hermes maintains:

1. A long-lived **Customer Thread** in **Hermes Native Memory** spanning all Textline messages over time.
2. One or more bounded **SMS Session** windows (24 hours) that control agent runtime context and re-verification behavior.

A new inbound Textline webhook is handled by a thin **Channel Gateway** that verifies authenticity, normalizes the event, binds the Textline conversation id to the current **SMS Session**, and invokes **Hermes Core** under the external profile. Outbound replies use a Textline **Tool**; webhook normalization, opt-out handling, and session binding use **Skills**.

**Internal Copilot Profile** is the governed internal mode of the same **Hermes Core**. The **Copilot Workbench** is the employee shell with two surfaces on one app:

- **Copilot Gateway**: internal chat that talks to Hermes through `copilot_internal`
- **Operations Dashboard**: case queue, conversation history, urgent flags, eval status, and resolution controls

Employees select or reference a **Follow-up Case** or customer thread, then use Copilot Gateway to draft replies and inspect tool evidence. Dashboard state is read from **Hermes Native Memory**, not a parallel case database invented for this project.

**Considered options:** Textline as its own profile (rejected—splits customer-service policy); Copilot as only a passive ticket UI without internal chat (rejected—weak employee workflow).
