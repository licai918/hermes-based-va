# Hermes Native Memory four-layer model with Customer Memory binding

> **Storage substrate superseded by ADR-0140.** The four-layer model, slot
> binding, and write-source rules still hold, but the system-of-record is the
> Toee Business Datastore (Postgres), not Hermes Native Memory. Hermes memory is
> conversation-only.

Tooe Tire **Hermes VA** partitions **Hermes Native Memory** into four layers. The repository does not create a parallel preference database.

## Layer 1 — Identity Graph

Stores channel identities, **Session Identity Snapshot** records, Shopify and cross-system customer links, consent such as **SMS Opt-Out**, match history, and cross-channel identity relationships.

## Layer 2 — Conversation layer

Stores long-lived **Customer Thread** and **Email Thread** records, inbound and outbound turns, bounded **SMS Session** windows, and **AgentTurnContext** bindings for gateway execution.

## Layer 3 — Operational layer

Stores **Follow-up Case** records, **Workbench Audit Log** entries, auto-handled interaction evidence, eval metadata, and related operational workflow state.

## Layer 4 — Customer Memory

Stores structured service preferences bound through the **Identity Graph**:

- when **Verified Customer** is known, bind to `shopifyCustomerId`
- when the sender is **Unmatched Caller** or **Ambiguous Phone Match**, bind provisionally to `channelIdentityId` with `provisional: true` until a verified link exists

**Customer Memory** holds durable service preferences such as contact-time preference, channel preference, delivery-habit notes, and communication-style notes. It does not store live order, invoice, balance, or payment facts; those remain tool reads. It does not store operational policy text or model-guessed account facts.

Consent state such as **SMS Opt-Out** remains in the **Identity Graph**, not **Customer Memory**.

Reads and writes use official **Hermes Native Memory** APIs through the **Hermes Runtime Shim**. Toee Tire defines schema slots and binding rules only.

**Considered options:** store preferences only inside conversation-thread summaries (rejected—weak cross-session reuse and poor verified-customer merge); create a separate PostgreSQL preference table (rejected—conflicts with ADR-0026); treat STOP consent as a preference slot (rejected—consent belongs in the Identity Graph).
