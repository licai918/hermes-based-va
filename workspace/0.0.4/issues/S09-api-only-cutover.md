# S09 — API-only cutover: delete the in-memory fallback

- **Milestone:** 0.0.4 — durable substrate
- **Track:** T1 API-only workbench
- **Size:** L
- **Depends on:** S07, S08
- **Delivers:** FR-1, FR-3, FR-4, NFR-4
- **Surface:** workbench `lib/auth`, `lib/gateway`, `lib/bff` + tests

## Goal

FR-1/FR-3 (grilled decisions 1–3): the four in-memory stores, the seed, and
the TS chat/draft stub are deleted; every BFF handler keeps only its
`...ViaApi` path; missing `HERMES_*_API_URL/TOKEN` fails closed at boot.
FR-4: BFF tests migrate to the HTTP-client seam with coverage parity.

## Approach

- Delete `lib/auth/account-store.ts`, `lib/gateway/store.ts`,
  `lib/gateway/knowledge-store.ts`, `lib/gateway/eval-store.ts`,
  `lib/gateway/seed.ts`; remove the store-or-api branches;
  `hermes-api-config` unset → boot-time error (clear message naming the
  missing vars), never a silent downgrade.
- Delete the TS chat fallback (`handleChat` template stub + `executeTool`
  mock path in `chat.ts` / `drafts.ts` / `messages.ts` / `deps.ts`); the
  agent-turn API is the only chat path. Local real replies need
  `OPENROUTER_API_KEY`; tests use the dispatch server's
  `scripted_completions` seam.
- Test migration: mock at `hermes-api-client` / `hermes-agent-client`.
  **Coverage parity ledger in the PR:** every store-seam assertion either
  re-asserted at the client seam or explicitly retired with the fallback.
- CI (NFR-4): the workbench suite runs against the API-only wiring; no test
  imports the deleted stores.

## Acceptance — three-layer gate

- **① Technical:** CI green; boot-time fail-closed test; parity ledger
  reviewed; grep-proof no store imports remain.
- **② E2E (browser):** full workbench walkthrough (login → copilot case →
  chat/draft via API → admin panels) with only dispatch servers + Postgres
  behind it; boot without config shows the fail-closed error; screenshots.
- **③ Product (PAC):** PAC-1 (with S10): restart the stack mid-session —
  account, lockout, claims survive.

## Out of scope

- Package deletion — **S11**. Orchestration — **S10**. Python keyless stub
  (PRD §6).
