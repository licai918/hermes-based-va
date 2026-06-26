# Lightweight Customer Memory injection with governed tool writes

> **Refined by ADR-0140.** Reads inject from the Toee Business Datastore via the
> `toee_hermes` `pre_llm_call` hook (appended to the user turn); writes go through
> the `toee_customer_memory` plugin tool. Hermes built-in `memory` stays the
> agent's own conversation notes.

**Customer Memory** reads and writes use different paths in v1.

## Read path — lightweight per-turn injection

At the start of each external agent turn and each Copilot case-scoped turn, the **Hermes Runtime Shim** reads the current **Customer Memory** slots from official **Hermes Native Memory** and injects a compact memory block into runtime context when any slot has a value.

Binding key selection:

- **Verified Customer** — read from `shopifyCustomerId`
- otherwise — read provisional records for the active `channelIdentityId`

If no slots exist, Hermes injects no empty Customer Memory section.

Injection includes only the four v1 slots from ADR-0111. It does not inject live order, AR, or policy facts.

## Write path — governed tools only

Preference writes and clears do not happen through prompt injection. They use governed Domain Adapter Tools such as `toee_customer_memory.upsert_preference` and `toee_customer_memory.clear_preference` under the profile allowlists defined in a separate ADR.

A supplemental `get_preferences` read tool may exist for explicit verification, but it is not required on every turn because reads are already injected.

## Copilot behavior

When an employee selects a **Human Intervention Case**, Copilot context loading uses the same Customer Memory read rules based on the active case thread identity.

Employees may correct preferences through governed write tools after confirmation per ADR-0111.

**Considered options:** tool-only reads on demand (rejected—extra latency and missed preference use on simple turns); permanent system-prompt preference text (rejected—not customer-specific); treat injected memory as writable by the model without tools (rejected—weak audit and upgrade governance).
