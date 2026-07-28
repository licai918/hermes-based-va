# The memory control loop: lifecycle metrics, honest counts, and read-only knobs

> **Status: Accepted — implemented** (decided during 0.0.5, 2026-07-28). Ships on
> `feat/0.0.5-land-all`: S22 (FR-34a, NFR-1/3/8, PRD Track T6). Pairs with the
> **forgetting table** in
> [`memory-layers.md`](../architecture/memory-layers.md), which this ADR's
> decisions are the instrumentation half of.

## Context

Seven memory layers now write, read, inject, age out and get erased. Six slices
already emit the raw evidence: S07's differing-value overwrite audit rows, S08's
write-scan rejections, S09's injection ledger, S11's erase and its
deletion-success tripwire, S19's per-layer read-deadline skips, S26's per-entry
effectiveness. **None of it was on a page.** An operator could not answer "is
memory being corrected a lot?", "is anyone trying to poison it?", "when a
customer asks to be forgotten, does it stay forgotten?", or "how big is the
prompt glossary, actually?" without SQL.

FR-34a asks for the lifecycle half of that panel plus a per-customer
memory-health strip and a knob panel. Two things about that request needed
deciding rather than implementing, and one earlier tile needed correcting.

## Decision

### 1. Counts, not rates — because the denominators do not exist

FR-34a says "conflict **rate**" and "pollution **rate**". Nothing in the system
records how many L4 writes were *attempted*: a rejected write leaves a counter
row, an accepted one leaves a slot, and a no-op overwrite leaves nothing at all.
So a rate would need a denominator assembled out of whatever happens to be
countable — a percentage that reads as accuracy and is not.

**The panel renders counts, and each count says it is a lifetime total with no
denominator.** This is the same correction the honored-rate tile already carries
(components, not a bare percentage) and the reason S21's judge legs are rendered
as scored / undetermined / eligible rather than as one number.

If a rate is wanted later, the honest way to get one is a counter at the L4 write
site — a new emit seam, which this slice deliberately does not add.

### 2. A count travels with its scope as data

The wire type for every lifecycle number is `{key, label, detail, value}`, and
the BFF **refuses** a count arriving without `label` and `detail` rather than
rendering the bare number. This is S14's Memory Hub rule (`{label, value}`, so no
renderer can drop the caveat) extended with the field that matters most here:
`detail` states what is **deliberately not** in the number.

That field is load-bearing, because two components FR-34a names have no source in
shipped code:

- **queue conflict annotations** — S13's write-time advisories are not shipped;
- **poisoned retirements** — no L6/L7 retirement records a poisoning reason, and
  FR-20's retirement feed is not shipped.

Each says so at the count it belongs to. A component with no source at all
renders `null` → "Not recorded", never `0`: "nothing feeds this yet" and "it
happened zero times" are different facts, and this is the same rule S21 applied
to `no_stale_use`'s absent leg.

### 3. The privacy-deflection metric is a PROXY, and the label says so first

Owner decision ⑤. What the system can see is customers clearing their own
preference slots and administrators erasing whole bindings. What it cannot see is
a customer who complains by phone, in a review, or by simply leaving. The tile is
titled "(privacy-deflection PROXY)" and its detail names the gap rather than
implying the number is a complaint rate.

### 4. S19's layer drops are counted, not tiled as latency

S19 emits a `<metric>_skipped` row when the pre-turn read deadline drops a layer
from the prompt, and left the tile to this slice. It is **not** added to the
latency tile set: those are duration tiles judged against a budget, so a drop
count rendered there would report the deadline's own length as a p95, and a layer
nothing has ever dropped would read "Not yet measured" — the opposite of the
truth. It lands as one **count per injected layer** on the lifecycle block, with
the metric names derived from `skip_metric` and the existing metric→layer map
rather than restated.

The count is structurally 0 while `MEMORY_READ_BUDGET` is off (which is how it
ships, against measured evidence), and the detail says that too — otherwise a
permanent zero reads as "we never drop anything" rather than "the mechanism is
off".

### 5. The knob panel is READ-ONLY, and that is the decision (D14)

A panel that renders env-var names is not an audited config change path. Building
a toggle that looked mutable and was not would satisfy the letter of FR-34a and
lie to the administrator.

**0.0.5 records plainly that NFR-3's knob clause is satisfied by deploy-time
config only:** a knob moves by a code/config commit, and its audit trail is git
history. There is no in-app enforcement and no in-app mutation — the panel
renders no control that could produce one, and a test asserts the section
contains no interactive element. Every slice that speaks of "an audited config
change" in 0.0.5 means exactly this. The owner may instead fund a real governed
config action + audit row + config table; until then, honesty over a fake toggle.

