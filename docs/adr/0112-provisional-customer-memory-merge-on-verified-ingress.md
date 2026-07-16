# Provisional Customer Memory merge on verified ingress

> **Storage substrate superseded by ADR-0140.** The provisional-merge rule holds;
> records live in the Toee Business Datastore (Postgres), not Hermes Native
> Memory.

> **Amended by [ADR-0148](0148-copilot-agent-source-actor-attribution-and-context-only-binding.md)**
> (2026-07-14, 0.0.2). The merge rule below is unchanged. Separately, the WRITE
> path's `internal_copilot`-only fallback onto a model-supplied
> `channel_identity_id` param is removed: binding is now context-only on every
> profile, and an unresolvable identity always fails closed (`policy_blocked`).

**Customer Memory** records bound to `channelIdentityId` with `provisional: true` merge onto a verified customer node when **Ingress Phone Match** or equivalent ingress identity resolution first resolves the sender to a **Verified Customer**.

## Merge trigger

Merge runs during ingress identity processing when:

- the current channel identity newly resolves to exactly one `shopifyCustomerId`, or
- a new **SMS Session** re-resolves the sender to a **Verified Customer** per ADR-0043 and ADR-0019

**Ambiguous Phone Match** does not merge provisional preferences until the session identity becomes verified or is disambiguated through governed clarification flows.

## Merge behavior

When merge triggers:

1. read all provisional **Customer Memory** slots for the active `channelIdentityId`
2. upsert them onto the verified `shopifyCustomerId` node
3. if the same slot already has a value on the verified node, keep the verified value and record the provisional value in merge audit metadata
4. remove provisional copies after merge
5. write an **Identity Graph** merge record with `mergedAt`, source channel identity, and target `shopifyCustomerId`

## v1 non-goals

Cross-channel auto-merge of provisional preferences for two different channel identities is out of scope in v1 even if the **Identity Graph** later links them manually.

Employee correction of merged preferences still uses governed Copilot or explicit customer-service writes per ADR-0111.

**Considered options:** never merge provisional preferences automatically (rejected—verified customers would not benefit from earlier stated preferences); overwrite verified slots with provisional values on merge (rejected—too aggressive); require employee confirmation for every merge (rejected—adds friction to silent verification flow).
