# S24 — Product UAT: owner runs PAC-1…9; sign-off

- **Milestone:** 0.0.4 — land all seven
- **Track:** Final gate
- **Size:** M
- **Depends on:** ALL (S01–S23)
- **Delivers:** PRD §7 product gate
- **Surface:** simulator + workbench + live deployment; sign-off doc

## Goal

The owner exercises all nine PACs end-to-end and signs off
`workspace/0.0.4/UAT-signoff.md` (0.0.3 convention).

## The nine PACs

- **PAC-1 (T1):** restart the full stack mid-session — account, lockout,
  claims survive; boot without API config fails closed (screenshot).
- **PAC-2 (T2):** simulator SMS → kill turn worker before reply → restart →
  reply arrives exactly once (outbound-record skip visible).
- **PAC-3 (T2):** force retry exhaustion → dead-letter view → Replay as
  supervisor → audit shows the acting account.
- **PAC-4 (T2):** admin re-ingest runs on the background worker while a
  simultaneous simulator turn completes without added delay.
- **PAC-5 (T3):** TS packages gone, CI green, one-command dev-up yields a
  working workbench.
- **PAC-6 (T4):** live-data answers for an order, an AR/invoice, and a
  delivery question (cross-checked against Shopify/QBO/EasyRoutes); one
  backend broken → agent fails closed, invents nothing.
- **PAC-7 (T5):** integrations page all-healthy → break one → probe badges
  it within a cycle → in-app reconnect restores it, audited.
- **PAC-8 (T6):** a PR with the required replay gates green (SMS + email)
  plus the non-blocking real-model live-eval + judge advisory report; owner
  reads one report end-to-end.
- **PAC-9 (T7):** metrics panel shows honored-rate, self-service usage, L6
  confirmed entries as real values; QualityGatesPanel shows the latest
  report with timestamp; one number cross-checked against its source.

## Acceptance

- `UAT-signoff.md` records each PAC with evidence links/screenshots and the
  owner's accept/reject; rejects loop back to their slice before sign-off.