**The panel imports its values; it never re-types them** (D16). A literal beside
a constant is a second source of truth that agrees the day it is written and
drifts afterwards. Two tests pin both halves: each rendered value equals its
constant, and the knob module's source contains no copy of one.

**The mock backend reports no knob values rather than copied ones.** The
constants are `hermes_runtime`'s and `toee_hermes` must not import back, so the
mock twin sends `null` and the panel says "not reported by this backend" — the
same posture the mock retention twin already takes with the ledger-prune window.
The alternative, a restated list pinned by an equality test, would put a copy of
every number in a second file, which is what D16 exists to prevent.

### 6. `LEXICON_SELECTION` stays a deploy-time, fail-safe knob

It is on the panel as the one knob whose *effective* value is resolved rather than
read (`newest` unless the environment says `health`). It is deliberately
**fail-safe**: any unrecognised value — a typo included — resolves to the shipped
`newest` behaviour rather than to an empty glossary. Making it a runtime toggle
would give an operator a one-click way to change what every prompt carries, with
no audit row behind it; that is precisely the ungoverned write surface D14
refuses. It stays a config commit, and the panel says which value is in force.

### 7. The Memory Hub's zero-hit tile now reads effectiveness (D22)

**Corrected in this slice.** The tile counted `status='confirmed' AND
hit_count = 0`. Its label was not false — it said "lifetime `hit_count` = 0" —
but the number was knowably misleading, because `hit_count` counts
**deterministic-seam applications** and the seam only ever applies `alias` and
`normalizer` rows. A `default_rule` renders into the prompt as an imperative ask
and is never "applied", so **it earns exactly zero hits for ever, however well it
works** — and every seasonal default sat permanently inside that count.

It now reads `entry_effectiveness`: an entry is unused when it has **no
deterministic-seam hit (lifetime) AND no prompt injection in the ledger's
retention window**. Both halves matter — an entry reaching prompts with no seam
applications is being used, and an entry with old hits and no recent injections
is exactly the retirement candidate. An entry whose health score did not survive
the BFF's scope/basis refusal is left out of the count rather than guessed at.

This is the same finding that would have made a literal `hit_count == 0`
retirement feed propose every `default_rule` in the system on day one.

### 8. The per-customer health strip composes existing reads

Slot ages, correction count and clear/erase history all come from the Memory
Audit payload the console already renders. Only **last-injection recency** needed
a query — one scalar off S09's ledger, on the cursor the audit read already
holds, scoped by layer **and** by exact slot ref (not a `binding_key || ':%'`
prefix, which a neighbouring key that merely starts the same way would satisfy).
No new table, no new action, no second connection on a read a supervisor is
waiting for.

Slot age is taken from the **oldest** slot, not the newest: the strip exists to
show when a preference has gone stale, and the newest would report the memory as
fresher than it is. Clears and erasures are shown apart rather than summed — a
customer who asked to be forgotten entirely must not disappear into a "2
deletions" total.

## Consequences

- The metrics page carries the whole lifecycle picture, and every number on it
  can be read correctly without knowing which slice emitted it.
- A conflict or pollution **rate** is not available and will not be until someone
  adds a write-attempt counter. That is stated on the panel rather than
  approximated.
- `MEMORY_READ_BUDGET` and `LEXICON_SELECTION` are now visible as the two
  behaviour-changing switches they are, with their effective values.
- **NFR-3's knob clause has no in-app enforcement.** Anyone reading "knobs move
  only by admin action" should read it as "by a commit an administrator makes",
  not as a gate the application checks.
- No new tool, action or migration: the lifecycle counts and the knob panel ride
  the existing `toee_metrics.get_aggregate_metrics` read, so NFR-9 catalog-sync
  has nothing to mirror and nothing here is LLM-callable.

## Alternatives considered

**Invent a denominator for the rates.** Rejected: every candidate (current slot
rows, audited writes, metric rows) measures a different population than "writes
attempted", and the resulting percentage would be read as accuracy.

**Restate the knob values in the mock twin, pinned by a full-equality test** —
the mechanism `empty_latency_metrics` uses. Rejected: it works for a handful of
tile labels, but it would put a second copy of ~17 tuned numbers in a file whose
whole job is to have no store behind it, and D16 exists because a second copy is
how the first one goes stale.

**A governed `set_knob` action with an audit row.** This is the honest version of
"audited config change path" and it is a real option — it needs a config table, a
precedence rule against the environment, and a catalog entry. It was not funded
for 0.0.5, and shipping a toggle without it would have been worse than shipping
none.
