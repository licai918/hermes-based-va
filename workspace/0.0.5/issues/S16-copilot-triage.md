# S16 — Copilot triage annotations (scheduled batch + on-demand)

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T4 Memory-ops UX
- **Size:** M
- **Depends on:** S15
- **Delivers:** FR-23
- **Surface:** background annotator job (fork pattern) + inbox rendering

## Goal

FR-23 (grill-locked: scheduled batch + per-item on-demand; the chat-copilot-with-admin-reads
alternative stays REJECTED): every pending proposal gets copilot annotations — likely-
duplicate-of X / conflicts-with Y / PII-suspect / suggested canonical form — plus
recommend(approve|reject) with one-line reasoning. ADVISORY only; the admin decides. US10.

## Approach

- The S23 fork pattern as a scheduled background job (S04-0.0.4 worker): for each pending item
  since the watermark, run a restricted internal pass whose ONLY write is a governed
  annotation field on the proposal row — never a decide, never content (NFR-3).
- On-demand button per item re-runs the annotator for that item.
- Default-OFF flag; eval path untouched; cost knob = batch size + schedule (documented).
- Deterministic S13 annotations and these LLM annotations render side-by-side, visually
  distinguished (heuristic vs copilot).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** scripted-annotator tests — a duplicate-ish pending item gets annotated with
  the reference + recommendation; annotator failure leaves items un-annotated and the job
  alive; annotation write is the ONLY write (proven); flag default-OFF.
- **② E2E (browser):** run the batch on seeded items → annotations + recommendations render in
  the inbox; the on-demand button refreshes one; screenshot.
- **③ Product (PAC):** PAC-5's triage leg.

## Out of scope

- Auto-decisions (forbidden). NL manual-add — **S17**.
