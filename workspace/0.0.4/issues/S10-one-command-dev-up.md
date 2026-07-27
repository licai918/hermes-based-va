# S10 — One-command dev orchestration

- **Milestone:** 0.0.4 — durable substrate
- **Track:** T1 API-only workbench
- **Size:** M
- **Depends on:** S02, S04, S09
- **Delivers:** FR-5, NFR-5
- **Surface:** docker-compose + dev script + workbench README

## Goal

FR-5 (grilled decision 2): one command brings up the full local stack —
Postgres (+ knowledge DB), both dispatch servers, the gateway, both workers,
the workbench dev server — with seeded dev accounts, so the API-only
topology costs nothing daily. US8.

## Approach

- Extend docker-compose with the worker services (from S02/S04) and dispatch
  servers if not already composed; one dev script (root `package.json` or
  `scripts/`) that starts compose + workbench dev and waits for readiness.
- Seeded dev accounts via S08's bootstrap run on first up.
- Workbench README rewritten: this is THE local dev path; the old
  single-command in-memory story removed.

## Acceptance — three-layer gate

- **① Technical:** a from-clean-checkout script run reaches healthy state
  (documented smoke: login via API succeeds).
- **② E2E (browser):** fresh `dev up` → browser login → simulator round
  trip; screenshots.
- **③ Product (PAC):** NFR-5/PAC-1 — owner runs the one command and lands in
  a working logged-in workbench.

## Out of scope

- Cloud/deployment changes (local-first, ADR-0142).
