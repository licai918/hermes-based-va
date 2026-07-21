# Composio eligibility by Domain Adapter tool for v1

> **Storage substrate superseded by ADR-0140/0142.** The Layer-3-never-Composio boundary
> holds in full. Only the substrate changes: Layer 3 tools read and write the **Toee
> Business Datastore** (Postgres) plus internal governance state, not **Hermes Native
> Memory**, which is conversation-only.
> Current direction → [`docs/architecture/memory-layers.md`](../architecture/memory-layers.md).

Composio may be used only as an internal implementation backend per ADR-0127. v1 adapters split into three layers by whether Composio is allowed behind the Toee tool contract.

## Layer 1 — Composio allowed as internal implementation

These SaaS integrations may call Composio toolkits inside `packages/domain-adapters` while preserving ADR-0070 tool names and action enums:

| Tool | v1 actions | Notes |
|------|------------|-------|
| `toee_shopify_read` | `get_order`, `list_customer_orders`, `search_products`, `get_product` | Adapter maps each action to one or more Composio Shopify calls, then applies **Tool Gate** field shaping from ADR-0061 |
| `toee_qbo_read` | `get_invoice`, `list_customer_invoices`, `get_ar_summary` | Adapter enforces verified customer and **Customer Email Link** gating from ADR-0062 before Composio QuickBooks calls |
| `toee_square_payment_link` | `send_payment_link` | Adapter enforces verified customer and same-thread rules before Composio Square calls |

## Layer 2 — custom direct integration required

These tools must not use Composio as the primary backend in v1:

| Tool | Reason |
|------|--------|
| `toee_easyroutes_read` | EasyRoutes is not a standard Composio toolkit target |
| `toee_textline_reply` | Textline is channel ingress/outbound with gateway-specific credentials and audit |
| `toee_identity_lookup` | Match rules for phone, email sender, and ambiguous outcomes are Toee-owned. Shopify customer reads inside this tool may still use Composio internally, but the tool contract and match logic remain in Toee code |

## Layer 3 — Toee-native, never Composio-backed

These tools read and write **Hermes Native Memory** or internal governance state. They do not delegate to Composio:

| Tool | Profiles |
|------|----------|
| `toee_case` | External |
| `toee_case_manage` | Internal Copilot |
| `toee_customer_memory` | External and Internal Copilot |
| `toee_knowledge_search` | External and admin reads |
| `toee_knowledge_ops` | Supervisor Admin |
| `toee_eval_review` | Supervisor Admin |
| `toee_workbench_read` | Internal Copilot and Supervisor Admin |
| `toee_workbench_admin` | Supervisor Admin |
| `toee_copilot_draft` | Internal Copilot |

## Later email channel

Future governed email send or read tools such as a Toee-owned `toee_email_*` adapter may use Composio Gmail or Outlook toolkits internally. Composio email toolkit actions must not be registered directly on **Hermes Profiles**.

## v1 delivery order

1. Implement Layer 3 and Layer 2 custom paths required for Text-First Launch
2. Implement Layer 1 adapters with either Composio or direct REST behind the same `toee_*` contract
3. Choose Composio concretely for a Layer 1 tool only when the adapter mapping and credential model are ready; direct REST remains a valid implementation behind the same public contract

**Considered options:** route every Composio-supported SaaS tool through Composio including identity lookup as an agent-visible Composio tool (rejected—breaks Toee match semantics); use Composio for EasyRoutes and Textline (rejected—no reliable toolkit or wrong integration boundary); direct REST only for all Layer 1 tools (rejected—valid but forfeits Composio acceleration without architectural benefit).
