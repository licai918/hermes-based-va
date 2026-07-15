# S12 — Product UAT + PAC-1…5 sign-off

- **Milestone:** 0.0.2 — memory governance
- **Size:** M
- **Depends on:** S01–S11 (all engineering complete)
- **Delivers:** §6.5 product acceptance, §6.6 product gate
- **Surface:** UAT (no code)

## Goal

Prove the write-governance is **felt** — a supervisor can tell an AI-drafted write
from a rep's deliberate correction — and record licai's sign-off.

## Approach

Run a scripted UAT (evidence allowed) covering the §6.5 criteria:

- **PAC-1** honest audit — read a case's write-origin history (`source` + actor);
  an AI-drafted write is distinguishable from a rep correction.
- **PAC-2** no inferred writes on the Copilot path (transcript + the S07 eval).
- **PAC-3** no model-nameable keys — a draft emitting a phone/param cannot direct
  where a write binds (reasoning-trace review + the S04 tripwire).
- **PAC-4** genuine honored / silent signal — the advisory judge would go red if a
  preference were ignored; the agent stays silent about unraised preferences.
- **PAC-5** no regression to shipped memory — 0.0.1's PAC-1…7 still hold (read
  injection, merge, isolation, degradation).

## Acceptance

- PAC-1…PAC-5 accepted on evidence + a manual UAT review.
- Sign-off recorded (name = **licai**, date) in the PRD or the 0.0.2 release note.
- Both §6.6 gates (technical from S01…S11 + product here) checked → **0.0.2 done**.

## Out of scope

- Option D propose→confirm UAT — 0.0.3 (promoted only if the guarded autonomous
  path feels loose).
