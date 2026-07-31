# L7 Semantic Lexicon: governed domain language, its two application seams, and cross-layer precedence

> **Status: Accepted — implemented** (decided during 0.0.5, 2026-07-28). Closes the
> L7 Semantic Lexicon chain opened by S01
> ([migration 0020](../../hermes-runtime/migrations/0020_semantic_lexicon.sql), the
> governed store and write), S02 (the human decide gate + admin console), S03 (the
> in-code normalizers and seeded domain #1) and S05 (the deterministic tool-parameter
> seam). Ships on `feat/0.0.5-land-all`: S06 (FR-6/FR-7, NFR-1/3/4/5/6/8, PRD Track
> T1). This is the ADR that `memory-layers.md`'s L7 row, the store DDL and the
> 0.0.5 exploration all forward-reference.

## Context

L7 ("what the company's words mean") is the seventh and last memory layer. It holds
**domain language as governed data**: `TOEE` is `TOEE TIRE`; `2055516`, `205 55 16`
and `20555r16` are all `205/55R16`; in the winter window a bare tire size probably
means winter tires. Before L7 all of that rode on model guesswork — different
spellings reached different products, and a seasonal assumption was whatever the
model felt like that turn.

The chain to here:

- **S01** created the `semantic_lexicon` table (`UNIQUE(domain, surface_form)`, a
  status lifecycle `proposed|confirmed|rejected|retired`, three-valued provenance)
  plus the governed `toee_semantic_lexicon` tool and the write-side scan.
- **S02** added the human decide gate (confirm/reject/retire/edit/add) and the
  admin console. D7 pinned **in-place UPDATE** for edits, so an entry id is stable.
- **S03** supplied the two halves S01 left out: the **rules** (`parse_tire_size`,
  regex in code, never in a row) and the **vocabulary** (the seeded domain).
- **S05** built the **deterministic** seam: normalize a tool parameter, verify the
  result against the live catalog, and only then act.

This ADR decides the **other** seam — what happens to language that cannot be
parsed and verified — and the question S05's seam does not raise at all: **what
happens when two memory layers disagree.**

## Decision

### 1. Two application seams, graded by determinism

| Seam | Owner | What it does | Failure mode |
| --- | --- | --- | --- |
| Tool-parameter normalization (**hard**) | S05 | rewrites a parameter, verified against the live catalog | must not miss |
| `<confirmed_lexicon>` prompt glossary (**soft**) | S06 | puts confirmed vocabulary in front of the model | may miss; never asserts |

The glossary is the seam for everything determinism cannot reach. It is **read-only
and advisory**: nothing in it can assert a fact, and nothing in it is a tool call.

### 2. Only `confirmed` entries ever render, checked twice

`PostgresGatewayStore.load_confirmed_lexicon` filters `status = 'confirmed'`, and
`hooks.glossary_entries` re-checks the field rather than trusting its caller. A
`proposed` row is inert by construction (S01), a `rejected` one is dead, and a
`retired` one is switched off — the status lifecycle is the whole control surface,
which is why no slice needed to widen the table.

### 3. Bounded newest-20, as a NAMED constant (D16)

`tool_backend.LEXICON_GLOSSARY_LIMIT = 20`. Newest-decided first. It is a named
module constant from day one because S22's knob panel must render "glossary N" by
importing the name rather than hunting a literal, and because reading it from
deploy-time config later is then a one-line change. Per **D14** that knob moves by
**config commit, not an in-app action** — the panel displays, it does not mutate,
and the audit trail is git history.

Known ceiling, stated rather than implied: a `default_rule` row older than the
newest 20 confirmed entries falls out of the window and stops rendering.
Hit-**ranked** selection is S26's toggle and is the upgrade path.

### 4. TWO independent flags, both default OFF

`LEXICON_INJECTION` (copilot draft turn) and `LEXICON_EXTERNAL_INJECTION` (external
turn) — the S25-0.0.3 two-flag precedent, so the external read is disable-able
**without touching the copilot path** and vice versa. Both fail-closed: unset,
empty, or any value outside the explicit on-set is OFF.

**The eval pin (NFR-4).** The record/replay path sets neither flag, so it reads and
renders no lexicon entry and the recorded prompts stay byte-identical.
Two further, independent structural reasons the eval path cannot inject L7 even
with both flags forced on: `eval_record` calls `render_injection` with no `lexicon`
argument at all, and the copilot record path binds a scenario-scoped store with no
`load_confirmed_lexicon` method, which the fail-closed loader degrades to `None`.

### 5. `default_rule` conditions are evaluated AT RENDER, and a default is a QUESTION

The condition is resolved when the block is built, not when the row is written:
`current_season(today)` picks which seasonal rule applies, and a confirmed
`season=override` row beats the calendar (an admin pins the season from the console
with no deploy). **At most one seasonal line per domain renders**; the losing
season's row is not in the prompt at all.

The rendered line is an imperative:

> `- Seasonal default (tire, winter): ASK whether the customer wants winter tires,`
> `unless the customer's own preference says otherwise. A default is a question to`
> `raise, never an assumption to act on.`

S03 made `SeasonalDefault.confirm_required` a read-only property that is always
`True` — there is no constructor argument and no assignment that yields `False` —
so the confirm posture cannot be switched off in **data**. This ADR pins the other
half: **it must not be undone in RENDERING either.** The renderer therefore has no
branch on `confirm_required`; the confirm clause is unconditional. A customer who
wanted all-seasons and got quoted winters because the calendar said November is
exactly the failure both halves exist to make unreachable.

### 6. Cross-layer precedence: L4 beats L7 (FR-7)

