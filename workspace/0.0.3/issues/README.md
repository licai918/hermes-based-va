# 0.0.3 — Land all of 0.0.3 — issue slices

Fine-grained slices of [../PRD.md](../PRD.md) (8 tracks: knowledge L5, Conversation Simulator,
propose→confirm, email+merge, transparency, L6, measurement, hygiene). Each slice is
independently implementable and reviewable, names its own acceptance, and carries the
**three-layer gate** (NFR-1): ① technical ② browser E2E (create the entry if missing) ③ owner
PAC in the simulator — with the NFR-1 carve-out for pure-refactor slices.

**Numbering is iteration-scoped** (0.0.3 S-numbers; 0.0.2 had its own S01–S20 — different list).

## Dependency graph

```
T2 sim:   S01 sender-gate ─▶ S02 ingress BFF ─▶ S03 sim UI ─▶ S04 presets/reset ─▶ S05 link-identity
T1 know:  S06 knowledge DB ─▶ S07 ingestion ─▶ S08 hybrid retriever ─▶ S09 driver+deadline ─▶ S10 turn wiring
                             S07 ─▶ S11 admin corpus panel      S08/S09 ─▶ S12 gates harness (+knowledge ADR)
T3 p→c:   S13 S20-reversal (+ADR) ─▶ S14 proposal envelope ─▶ S15 proposal UI ─▶ S16 proposal audit surface (after S20)
T4 email: S01 ─▶ S17 email pipeline ─▶ S18 sim email switcher (after S03)     S17+S05 ─▶ S19 cross-channel merge (+ADR)
T5 trans: S20 supervisor audit view      S21 customer self-service
T6 L6:    S22 experience store ─▶ S23 learning loop ─▶ S24 confirm-gate UI ─▶ S25 injection+eval-pin (+L6 ADR)
T7 meas:  S26 metrics panel (after S10/S15/S21/S25 counters exist)    S27 judge tuning [independent]
T8 hyg:   S28 retention sweep   S30 CI Postgres   S31 debt XS pair   [independent]
          S29 pooling — after S06/S09 (knowledge-DB site exists) + S03 (parallel-sim load test)
Final:    S32 knowledge final gate (S12 + owner questions) ─▶ S33 product UAT + PAC sign-off (after ALL)
```

Suggested sequence: **S01→S05 and S06→S12 in parallel first** (the simulator is the acceptance
surface for everything else; knowledge is the longest pole) → S13→S16 → S17→S19 → S20/S21 →
S22→S25 → S26/S27 → S28–S31 anywhere → S32 → S33.

## Slices

