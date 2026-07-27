# 0.0.5 — Complete the memory architecture — issue slices

Fine-grained slices of [../PRD.md](../PRD.md) (6 tracks: L7 lexicon, lifecycle core, boundary
enforcement, memory-ops UX, latency, Memory Control Loop). Each slice is independently
implementable and reviewable, names its own acceptance, and carries the **three-layer gate**
(0.0.3 convention): ① technical ② browser E2E ③ owner PAC — pure-refactor/test-only
carve-outs named per slice.

**Numbering is iteration-scoped** (0.0.5 S-numbers; 0.0.3/0.0.4 had their own lists).
**Moving targets:** ADR ~0155+ / migration ~0020+ — re-verify at every land time.
**Precondition:** 0.0.4 fully merged (incl. quality-feedback Phase 1: tables 0018/0019).
**The ONE owner input:** S24 (knowledge final gate) needs the owner's ~30 real questions.

## Dependency graph

```
T1 lexicon:  S01 store+propose+scan ─▶ S02 decide/CRUD+console ─▶ S15 (inbox absorbs queue)
             S01 ─▶ S03 normalizers+seeded domain ─▶ S05 deterministic seam
             S01 ─▶ S04 capture forks (+ADR-0152 note)
             S01 ─▶ S06 prompt seam + cross-layer precedence + eval pin
T2 lifecycle: S07 value history   S08 L4 value scan   S09 provenance ledger   S11 erase+tripwire
             S09 + S15 ─▶ S10 blast-radius review items
T3 enforce:  S12 tripwire tests [EARLY BIRD]
             S01 ─▶ S13 write-time advisories
             S01 + S15 ─▶ S20 graduation sweep + zero-hit retirement
T4 UX:       S01 ─▶ S14 Memory Hub
             S02 ─▶ S15 unified review inbox ─▶ S16 copilot triage annotations
             S02 ─▶ S17 NL manual-add prefill + fail-review L4 prefill
T5 latency:  S18 instrumentation + SLO [EARLY BIRD] ─▶ S19 budget enforcement (on evidence)
T6 loop:     S21 judge legs ─▶ S23 eval families        S24 S32 knowledge gate [OWNER INPUT]
             S07+S08+S11 ─▶ S22 lifecycle metrics + memory-health strip + knob panel
             qf + S01 + S15 ─▶ S25 feedback aggregator ─▶ S27 edit-diff mining
             S09 + S21 ─▶ S26 score×ledger effectiveness (+stratified sampling)
             S25 + S26 ─▶ S28 loop-closure metrics
```

Suggested sequence: **S12 + S18 first (early birds), then T1 S01→S06 (the long pole) with T2
S07/S08/S09/S11 in parallel** → T4 S14→S17 → S10/S13/S20 → T5 S19 → T6 last (S21→S28), with
S24 whenever the owner's question set arrives.

## Slice index

| # | Slice | Size | Delivers |
| --- | --- | --- | --- |
| [S01](S01-lexicon-store-propose-scan.md) | `semantic_lexicon` store + governed propose tool + write scan | M | FR-1, FR-3(write) |
| [S02](S02-lexicon-decide-crud-console.md) | decide/CRUD actions + lexicon console | M | FR-3(decide), FR-8 |
| [S03](S03-normalizers-seeded-domain.md) | in-code normalizers + seeded domain #1 (tire/company/season) | M | FR-2 |
| [S04](S04-capture-forks-adr.md) | gateway-side capture fork + copilot fork routing + ADR-0152 note | M | FR-4 |
| [S05](S05-deterministic-seam.md) | per-handler param normalization + catalog verification | M | FR-5 |
| [S06](S06-prompt-seam-precedence-pin.md) | `<confirmed_lexicon>` glossary + cross-layer precedence + eval pin | M | FR-6, FR-7 |
| [S07](S07-value-history.md) | `preference_updated` audit rows + value history in supervisor view | S | FR-9 |
| [S08](S08-l4-value-scan.md) | L4 value injection scan (hard-reject) | S | FR-10 |
| [S09](S09-provenance-ledger.md) | injection provenance ledger (new table, both turn paths) | M | FR-11 |
| [S10](S10-blast-radius-items.md) | blast-radius affected-cases query + inbox review items | S-M | FR-12 |
| [S11](S11-whole-binding-erase.md) | whole-binding erase + deletion-success tripwire | S | FR-13, FR-14 |
| [S12](S12-tripwire-tests.md) | LAYER_OF_ACTION map + composition + boundary-matrix tests | S | FR-15, FR-16, FR-17 |
| [S13](S13-write-time-advisories.md) | lexicon-shape re-file annotation + cross-layer dedup | S | FR-18 |
| [S14](S14-memory-hub.md) | Memory Hub page (L1-L7 rows, live counts) | S | FR-21 |
| [S15](S15-unified-inbox.md) | unified review inbox + Re-classify | M | FR-22 |
| [S16](S16-copilot-triage.md) | copilot triage annotations (batch + on-demand) | M | FR-23 |
| [S17](S17-prefills.md) | NL manual-add prefill + fail-review L4 prefill | S | FR-24, FR-25 |
| [S18](S18-latency-instrumentation.md) | per-layer latency emits + SLO tiles | S | FR-26 |
| [S19](S19-budget-enforcement.md) | deadlines + fail-open + thread-pool parallelization | S-M | FR-27 |
| [S20](S20-graduation-zero-hit.md) | graduation sweep + zero-hit retirement feed | M | FR-19, FR-20 |
| [S21](S21-judge-legs.md) | misapplication + stale-use legs (advisory) + gating safety leg | S-M | FR-28 |
| [S22](S22-lifecycle-metrics-knobs.md) | conflict/pollution/deletion metrics + memory-health strip + knob panel | M | FR-34(lifecycle) |
| [S23](S23-eval-families.md) | preference-change / adversarial / deletion eval families | M | FR-29 |
| [S24](S24-knowledge-final-gate.md) | S32 fold-in: recall@3 ≥80% on the owner's ~30 real questions | S | FR-30 |
| [S25](S25-feedback-aggregator.md) | scheduled propose-only aggregator (N=3/M=3, routing table) | M | FR-32 |
| [S26](S26-effectiveness-scores.md) | score×ledger per-entry effectiveness + stratified sampling | M | FR-31 |
| [S27](S27-edit-diff-mining.md) | edit-diff mining → L6/L7 proposal shapes | M | FR-33 |
| [S28](S28-loop-closure-metrics.md) | feedback→proposal conversion + post-fix re-fail + honored trend | S | FR-34(loop) |

