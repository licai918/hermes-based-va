# Ingress-time silent phone match with session-scoped identity snapshots

**Phone Match Verification** is a backend identity resolution step, not a customer-facing verification ceremony. When Textline delivers an inbound SMS webhook, the **Channel Gateway** runs **Ingress Phone Match** synchronously through `toee_identity_lookup` before **Hermes Core** processes the message. By the time the agent turn begins, the current **SMS Session** already has a resolved identity outcome.

Customers never receive a separate "verify your identity" flow, one-time code, or pre-answer verification prompt. **Phone Match Verification** is complete from the sender phone number alone at message receipt.

## Session-scoped runtime state

Each **SMS Session** carries a **Session Identity Snapshot** with one of:

- **Verified Customer** — one Shopify Customer **Registered Phone** match
- **Unmatched Caller** — no Shopify match
- **Ambiguous Phone Match** — more than one Shopify Customer match

When a new **SMS Session** starts after **SMS Session Timeout**, the **Channel Gateway** runs **Ingress Phone Match** again and writes a fresh **Session Identity Snapshot**. This is backend re-resolution only; the customer does not repeat any verification step.

Within an open **SMS Session**, later inbound messages reuse the existing snapshot unless the gateway explicitly refreshes it after a policy-defined trigger such as opt-out handling.

## Identity Graph persistence

The **Identity Graph** in **Hermes Native Memory** stores:

1. **Channel identity** — Textline phone number, opt-out state, and cross-channel links
2. **Session Identity Snapshot** — per **SMS Session** outcome, matched Shopify customer id(s), and timestamp
3. **Match history** — prior session snapshots and audit records for **Copilot Workbench** read-only context

The **External Customer Service Profile** uses only the active **Session Identity Snapshot** for tool authorization. **Copilot Workbench** may read the full **Customer Thread** and historical identity records through **Case Thread Context**, but cannot change verification outcomes retroactively.

## Ambiguous and unmatched handling

**Ingress Phone Match** may resolve to **Ambiguous Phone Match** or **Unmatched Caller** immediately at message receipt. Hermes does not ask the customer to "verify" before answering general or public-catalog requests.

Disambiguation such as company name, order number, or invoice number is required only when the customer requests account-scoped facts and the current **Session Identity Snapshot** is ambiguous or insufficient. That is request clarification, not a standalone verification ritual.

**Considered options:** ask customers to confirm identity before every new **SMS Session** (rejected—adds friction and violates silent verification); carry prior-session **Verified Customer** state into a new session without re-lookup (rejected—stale authorization risk per ADR-0019); store verification only in agent memory without **Identity Graph** (rejected—Copilot and audit need durable records).