| ID | Title | Size | Delivers |
| --- | --- | --- | --- |
| [S01](S01-simulated-reply-sender-gate.md) | `REPLY_SENDER=simulated` composition gate (skip Textline, mirror to message_turn, fail-closed) | S | FR-10, NFR-4 |
| [S02](S02-simulator-ingress-bff.md) | Simulator ingress BFF: flat-JSON webhook + legacy HMAC → gateway; reply read-back from message_turn | M | FR-9 |
| [S03](S03-simulator-ui-page.md) | Simulator page + nav entry (thread view, composer, case link, role gating) | M | FR-8, FR-12 |
| [S04](S04-identity-presets-reset.md) | Identity presets (verified / unknown / ambiguous) + reset / new-conversation controls | S | FR-9, FR-13 |
| [S05](S05-link-identity-control.md) | "Link identity" control (simulated verified ingress → Identity Graph link) | S | FR-13 |
| [S06](S06-knowledge-db-productionize.md) | Knowledge DB productionized: `toee_knowledge` migrations, `KNOWLEDGE_DATABASE_URL` lazy seam | S | FR-1 |
| [S07](S07-shopify-ingestion-job.md) | Shopify-connector ingestion job (pull→chunk→embed→index, idempotent, **boundary-check report**) | M | FR-2, NFR-3 |
| [S08](S08-hybrid-retriever.md) | Hybrid retriever: FTS + local embedding (fastembed) + RRF fusion, top-k with provenance | M | FR-3 |
| [S09](S09-knowledge-driver-deadline.md) | Governed driver via `extra_drivers` + `knowledge_enabled()` + **driver deadline → found=false** + log sanitization | M | FR-4, NFR-5 |
| [S10](S10-knowledge-turn-wiring.md) | Knowledge on both turn surfaces (external + copilot draft), grounded-chunks discipline | S | FR-5 |
| [S11](S11-admin-corpus-panel.md) | Admin knowledge corpus panel: status (docs/chunks/last-ingest) + re-ingest action | M | FR-6 |
| [S12](S12-knowledge-gates-harness.md) | Gates harness: recall@3 runner + **hybrid in-turn p95 re-run (FR-7b)**; reports on admin; **knowledge ADR** | M | FR-7, FR-7b, NFR-8 |
| [S13](S13-s20-reversal.md) | S20 reversal: drop draft-turn write overlay; update tests + re-record eval artifacts; **reversal ADR** | M | FR-14, NFR-2, NFR-6, NFR-8 |
| [S14](S14-proposal-envelope.md) | Structured proposal envelope: draft turn emits `proposals[]` → agent-turn API → BFF | M | FR-15 |
| [S15](S15-proposal-ui-accept-dismiss.md) | Proposal UI in preferences panel: Accept (governed dispatch write) / Dismiss; audit records | M | FR-16, FR-17 |
| [S16](S16-proposal-audit-surface.md) | Proposal-history section on the supervisor view (dismissals visible) | S | FR-17 |
| [S17](S17-minimal-email-pipeline.md) | Minimal email pipeline: channel generalization, simulated email ingress, Email Sender Match, email turn + memory injection, reply mirror | L | FR-18 |
| [S18](S18-simulator-email-switcher.md) | Simulator channel switcher (SMS / email) | S | FR-11 |
| [S19](S19-cross-channel-merge.md) | Cross-channel provisional merge: policy + implementation + merge audit; **merge ADR** | M | FR-19, NFR-2, NFR-8 |
| [S20](S20-supervisor-audit-view.md) | Supervisor memory audit view: slots + write history (source/actor/time) + attributed clear | M | FR-20 |
| [S21](S21-customer-self-service.md) | Verified-only self-service: safe summary + governed clear + unverified deflection | M | FR-21, NFR-2 |
| [S22](S22-agent-experience-store.md) | `agent_experience` store (status + `kind` note\|procedure) + governed tool + injection scan | M | FR-23, NFR-3 |
| [S23](S23-learning-loop.md) | Learning loop: post-copilot-turn review pass (fork pattern), operational-only proposals | M | FR-22, NFR-3 |
| [S24](S24-l6-confirm-gate-ui.md) | L6 admin review queue: Accept / Reject (reuses S15 interaction pattern) | M | FR-24 |
| [S25](S25-l6-injection-eval-pin.md) | Confirmed-entry injection (copilot; external **read-only** behind own flag) + eval pinning; **L6 ADR** | M | FR-25, FR-26, FR-27, NFR-5, NFR-6, NFR-8 |
| [S26](S26-metrics-panel.md) | Aggregate metrics + admin panel (incl. **honored rate**, proposal accept rate, knowledge found rate) | M | FR-28 |
| [S27](S27-judge-tuning.md) | Judge tuning: rubric + model option + labelled fixture set measuring judge precision/recall | S | FR-29 |
| [S28](S28-retention-sweep.md) | Retention sweep per ADR-0004/0116 classes + admin visibility (last run, per-class counts) | M | FR-30 |
| [S29](S29-connection-pooling.md) | Pooling at all 4 sites (dispatch, gateway store, per-turn drivers, knowledge DB) under parallel sim load | M | FR-31 |
| [S30](S30-ci-postgres.md) | CI provisions Postgres — datastore/E2E gate runs in CI | S | NFR-7 |
| [S31](S31-debt-xs-pair.md) | Debt XS pair: QBO link-check persona mirror + `_require_slot` consolidation *(NFR-1 carve-out: layer ① only for the refactor half)* | XS | FR-32, FR-33 |
| [S32](S32-knowledge-final-gate.md) | Knowledge final gate: recall@3 ≥ 80% on the ~30 real questions (tune-then-sign loop) | S | FR-7, PAC-10 |
| [S33](S33-product-uat-signoff.md) | Product UAT: owner runs PAC-1…9 in the simulator; sign-off doc | M | §6 product gate |