## Traceability — the gap audit

**FR → slice (every FR maps):**
FR-1→S01 · FR-2→S03 · FR-3→S01+S02 · FR-4→S04 · FR-5→S05 · FR-6→S06 · FR-7→S06(+S12 test) ·
FR-8→S02 · FR-9→S07 · FR-10→S08 · FR-11→S09 · FR-12→S10 · FR-13→S11 · FR-14→S11 ·
FR-15→S12 · FR-16→S12(+S06 extension) · FR-17→S12 · FR-18→S13 · FR-19→S20 · FR-20→S20(+S26
health-score merge) · FR-21→S14 · FR-22→S15 · FR-23→S16 · FR-24→S17 · FR-25→S17 · FR-26→S18 ·
FR-27→S19 · FR-28→S21 · FR-29→S23 · FR-30→S24 · FR-31→S26 · FR-32→S25 · FR-33→S27 ·
FR-34→S22(lifecycle)+S28(loop). **All 34 covered; no orphans.**

**NFR → enforcement:**
NFR-1 (three-layer gate) → every slice's Acceptance block; test-only carve-outs named in
S12/S21/S23 · NFR-2 (ADR-0148 invariants) → asserted in S01/S02/S07/S08/S11 acceptance +
existing tripwires re-run branch-wide · NFR-3 (propose→confirm absolute) → S04/S13/S16/S20/
S25/S27 all propose-only; knob changes admin-only in S22 · NFR-4 (eval determinism) →
S06/S09/S18 eval-neutral clauses; ONLY S21's safety leg gates · NFR-5 (never stall a reply) →
S09/S18/S19 fail-open clauses · NFR-6 (no-PII shared layers) → S01 scan, S08, S16 PII-suspect ·
NFR-7 (mock/PG lockstep) → S01/S02/S05/S08/S11 shared-resolver clauses · NFR-8 (docs with
decisions) → S04 (ADR-0152 note), S06 (L7 ADR), S22 (control-loop ADR section),
memory-layers.md updates named in S04/S06 · NFR-9 (catalog sync) → S01/S02 re-list the
post-S11 sync set; drift tests in every catalog-touching slice.

**PAC → slice(s):**
PAC-1→S03+S04+S05+S06 · PAC-2→S02(+S15) · PAC-3→S07+S10+S11 · PAC-4→S08+S23 ·
PAC-5→S14+S15+S16+S17 · PAC-6→S18(+S19) · PAC-7→S25+S28 · PAC-8→S24 · PAC-9→all (re-run
gates at each track close). **All 9 covered.**

**US → slice(s):**
US1→S02 · US2→S03+S05 · US3→S03+S06 · US4→S04+S15 · US5→S07 · US6→S08(+S23) · US7→S11 ·
US8→S10 · US9→S14+S15 · US10→S16 · US11→S17 · US12→S17 · US13→S18 · US14→S19 · US15→S12 ·
US16→S20 · US17→S20+S26 · US18→S25 · US19→S28 · US20→S24. **All 20 covered.**

**Deferred/rejected items re-verified in PRD §6** — none re-enter through any slice.

**Audit verdict: no gaps.** Every FR/NFR/PAC/US maps to at least one slice; every slice
delivers at least one FR; dependencies are acyclic; the single owner input (S24) is isolated
so it blocks nothing else.
