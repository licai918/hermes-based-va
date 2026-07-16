# 0.0.2 — Memory Governance & Hardening — issue slices

Fine-grained slices of [../PRD.md](../PRD.md) (write-decision guardrail + carve-out
removal + hygiene). Each slice is independently implementable and reviewable and
names its own acceptance. Build order follows the dependency graph. Every FR / R /
RK / DoD gate maps to a slice — see **Traceability** at the bottom (no gaps).

## Dependency order

```
S05 SPIKE (eval copilot channel) ───────────────▶ S07
S03 (persona guard) ─────────────────────────────▶ S07 (copilot no-inferred)
S01 (source discriminator) ─┐
S02 (actor column) ─────────┼──────────────────▶ S11 (ADR) ─┐
S04 (remove carve-out) ─────┘                               │
S06 (LLM-judge component) ──────────────────────▶ S08 (honored/silent eval)
S09 (TS slot export)   [independent]                        │
S10 (swallow warning)  [independent]                        │
                        S01..S11 ─────────────────────────▶ S12 (UAT + sign-off)
```

Suggested sequence: **S05 (spike first)** → S01 → S02 → S04 → S03 → S09 → S10 →
S06 → S07 → S08 → S11 → S12. (S05 must resolve before S07 starts; write the R1/R2/R3
datastore assertions TDD-style alongside S01/S02/S04.)

## Slices

| ID | Title | Size | Delivers |
| --- | --- | --- | --- |
| [S01](S01-source-discriminator-copilot-agent.md) | Source discriminator: `copilot_agent` via `user_id` presence | S | FR-2, R1, RK-1, RK-2 |
| [S02](S02-actor-column-persist-user-id.md) | Actor column + persist the acting rep | S | FR-4, R2, NFR-1, RK-6 |
| [S03](S03-copilot-persona-write-guard.md) | Copilot draft-persona write-discipline guard | S | FR-1, RK-1 |
| [S04](S04-remove-channel-identity-carveout.md) | Remove the `channel_identity_id` carve-out + tripwire + test updates | S | FR-5, R3, RK-4 |
| [S05](S05-spike-eval-copilot-channel.md) | **SPIKE:** eval-harness Copilot-channel capability | S | RK-5 (gates S07) |
| [S06](S06-llm-judge-component.md) | LLM-judge component (advisory, injection-hardened, fixture-tested) | M | FR-3/FR-6 infra, R5, RK-3 |
| [S07](S07-copilot-no-inferred-eval.md) | Copilot no-inferred eval scenario (mechanical, hard gate) | S | FR-3, R4 |
| [S08](S08-honored-and-no-unprompted-recall-eval.md) | Honored-leg fix + no-unprompted-recall (judge-wired, advisory) | M | FR-6, R5, R6 |
| [S09](S09-ts-slot-single-source-export.md) | Single-source the preference-slot list on the TS side | S | FR-7 |
| [S10](S10-copilot-identity-lookup-warning.md) | Copilot identity-lookup swallow → PII-safe warning | S | FR-8 |
| [S11](S11-adr-governance-amendment.md) | ADR: `copilot_agent` source + actor column + carve-out removal | S | §5/§9, ADR |
| [S12](S12-product-uat-signoff.md) | Product UAT + PAC-1…5 sign-off | M | §6.5, §6.6 product gate |

## Definition-of-Done coverage (traceability)

**Functional requirements — every FR maps to ≥1 slice:**

| FR | Slice(s) |
| --- | --- |
| FR-1 draft-turn prompt guard | S03 (guard) + S07 (its eval) |
| FR-2 `copilot_agent` source | S01 |
| FR-3 no-inferred + judge | S05 (spike) + S06 (judge) + S07 (scenario) |
| FR-4 actor attribution | S02 |
| FR-5 remove carve-out | S04 |
| FR-6 honored/silent eval | S08 (uses S06 judge) |
| FR-7 TS slot export | S09 |
| FR-8 swallow warning | S10 |

**Correctness rules — every R maps to a slice at its level:**

| R | Slice(s) |
| --- | --- |
| R1 source discriminator | S01 (unit + datastore) |
| R2 actor persistence | S02 (datastore) |
| R3 carve-out removed | S04 (unit + datastore + tripwire) |
| R4 prompt-guard regression | S07 (eval) |
| R5 honored-leg genuine | S06 (judge) + S08 (wiring) |
| R6 no-unprompted-recall | S08 (eval) |

**Risks — disposition per slice:**

| RK | Slice / disposition |
| --- | --- |
| RK-1 soft prompt guard | S03 (mirrors proven rule) + S01 (label makes a slip visible) |
| RK-2 `user_id` mislabel | S01 (R1 unit pins the mapping) |
| RK-3 judge non-determinism / injection | S06 (advisory + injection-hardened) |
| RK-4 carve-out removal blast radius | S04 (tripwire + 3 test updates) |
| RK-5 eval harness copilot channel | S05 (spike gates S07) |
| RK-6 actor-column ALTER | S02 (nullable, no backfill) |
| RK-7 scope creep into option D | **out of scope** (0.0.3); no slice |

**§6.6 gates:**
- Technical gate → S01 / S02 / S04 / S07 / S08 + S11 (ADR); the removal tripwire is in S04; no-regression is asserted in each slice + confirmed at S12.
- Product gate → S12 (PAC-1…5, licai sign-off).

**Coverage check:** FR-1…FR-8 ✓, R1…R6 ✓, RK-1…RK-6 ✓ (RK-7 explicitly out of
scope), both DoD gates ✓. No requirement is unslotted.