## Traceability — coverage check (no gaps)

**FR → slice (every FR maps):**
FR-1→S06 · FR-2→S07 · FR-3→S08 · FR-4→S09 · FR-5→S10 · FR-6→S11 · FR-7→S12+S32 · FR-7b→S12 ·
FR-8→S03 · FR-9→S02+S04 · FR-10→S01 · FR-11→S18 · FR-12→S03 (case link) · FR-13→S04+S05 ·
FR-14→S13 · FR-15→S14 · FR-16→S15 · FR-17→S15+S16 · FR-18→S17 · FR-19→S19 · FR-20→S20 ·
FR-21→S21 · FR-22→S23 · FR-23→S22 · FR-24→S24 · FR-25/26/27→S25 · FR-28→S26 · FR-29→S27 ·
FR-30→S28 · FR-31→S29 · FR-32/33→S31. *(FR-12 rides in S03: the case link is part of the sim
page; the copilot side needs no build — it is the existing workbench.)*

**NFR → enforcement:**
NFR-1 (three-layer gate) → every slice's Acceptance block; carve-out named in S31 ·
NFR-2 → S13/S19/S21 assert the ADR-0148 invariants + tripwire stays green ·
NFR-3 → S07 (boundary check), S22/S23 (operational-only + scan) · NFR-4 → S01/S02 ·
NFR-5 → S09 (deadline), S25 (skip-on-fail) · NFR-6 → S13 (re-record), S25 (pin) ·
NFR-7 → S30 · NFR-8 → ADRs ride S12 (knowledge), S13 (reversal), S19 (merge), S25 (L6).

**PAC → slice(s):**
PAC-1→S06–S12 · PAC-2→S01–S04 (+0.0.1 shipped path) · PAC-3→S13–S15 · PAC-4→S17–S19+S05 ·
PAC-5→S20+S16 · PAC-6→S21 · PAC-7→S22–S25 · PAC-8→S26+S27 · PAC-9→S28+S29 · PAC-10→S32 ·
all → S33 sign-off.

**User stories:** US1–7→S01–S05/S03 · US8–9→S07–S10 · US10→PAC-2 regression (S33) · US11–13→S21 ·
US14→S19 · US15–17→S13–S15 · US18→S10 · US19→S25 · US20–21→S20 · US22→S11 · US23→S24 ·
US24→S26 · US25→S28 · US26→S09 · US27→S12 · US28→S30 · US29→S13/S25 · US30→S29. **All 30 covered.**

**Audit findings (all 14 from the PRD's independent audit) land in:** finding 1→S12 · 2→S20/S21
(disposition recorded in PRD §T5) · 3→S07 · 4→S22 · 5→S25 · 6→S26 · 7→S20 (build on shipped
model) · 8→S13 · 9→S29 · 10→S05 · 11→S31 · 12→S12/S13/S19/S25 · 13→this README's numbering note ·
14→S16.

**Coverage check result:** FR-1…FR-33 + FR-7b ✓ · NFR-1…NFR-8 ✓ · PAC-1…PAC-10 ✓ · US 1–30 ✓ ·
all 14 audit findings ✓ · 4 ADRs assigned ✓. **No requirement is unslotted; no slice delivers
nothing.**
