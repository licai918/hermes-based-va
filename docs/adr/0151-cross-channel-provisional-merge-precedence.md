# Cross-channel provisional merge precedence

> **Supersedes [ADR-0112](0112-provisional-customer-memory-merge-on-verified-ingress.md)'s
> v1 non-goal** (line "Cross-channel auto-merge of provisional preferences for
> two different channel identities is out of scope in v1"). 0.0.3 S19 (FR-19)
> implements it: see below. ADR-0112's merge trigger, merge behavior, and the
> "verified slots are never overwritten" invariant are otherwise unchanged.

**Status:** Accepted, 2026-07-20 (0.0.3, S19).

## Context

ADR-0112 merges a caller's pre-verification provisional Customer Memory slots
onto their verified record when ingress identity resolution first verifies
them. The merge trigger (`hermes-runtime/hermes_runtime/openrouter.py
_merge_provisional_memory`, called from `run_turn` before the turn-time memory
read) only ever pulled the **current turn's own channel** provisional key
(`_provisional_key_for`): a verified EMAIL turn merged `provisional:email:<addr>`
but never looked for an existing `provisional:sms:<E164>` for the same
customer, even after S05's Identity Graph link connected both channels to one
`shopify_customer_id`.

That is the FR-19 gap: "when the Identity Graph links a channel identity to a
verified customer (or two channel identities to each other), provisional
slots merge per a defined precedence... The SMS→email continuity path is
demonstrable" — a preference stated over SMS must be honored in a later
verified email conversation once the identities are linked.

## Decision

**Generalize the SOURCE-KEY SET the merge trigger enumerates, not the merge
unit of work.** `PostgresGatewayStore.merge_provisional_memory(provisional_key,
verified_key)` (the SQL: lock provisional rows, `INSERT ... ON CONFLICT
(binding_key, slot_name) DO NOTHING` onto the verified key, record
`overridden` conflicts, delete provisional, one audit row) is reused
**unchanged** — the trigger now calls it once per linked channel instead of
once for the current channel only.

### Enumeration

On a verified turn, a new read-only store method,
`PostgresGatewayStore.list_channel_identities_for_customer(shopify_customer_id)`,
returns every `(channel, channel_identity)` pair in `identity_link` pointed at
that customer — the mirror-direction query of the `_match` read the
`toee_identity_lookup` datastore handler already uses. It is a plain internal
store read, not a tool action: it returns Identity Graph structure (which
channels are linked), never customer content, and has exactly one caller
(the merge trigger). No catalog/mock-driver surface was added for it — the
production merge path only ever runs against `PostgresGatewayStore` (memory is
Postgres-only regardless of `TOOL_BACKEND`; see `memory_enabled()`), so there
is no second production backend to mirror. Existing/legacy test doubles that
don't implement the method degrade to single-channel behavior rather than
raising (`hermes_runtime.openrouter._linked_provisional_keys` uses
`getattr(store, ..., None)`), so no pre-S19 test file needed changes.

### Precedence

Both the current turn's channel and every linked channel may hold a
provisional value for the **same slot name**. Because `ON CONFLICT ... DO
NOTHING` lets the FIRST writer of an empty verified slot win, the ORDER the
trigger calls `merge_provisional_memory` in **is** the precedence:

1. **This turn's own channel first.** It is the just-stated, freshest signal
   — the customer is actively telling us something on the channel they are
   using right now.
2. **Every other linked channel next, in a fixed `(channel, channel_identity)`
   ascending order** — the order `list_channel_identities_for_customer`'s own
   `ORDER BY` already returns. Deterministic and reproducible: the same
   Identity Graph state always merges in the same order.

Deduped: a channel that is both "this turn's own" and separately present in
`identity_link` merges exactly once.

**Considered and deferred:** per-slot recency (most-recently-*updated
provisional slot* wins, using `customer_memory_slot.updated_at`) was the
brief's suggested alternative. Rejected for v1 as unnecessary complexity: it
would require a second read (latest slot timestamp per candidate key) purely
to resolve an edge case — two *different* channels stating conflicting values
for the *same* slot name — that the fixed order above already resolves
deterministically, and that in practice is rare (most cross-channel merges
have no slot-name overlap at all; the SMS→email continuity scenario has none).
If a real conflict pattern emerges later, add a
`latest_activity_at`-ordered variant of the linked-channel list without
touching the merge unit itself — the trigger's precedence is entirely a
question of what order it calls `merge_provisional_memory` in.

### Dispositions (FR-19's other two cases)

- **Channel↔channel link with no verified customer.** `_merge_provisional_memory`
  already only proceeds when `binding_key_from_identity(identity)` resolves
  **kind `"verified"`** — an ambiguous or unmatched identity is skipped
  (ADR-0112, unchanged). Two provisional channel identities linked to each
  other with no `shopify_customer_id` yet have no verified key to merge onto,
  so this is a **no-op until one side verifies** — nothing to invent, nothing
  new to build. The moment either channel's next turn verifies, the
  now-linked-but-still-provisional sibling channel's slots are pulled in by
  the enumeration above, same as any other linked channel.
- **Verified↔verified consolidation** (two already-verified `shopify_customer_id`s
  turning out to be the same real customer) is **out of scope**, unchanged
  from ADR-0112: this merge only ever moves `provisional:*` rows onto a
  verified key, never merges two verified keys into each other.

## ADR-0148 invariants preserved

- `source = merged_provisional` is set only inside `merge_provisional_memory`'s
  own INSERT — the trigger loop never sets or overrides `source`, and it is
  never model-supplied.
- `actor_account_id` stays NULL on every merge row (the INSERT still omits the
  column) — cross-channel or not, a merge is a framework action, never
  attributed to a human actor.
- Binding stays context-only: the linked-channel enumeration is keyed off the
  turn's own resolved `verified` binding key, never a model-supplied param.
- An unresolvable identity still fails closed to no merge (`verified is None or
  verified[1] != "verified"` short-circuits before any store call).
- Verified slots are never overwritten: `ON CONFLICT ... DO NOTHING` is
  unchanged; a cross-channel test with a real slot conflict on the verified
  customer proves it (`test_verified_slot_is_never_overwritten_by_either_linked_channel`).

## Consequences

- One turn can now issue N merge calls (N = linked channels), each its own
  audit row — the S20 audit view keeps rendering merges with no change (the
  audit row shape is untouched; there are just more of them, one per source
  key, exactly as ADR-0112 already produced one row per provisional key).
- A merge failure on one linked channel no longer blocks the others: each
  source key's merge is independently idempotent and retried on the next
  verified turn (FR-7), so a partial failure this turn just means fewer merges
  fired, not a failed reply.
- No new tool action, no new catalog entries, no mock-driver twin: the
  enumeration is an internal implementation detail of the merge trigger.

**Considered options:** move the merge trigger into the link-identity handler
itself (rejected — S19's brief and ADR-0112 both anchor the trigger on the
*verified turn*, not the link event, so it composes with a manually-seeded
link and doesn't require a second call site); rewrite the merge SQL to accept
a list of provisional keys in one statement (rejected — the per-key call keeps
`merge_provisional_memory`'s existing idempotency/locking/audit-row contract
completely unchanged, and N is small — a handful of channels per customer at
most).
