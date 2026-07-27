# S06 — Prompt seam: `<confirmed_lexicon>` glossary + cross-layer precedence + eval pin (+L7 ADR)

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T1 L7 Semantic Lexicon
- **Size:** M
- **Depends on:** S01 (S03 for meaningful content)
- **Delivers:** FR-6, FR-7
- **Surface:** render_injection composition; both turn paths; L7 ADR + memory-layers.md

## Goal

FR-6: bounded newest-20 confirmed entries rendered as a fenced `<confirmed_lexicon>` block on
both turns — fail-closed, default-OFF on the eval path (S25 discipline). FR-7 (grill-locked):
cross-layer render precedence — L4 carries override standing; `default_rule` text carries
"unless the customer's own preference says otherwise". US3's confirm behavior. Ships the
**L7 decision ADR** + memory-layers.md L7 row exploring→shipped (NFR-8).

## Approach

- `load_confirmed_lexicon(store)` mirror of `load_confirmed_experience` (bounded, fail-closed)
  behind **TWO independent default-OFF flags** — copilot + external, disable-able separately
  (gap-audit fix: locked now, the S25-0.0.3 two-flag precedent; recorded in the ADR).
- `render_injection` gains the lexicon block; composition order + precedence phrasing per the
  locked rule; **`default_rule` conditions are EVALUATED at render** (gap-audit fix — e.g.
  `current_season(date)` from S03 resolves which default applies; admin override row wins)
  and render with the confirm-required posture.
- Extend S12's composition test with the precedence assertion (FR-16 extension clause).
- Newest-20 now; the hit-ranked selection TOGGLE ships in **S26** (assigned, not orphaned).
- **memory-layers.md completion (gap-audit fix, NFR-8, same PR as the L7 ADR):** L7 row
  exploring→shipped, PLUS the L1-L7 routing decision tree and the L7 boundary-matrix rows
  from the exploration land in the map (the forgetting table lands with S22's ADR section).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** only confirmed entries render (proposed/rejected/retired excluded, both
  paths); flags default OFF on record/replay (replay suite green); load failure = skip, turn
  completes; precedence composition test green; L7 ADR file exists; memory-layers.md updated.
- **② E2E (browser):** with the flag on, a bare size in the current season draws the seasonal
  default AND a confirmation question; screenshot.
- **③ Product (PAC):** PAC-1's season/confirm leg.

## Out of scope

- Hit-ranked selection — post-S26. Effectiveness scores — **S26**.
