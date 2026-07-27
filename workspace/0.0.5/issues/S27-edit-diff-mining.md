# S27 — Edit-diff mining → L6/L7 proposal shapes

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T6 Memory Control Loop
- **Size:** M
- **Depends on:** S25
- **Delivers:** FR-33
- **Surface:** the aggregator's diff arm; optional advisory annotator

## Goal

FR-33 (C6 §6.4 — the deliberately-scoped hard part): mine the `sent_edited` stream (generated
snapshot vs sent text, the highest-volume signal) — deterministic diff + clustering first;
when M=3 similar same-span rewrites recur, emit the RIGHT proposal shape: repeated rewrites of
a surface form → an **L7 alias** proposal; repeated procedural rewrites → an **L6** proposal
(`feedback_derived`). LLM-assist is allowed ONLY as a fork-pattern advisory annotator whose
output is a proposal draft, never a write.

## Approach

- Deterministic core: span-diff each pair, normalize whitespace/casing, cluster by
  (span-similarity × recurring replacement); the L7-vs-L6 shape decision uses the S13
  lexicon-shape heuristic on the recurring replacement.
- Weighting per the qf volume note (implicit ≫ explicit — don't let one loud thumbs-down
  outvote thirty quiet edits).
- The optional LLM clustering assist runs as an S16-style annotation on the emitted proposal
  (suggested canonical/cluster rationale), default-OFF.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** unit — three drafts where reps consistently rewrite "X" to "Y" yield ONE
  L7 alias proposal (surface X, canonical Y, evidence = the three diffs); three procedural
  rewrites yield an L6 proposal; two similar diffs yield nothing; noise (unrelated edits)
  clusters to nothing; idempotent re-runs.
- **② E2E (browser):** seeded edited-sends → the mined proposal appears in the inbox with
  diff evidence; screenshot.
- **③ Product (PAC):** feeds PAC-7.

## Out of scope

- Any auto-write (absolute). Tone/persona diffs route per S25's table, not here.
