# Textline channel binding and Copilot internal gateway

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