A customer's own stated preference outranks a shared seasonal default. Not
"usually". Two independent mechanisms carry it, because either alone is a coin flip
on how a model reads a prompt:

- **Order.** Composition is Session Identity Snapshot (L1, unfenced) → Customer
  Memory (L4) → confirmed operational learnings (L6) → confirmed lexicon (L7). The
  glossary arrives after the customer's own words are already established.
- **Phrasing.** The glossary header says
  *"The customer's own stated preferences take precedence over every line below"*,
  and each default line carries FR-7's clause verbatim.

Both are tripwire-tested in `hermes-runtime/tests/test_memory_boundary_tripwires.py`
(the composer) and `test_l7_injection.py` (the wiring, through a real turn).

This is the render-time counterpart of the exploration's **L4 vs L7** boundary pin:
SCOPE decides which layer OWNS a fact; precedence decides which WINS when both
speak.

### 7. The render side of the fence-escape fix (D19)

`_render_memory` interpolated raw customer-authored slot values with no escaping, so
a value containing this module's own closing token at the start of a line **closed
the fence early** and put the rest of itself in the same unfenced region as the
framework-derived Session Identity Snapshot — where it reads as trusted narration
instead of untrusted data. A structural prompt-injection escape, not a semantic one,
so no "ignore previous instructions" pattern catches it.

`hooks._fence_safe` now neuters fence-delimiter tokens in **every** interpolated
value, on all three fenced blocks and the unfenced snapshot. The regex is derived
from `hooks.FENCE_TAGS`, so a fourth block cannot be added with an unescaped body by
accident. It is a no-op for any value with no token, which is what keeps the eval
prompts byte-identical.

**Defence in depth, and the honest boundary.** S01 made `scan_injection` hard-reject
these tokens on the write side, but only **L6 and L7 call it** — L4's write path does
not call it at all (wiring it is S08), and nothing rewrites rows that predate the
guard. The render side is what covers a value that is already stored, on every layer.

### 8. The provenance ledger's L7 seat rides L7's OWN flag (D4.1 as corrected)

`injection_ledger._LAYER_GATES[LAYER_L7] = _l7_injection_enabled` (either L7 axis).
Gating it on a global memory flag would have reproduced, one layer over, exactly the
hole the L6 fix closed: a deployment injecting the glossary with the memory backend
off would render L7 and record nothing.

The ledger records the **selected** rows, not the raw read — `hooks.glossary_entries`
is the single shared selector both the renderer and the ref builder use (NFR-7), so
a `default_rule` row for the season that is not current is never credited with an
injection it did not have.

## Consequences

**Deliberate residuals, named because a silent one is worse.**

- A confirmed `season=override` row is **consulted but not selected** — it is
  configuration, not vocabulary, and renders no line — so it earns no ledger row and
  S20's zero-hit sweep will read it as unused. Under-claiming is the residual D4.3
  accepts; over-claiming is what it forbids.
- `glossary_entries` is therefore **not idempotent**, and both turn seams hand
  `render_injection` the RAW store read rather than a pre-narrowed list.
- The glossary is soft. It may miss. That is the whole reason S05's seam exists.

**A shape change in `proposer_context` that consumers must not key off.**
Redaction can change the **shape** of `proposer_context`, not just its content. PII
in a KEY is redacted rather than rejected (D2 amendment 3), and a key that redacts to
`[redacted]` when a sibling already redacted to the same string is **suffixed**
(`[redacted] (2)`, then `(3)`, …) rather than overwritten. Dropping it would destroy
governance evidence with no trace, so the collision suffix is ugly on purpose. It is
recorded here because **S02 and S25 both read `proposer_context` and neither should
key off its keys** — a key is not stable across the write scan.

**No new tool, no new action, no migration.** L7's catalog surface landed with S01
and S02; this slice reads an existing table through an existing store and adds one
optional argument to a pure renderer. NFR-9 catalog-sync is untouched.

## Alternatives rejected

- **Render the glossary unbounded.** The prompt grows with the store, and the entries
  that matter get diluted by the ones that do not. Bounded newest-N now, ranked
  selection when there is real traffic to rank by (S26).
- **Let a `default_rule` state its default instead of asking.** This is the failure
  mode the layer is most likely to produce and the hardest to see in review: it reads
  as helpfulness. Rejected in data by S03 and in rendering by this ADR.
- **One flag for both turn paths.** The 0.0.3 S25 gap audit already settled this for
  L6: an operator must be able to disable the external read without touching the
  copilot path.
- **Escape only `</untrusted_customer_memory>`.** The tokens are a set, the set is
  going to grow, and the next block would have been added without an escape. The
  regex is derived from the tag tuple instead.
- **Reject fence tokens at render.** Rejecting means dropping a customer's stored
  preference at read time, with no audit and no way for them to know. Neutering the
  token leaves a visible trace and keeps the rest of the value.

## References

- [`workspace/0.0.5/EXPLORATION.md`](../../workspace/0.0.5/EXPLORATION.md) — the L1–L7
  scope map, the routing decision tree, and the three boundary pins.
- [`workspace/0.0.5/DECISIONS.md`](../../workspace/0.0.5/DECISIONS.md) — D4 (the ledger
  gate and its correction), D14, D16, D19.
- [ADR-0152](0152-l6-agent-experience-confirmed-injection-and-eval-pin.md) — the L6
  pattern this re-instantiates over a structured store.
- [ADR-0140](0140-business-datastore-system-of-record-hermes-memory-conversation-only.md) —
  the substrate.
- [`docs/architecture/memory-layers.md`](../architecture/memory-layers.md) — the layer
  map; L7's row flips to shipped with this ADR.
