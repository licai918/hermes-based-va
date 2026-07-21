# Composio as an internal integration backend behind Domain Adapters

> **Storage substrate superseded by ADR-0140/0142.** The Composio-behind-adapters
> boundary is unchanged. Only the substrate changes: adapters write audit records
> to the **Toee Business Datastore** (Postgres), not **Hermes Native Memory**, which is
> conversation-only.
> Current direction → [`docs/architecture/memory-layers.md`](../architecture/memory-layers.md).

Tooe Tire may use the Composio CLI SDK and Composio toolkits as an internal HTTP and OAuth helper behind **Domain Adapter Tools**. Composio is not an agent-facing integration surface in **Hermes VA**.

## Agent-facing boundary unchanged

**Hermes Profile** tool allowlists, **Domain Adapter Tool Action** enums, **Tool Gate**, audit logging, field masking, and **Launch Eval** mocks continue to target Toee-owned tools such as `toee_shopify_read` and `toee_qbo_read` per ADR-0059 and ADR-0070.

The model must not call Composio toolkit tools directly. Composio schema names do not appear in profile allowlists, eval fixtures, or workbench BFF contracts.

## Allowed use

Composio may live inside `packages/domain-adapters` implementation code to:

- perform OAuth and connected-account setup for Shopify, QuickBooks, Square, and similar SaaS APIs
- invoke vendor REST operations that map onto existing v1 `action` enums
- accelerate later integrations by wrapping new Composio toolkits behind new governed `toee_*` tools

Each adapter still:

1. accepts only the fixed v1 `action` enum for that tool
2. runs **Tool Gate** before any outbound vendor call
3. shapes responses to Toee field-gating rules
4. writes audit records in **Hermes Native Memory**

## Forbidden use

- registering Composio tools on the Hermes tool surface for external or copilot profiles
- bypassing **Tool Gate** because Composio exposes a broader vendor API
- changing **Launch Eval** assertions to match Composio tool names or parameters
- routing Textline, Twilio, EasyRoutes, case management, customer memory, knowledge ops, or eval review through Composio as the primary integration path without a Toee adapter wrapper

## Relationship to ADR-0030

ADR-0030 rejected third-party MCP wrappers and unofficial Shopify/QBO shims as the agent integration path. Composio under this ADR is an implementation dependency inside Toee adapters, not a replacement for governed **Hermes Tools**.

## Upgrade and portability

Domain adapter public contracts stay stable if Composio is replaced by direct REST clients later. Adapter tests and **Launch Eval** mock layers depend on `toee_*` actions, not Composio SDK types.

**Considered options:** expose Composio toolkits directly to Hermes agents (rejected—breaks action enums, Tool Gate, and eval contracts); forbid Composio entirely (rejected—adds integration cost without architectural benefit); replace `packages/domain-adapters` with Composio-only configuration (rejected—EasyRoutes, Textline, and Toee-native tools still require custom adapters).
