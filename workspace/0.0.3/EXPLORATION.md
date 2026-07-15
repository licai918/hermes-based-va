# 0.0.3 — Exploration (NOT a PRD)

- **Status:** exploration only. A holding space for what **0.0.2 deferred**, plus a
  **live scratchpad** for ideas that surface while building 0.0.2. Nothing here is
  committed scope; each item graduates to a PRD only after a brainstorm.
- **Builds on:** 0.0.2 (govern + harden — [EXPLORATION](../0.0.2/EXPLORATION.md),
  branch `feat/0.0.2-memory-governance`). 0.0.1 shipped Customer Memory (PR #54).
- **Date opened:** 2026-07-14 (at 0.0.2 kickoff)

---

## How to read this

Same convention as 0.0.2's exploration: each candidate is sized (XS/S/M/L) and
carries the trade-off, not a decision. Most of these were written up in full in
0.0.2's EXPLORATION.md — this file carries the **essence + why it landed in 0.0.3
+ a link**, so we don't duplicate. The **likely 0.0.3 headline is the knowledge
layer** — the one big capability 0.0.2 deliberately deferred so it gets a full
spike → PRD cycle instead of being rushed.

**Candidate index**
1. Knowledge layer (gbrain vs in-house retriever) — *capability* (L) — **likely headline**
2. Write-guardrail "propose → confirm" (option D) — *governance* (L)
3. Customer Memory retention sweep — *compliance* (M, conditional)
4. Connection pooling — *scale* (M, conditional)
5. Cross-channel memory continuity (email / voice) — *capability* (M, conditional)
6. Transparency & control — *privacy* (M) — *only if not taken as a 0.0.2 stretch*
7. Effectiveness instrumentation — *measurement* (S–M) — *only if not taken as a 0.0.2 stretch*

---

## Candidate 1 — Knowledge layer (the deferred headline) — L

**Why deferred from 0.0.2:** it is the one big new *capability* (L), needs
pre-commit spikes, and carries external-dependency risk — 0.0.2 kept it out so it
gets a real spike → PRD cycle rather than being rushed.

**The core decision (unchanged):** Path X (gbrain — pgvector + hybrid retrieval,
large external dep) vs Path Y (in-house BM25 retriever over `brain/` markdown,
fully owned). The 0.0.2 exploration leaned **Path Y (BM25 first)**.

**Hard gates before committing (spikes):** p95 in-turn retrieval **< 800 ms**;
precision@3 acceptable on ~30 real questions; knowledge index in a **separate DB**
(no PII). In-turn = retrieved **cited chunks**, never synthesized answers.

**Full writeup:** [0.0.2 EXPLORATION, Candidate 2](../0.0.2/EXPLORATION.md)
(boundary, driver seam, `brain/` taxonomy, authoring flow, ADR deliverables).
**Size:** Path Y = M, Path X = L; spikes = half a day–2 days.

## Candidate 2 — Write-guardrail "propose → confirm" (option D) — L

**Why deferred:** 0.0.2 ships the lightweight **A+B+E+NFR-3** guardrail; **D**
(the draft agent *proposes*, a rep *Accepts* in the preferences panel, and only
then it persists as `employee_confirmed`) is the governance-faithful north star,
but L-sized and reuses S16–S18.

**Promote to 0.0.3 if:** UAT of the 0.0.2 autonomous-write path feels loose — D
makes "can the LLM write autonomously" moot by construction.

**Full writeup:** [0.0.2 EXPLORATION, Candidate 1 → "the correct version (D)"](../0.0.2/EXPLORATION.md).

## Candidate 3 — Customer Memory retention sweep — M (conditional)

Condition-gated on corpus volume. Provisional slots accumulate (every unmatched
caller who states a preference); verified slots have no sweep either. ADR-0004/0116
define the policy; `created_at` / `last_interaction_at` columns exist. Ties to the
deferred Cloud Tasks / Cloud SQL slice (where the scheduled job runs).
**Full writeup:** [0.0.2 EXPLORATION, Candidate 3](../0.0.2/EXPLORATION.md).

## Candidate 4 — Connection pooling — M (conditional)

**Only pursue if load testing shows it matters.** 0.0.1 opens ~2–3 Postgres
connections per turn, no pool. Fine at SMS volume; a scaling cliff later. Ties to
the Cloud SQL / Cloud Run slice.
**Full writeup:** [0.0.2 EXPLORATION, Candidate 6](../0.0.2/EXPLORATION.md).

## Candidate 5 — Cross-channel memory continuity (email / voice) — M (conditional)

Verified memory already follows a customer across channels (binds to
`shopifyCustomerId`); **provisional** memory is per-channel. As email (ADR-0083/
0123) and a shared SMS/voice identity (ADR-0013) ship, define how those turn paths
read+inject memory, and whether provisional memory merges across linked channel
identities (0.0.1 parked cross-channel provisional merge as an ADR-0112 non-goal).
Gated on which channels actually ship. **Size:** M per channel.
**Full writeup:** [0.0.2 EXPLORATION, Candidate 8](../0.0.2/EXPLORATION.md).

## Candidate 6 — Transparency & control — M  *(only if not a 0.0.2 stretch)*

Customer-facing "what do you remember about me?" + clear; supervisor view/audit of
a customer's memory + change history (pairs with 0.0.2's `source` distinction);
wire memory into data-deletion. Grows into a real privacy/compliance surface.
**Full writeup:** [0.0.2 EXPLORATION, Candidate 7](../0.0.2/EXPLORATION.md).

## Candidate 7 — Effectiveness instrumentation — S–M  *(only if not a 0.0.2 stretch)*

Aggregate the S11 per-turn observability: injection rate, slots-populated
distribution, merge/correction rate; a lightweight dashboard/report; an eval/UAT
rubric for "did the reply honor the preference." Tells us whether memory *helps*
before investing more. **Full writeup:** [0.0.2 EXPLORATION, Candidate 9](../0.0.2/EXPLORATION.md).

---

## Tech debt / carried forward

Populate as 0.0.2's reviews surface debt it does not fix. Seeds:
- Any item from 0.0.2 Candidate 5 (cleanups) that ends up **descoped** — move it
  here (the `honor_injected_preference` eval fix and the `no-unprompted-recall`
  scenario are currently **in** 0.0.2 scope; only land here if descoped).
- **CI provisions no Postgres** — the datastore/E2E acceptance gate is enforced
  locally only, not in CI (flagged in the 0.0.1 UAT sign-off). Belongs to the
  Cloud slice.
- **§6.4 audit-model wording divergence** — slot metadata + a dedicated
  merge-audit table + structured logs, vs the PRD's literal `workbench_audit_log`
  wording. Already on record (S13/S14).

## Live scratchpad — 0.0.2 dev spillover

Dump ideas here the moment they surface while building 0.0.2, so they are not lost;
triage at 0.0.3 kickoff. Format: `(date) one-line idea`.

- (2026-07-14) opened — nothing yet.

---

## Explicitly parked (not 0.0.3 unless promoted)

- External memory providers (mem0 / honcho — rejected in 0.0.1).
- Any change to how **live facts** are served (stay real-time Shopify/QBO reads).
- Synthesis-mode knowledge retrieval **in-turn** (latency + grounding risk).
