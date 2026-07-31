# S04 — Capture forks (gateway-side + copilot routing) + ADR-0152 superseding note

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T1 L7 Semantic Lexicon
- **Size:** M
- **Depends on:** S01
- **Delivers:** FR-4
- **Surface:** gateway post-turn fork; copilot review-fork prompt; ADR docs

## ⚠ Pre-flight corrections — BINDING (see [../DECISIONS.md](../DECISIONS.md))

- **D2 amendment 3 — what your fork may put in `proposer_context`.** The shared write scanner now
  treats dictionary **keys** leniently: a PII-shaped key (`order_1234567890`, `2026-07-27`, an
  epoch stamp) is **redacted**, not rejected, so order and ticket ids in your context keys are
  safe. **Values are not.** An L6 `proposer_context` value carrying real contact details — a
  nested `{"case": {"callback": "+1 416 555 0199"}}` is the shape to watch — **still hard-rejects
  the whole `propose_experience` write**, and that is deliberate: L6 is a shared layer and
  NFR-6's entire point is that customer PII does not go into one. **Carry ids and refs, not raw
  contact details.** The debugging tell if you get this wrong is a `policy_blocked` citing PII
  while the `content` looks perfectly clean.
- **D0** — "the S23 fork pattern" in the Approach below is **S23-0.0.3**, not the 0.0.5 S23.
- Provenance is framework-derived from `ToolExecutionContext.dispatch_route` (S01). Your fork
  runs on the agent path, so its proposals are `conversation_confirmed` — you do not and cannot
  set that from a parameter, and there is a forged-parameter test that will catch an attempt.

## Goal

FR-4 (owner decision ①): customer-confirmed clarifications become `proposed` lexicon entries —
captured by a **gateway-side post-turn review fork** (internal infrastructure, INTERNAL
profile, single-tool restricted toolset). The external agent itself still writes NOTHING —
ships the **ADR-0152 superseding note** pinning the fork-vs-agent distinction. The existing
copilot review fork's prompt routes lexicon-shaped findings to `propose_lexicon_entry`. US4.

## Approach

- Port the S23 fork pattern to the gateway turn path: runs AFTER the reply, gated on its OWN
  default-OFF flag (eval determinism — the record/replay path never runs it), turn-resilient
  (fork failure never affects the already-sent reply), restricted to
  `[propose_lexicon_entry]`.
- Fork prompt: extract ONLY explicit confirm exchanges (agent asked "do you mean X?" →
  affirmative) into structured params; S14 discipline (governed RESULT, never prose); the S01
  scan is the backstop.
- Copilot fork (S23's): prompt addition routing lexicon-shaped learnings to the lexicon tool
  (existing L6 notes are NOT auto-rerouted — that is S13's annotate-only).
- ADR-0152 superseding note + memory-layers.md L7 capture note (NFR-8, same PR).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** scripted-fork tests — a confirm exchange yields a proposed entry
  (framework-extracted); a no-confirm transcript yields nothing; fork exception leaves the
  reply result intact; flag default-OFF proven on the record/replay path; live-PG persistence.
- **② E2E (browser):** simulator: customer confirms a clarification → the proposed entry
  appears in the console/inbox with the exchange as evidence; screenshot.
- **③ Product (PAC):** PAC-1's capture leg.

## Out of scope

- Any external-agent write capability (forbidden, standing). Inbox UI — **S15**.
