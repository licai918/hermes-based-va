# S19 — Email suite transcripts + CI gate

- **Milestone:** 0.0.4 — land all seven
- **Track:** T6 Eval completion
- **Size:** S
- **Depends on:** S18, S25 (CI topology)
- **Delivers:** FR-27
- **Surface:** `eval/transcripts/email_go_live/` + CI matrix; no product code

## Goal

FR-27: the email scenarios (`eval/scenarios/email/14–23`) get recorded
transcripts and `email_go_live` joins the CI replay matrix as a required
check — the email pipeline can no longer silently regress.

## Approach

- Record via the S18 harness in scripted mode over the simulated email
  ingress (0.0.3 S17 pipeline); review disclosures like the SMS suite.
- CI: add `--suite email_go_live` beside `text_first_launch` in the replay
  gate (required).

## Acceptance — three-layer gate

- **① Technical:** replay gate green on both suites in CI; a deliberately
  broken email assertion fails the pipeline (then reverted).
- **② E2E (browser):** CI run page with both suites green; screenshot.
- **③ Product (PAC):** feeds PAC-8.

## Out of scope

- Real email provider (PRD §6). `policy_publish` suite (still undefined —
  untouched).
