# S12 — Product UAT: owner runs PAC-1…5; sign-off

- **Milestone:** 0.0.4 — durable substrate
- **Track:** Final gate
- **Size:** S
- **Depends on:** ALL (S01–S11)
- **Delivers:** PRD §7 product gate
- **Surface:** simulator + workbench; sign-off doc

## Goal

The owner exercises all five PACs end-to-end and signs off
`workspace/0.0.4/UAT-signoff.md` (0.0.3 convention).

## The five PACs

- **PAC-1 (T1):** restart the full stack mid-session — rep account, lockout
  state, case claims survive; boot without API config fails closed
  (screenshot).
- **PAC-2 (T2):** simulator SMS → kill turn worker before reply → restart →
  reply arrives exactly once (outbound-record skip visible).
- **PAC-3 (T2):** force retry exhaustion → dead-letter view → Replay as
  supervisor → audit shows the acting account.
- **PAC-4 (T2):** admin re-ingest runs on the background worker while a
  simultaneous simulator turn completes without added delay.
- **PAC-5 (T3):** TS packages gone, CI green, one-command dev-up yields a
  working workbench (PAC-1 flow re-run on the cleaned tree).

## Acceptance

- `UAT-signoff.md` records each PAC with evidence links/screenshots and the
  owner's accept/reject; rejects loop back to their slice before sign-off.
