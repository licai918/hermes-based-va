# toee_customer_memory v1 actions and profile allowlists

> **Storage substrate refined by ADR-0140.** Action enums and allowlists hold;
> the tool reads/writes the Toee Business Datastore (Postgres), not Hermes Native
> Memory.

> **Amended by [ADR-0148](0148-copilot-agent-source-actor-attribution-and-context-only-binding.md)**
> (2026-07-14, 0.0.2). "Employee-confirmed preference changes," below, no longer
> describes every Internal Copilot write: a draft turn's own `upsert_preference`
> call now persists `source = copilot_agent`, not `employee_confirmed`. The
> active Human Intervention Case requirement is unchanged.

**Customer Memory** writes use a dedicated Domain Adapter Tool with fixed v1 action enums per ADR-0059.

## toee_customer_memory

| Action | Purpose |
|--------|---------|
| `upsert_preference` | Create or update one allowed preference slot for the active identity binding |
| `clear_preference` | Clear one allowed preference slot |
| `get_preferences` | Read the current four preference slots for explicit verification |

Allowed slots remain the four v1 values from ADR-0111.

## Profile allowlists

**External Customer Service Profile**

- allowed: `upsert_preference`
- not allowed: `clear_preference`

`upsert_preference` requires **Tool Gate** proof that the current customer turn explicitly stated the preference being stored. Hermes must not upsert from inference alone.

**Internal Copilot Profile**

- allowed: `upsert_preference`, `clear_preference`, `get_preferences`

Copilot writes require an active **Human Intervention Case** and employee-confirmed preference changes per ADR-0111.

**Supervisor Admin Profile**

- `toee_customer_memory` is not registered in v1

Customer preference administration stays in customer-service and Copilot workflows, not governance console tools.

## Read behavior

Routine reads use lightweight per-turn injection per ADR-0113. `get_preferences` is supplemental for Copilot verification and eval assertions, not a required external turn action.

**Considered options:** grant External `clear_preference` (rejected—customers should not lose stored preferences without employee review); grant Admin preference writes (rejected—blurs governance and service boundaries); make `get_preferences` the only read path (rejected—unnecessary tool latency when slots are already injected).
