# ADR-first integration extension with optional Composio implementation

New business integrations in **Hermes VA** must define the governed Toee tool contract before choosing Composio, direct REST, or another internal backend.

## Required sequence

1. **ADR** — define the new or extended `toee_*` tool, fixed v1 `action` enums, profile allowlist impact, and **Tool Gate** rules
2. **Catalog update** — extend ADR-0070 or a successor catalog ADR with the new tool/actions
3. **Eval coverage** — add or update **Launch Eval Scenario** fixtures when the capability affects an external or publish gate
4. **Adapter implementation** — implement in `packages/domain-adapters` behind the frozen contract
5. **Backend choice** — for Layer 1 tools per ADR-0128, prefer one-to-one Composio mapping per ADR-0130; fall back to direct REST when Composio has no suitable single action

Composio toolkit availability does not determine the public Hermes tool surface. The team does not register Composio actions on **Hermes Profiles** before steps 1–3 are complete.

## New integration ADR checklist

Each integration ADR should state:

- tool name and v1 `action` enum
- allowed **Hermes Profiles**
- **Tool Gate** prerequisites such as verified customer, email link, or same-thread rules
- whether **Launch Eval** scenarios are required
- Composio eligibility layer from ADR-0128
- credential model if Composio Connected Accounts are used per ADR-0129

## Example: later email send

A future governed email reply tool might be defined as `toee_email_send.send_reply` with verified-thread gating and signature rules before any Composio Gmail toolkit call is wired behind the adapter.

## Prohibited paths

- enabling a Composio toolkit in production and exposing it directly to agents
- auto-syncing Composio marketplace tools into profile allowlists
- adding vendor-specific parameters to public tool schemas because Composio exposes them

Spikes may explore Composio toolkits in development branches, but production promotion still requires the ADR-first sequence.

**Considered options:** Composio-first rollout (rejected—bypasses Tool Gate and eval design); permanent shadow-toolkit-only Composio use (rejected—blocks legitimate implementation acceleration); marketplace auto-sync (rejected—uncontrolled agent capability expansion).
