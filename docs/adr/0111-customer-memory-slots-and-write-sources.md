# Customer Memory slots and governed write sources

> **Storage substrate superseded by ADR-0140.** Slots and governed write sources
> hold; they are stored in the Toee Business Datastore (Postgres), not Hermes
> Native Memory.

> **Amended by [ADR-0148](0148-copilot-agent-source-actor-attribution-and-context-only-binding.md)**
> (2026-07-14, 0.0.2). "After employee confirmation," below, no longer covers
> every Internal Copilot write — a Copilot draft turn may also write on its own
> initiative (S20). `source` now distinguishes the two (`employee_confirmed` vs.
> the new `copilot_agent`), and a nullable `actor_account_id` column records the
> confirming rep, when there is one.

**Customer Memory** stores structured service preferences in **Hermes Native Memory** per ADR-0110. v1 uses fixed slots and governed writes rather than open-ended key-value preference storage.

## v1 preference slots

| Slot | Purpose |
|------|---------|
| `contact_time_preference` | Preferred contact time window or schedule note |
| `channel_preference` | Preferred service channel such as SMS or email |
| `delivery_habit_note` | Durable delivery habit note that is not a live order fact |
| `communication_style_note` | Brief communication-style preference such as concise replies |

Each slot stores short text with a defined maximum length. Slots do not store order status, AR facts, policy text, or inferred personality judgments.

## Write surfaces

### External customer-service agent

The **External Customer Service Profile** may write **Customer Memory** only when the customer explicitly states a durable preference in the current turn. Writes use a governed Domain Adapter Tool such as `toee_customer_memory.upsert_preference`.

Hermes must not infer or autowrite preferences from tone, order history, or model guesswork.

### Copilot workbench

**Customer Service Rep**, **Workbench Supervisor**, and **Workbench Admin** users may upsert, correct, or clear preference slots through the **Internal Copilot Profile** while handling a **Human Intervention Case**, after employee confirmation in the Copilot workflow.

### Not allowed in v1

- open-ended preference keys
- autonomous preference writes without explicit customer language or employee confirmation
- storing **SMS Opt-Out** or other consent state in **Customer Memory**

Consent remains in the **Identity Graph**.

## Storage rule

Preference reads and writes use official **Hermes Native Memory** APIs through the **Hermes Runtime Shim**. Toee Tire defines slot schema and tool behavior only.

**Considered options:** open key-value customer memory (rejected—hard to audit and easy for model drift); read-only preferences in v1 (rejected—user requested durable customer-bound memory); use unstructured Hermes built-in `memory` writes for preferences (rejected—weak schema and upgrade governance).
