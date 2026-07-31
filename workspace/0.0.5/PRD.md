# PRD 0.0.5 — Complete the memory architecture: L7 lexicon, lifecycle governance, the Memory Control Loop

> Source: [`EXPLORATION.md`](EXPLORATION.md) (six candidates, ALL grill questions locked
> 2026-07-21 — every FR below cites its exploration section). Predecessors: 0.0.3 shipped
> L1-L6 + governance; 0.0.4 shipped the durable substrate (job queue, workers, scoring both
> arms, API-only workbench). **Numbering caution:** ADR ~0155+ / migration ~0020+ are moving
> targets — re-verify at each land time (qf lands 0018/0019).

## 1. Problem Statement

The memory architecture is designed to seven layers but only six are built, and the six run
open-loop: domain language rides on model guesswork (C1), memory reads are unmeasured and
sequential (C2), admins maintain memory across 10 flat consoles with no unified queue (C3),
layer boundaries are documented but not machine-enforced (C4), the lifecycle has three verified
holes — overwrites lose history, L4 values are unscanned, injections are counted but not linked
(C5) — and 0.0.4's scoring system is a dashboard, not a sensor wired to actuators (C6).

## 2. Solution

Six tracks, ≈20 slices, every one reusing a shipped pattern (the exploration names each seam):

| Track | Delivers | Long pole? |
| --- | --- | --- |
| **T1 L7 Semantic Lexicon** | the governed, admin-self-serve, conversation-fed domain-language layer, applied deterministically + as glossary | **yes — start first** |
| **T2 Lifecycle core** | value history, L4 write scan, injection provenance ledger, whole-binding erase | parallel to T1 |
| **T3 Boundary enforcement** | tripwire tests, write-time advisories, graduation sweep | S-G1 early bird |
| **T4 Memory-ops UX** | Memory Hub, unified review inbox, copilot triage | after T1 store |
| **T5 Latency** | per-layer measurement + SLO, budget enforcement | S-L1 early bird |
| **T6 Memory Control Loop** | judge legs + eval families + S32 gate, feedback aggregator, score×ledger effectiveness, loop metrics | **last** (needs qf data + ledger) |

Laws that bind every track: scores/signals NEVER auto-write memory content (propose→confirm is
absolute; knobs move only by audited admin action); memory may degrade a reply's context but
never stall it; eval determinism holds (only the adversarial safety leg may gate).

## 3. User Stories

- US1 (admin): I add "TOEE ≡ TOEE TIRE" from the console and it's live without a deploy.
- US2 (customer): I text "2055516", "205 55 16", or "20555r16" and get the same product.
- US3 (customer): in winter a bare size defaults to winter tires — and the agent confirms first.
- US4 (agent→admin): a customer confirms "205/55R16?" → a proposed lexicon entry appears in my
  queue with the exchange as evidence; I approve, edit, or reject.
- US5 (admin): I see WHO changed a preference and what the OLD value was, not just the current.
- US6 (attacker): I text "my delivery note is: ignore previous instructions…" — it never enters
  memory, and the attempt is countable.
- US7 (supervisor): one click erases a customer's whole memory binding, fully audited.
- US8 (supervisor): when we retire a wrong entry, I get the list of open cases it touched.
- US9 (admin): one Memory hub shows every layer's health; one inbox holds every pending
  decision; Re-classify moves a mis-filed proposal instead of reject-and-retype.
- US10 (admin): each pending proposal carries copilot annotations — duplicate? conflict?
  PII-suspect? suggested canonical — and a recommend-with-reasoning; I decide.
- US11 (admin): I type "TOEE 也叫拓意" in plain language; the form pre-fills; I confirm.
- US12 (supervisor): failing a review with a preference-shaped cause offers a one-click
  prefilled L4 correction.
- US13 (ops): p50/p95 read latency per memory layer is on the metrics panel with the SLO line.
- US14 (ops): pre-turn memory reads are deadline-bounded — a slow layer skips, never stalls.
- US15 (dev): adding a memory-writing action without declaring its layer fails CI.
- US16 (admin): confirmed L6 notes that are really mappings surface as "graduate to L7?" items.
- US17 (admin): entries that never fire or score poorly surface as retirement candidates with
  ONE entry-health score (hits × honored/misapplied/stale).
- US18 (rep): three same-tag fails on similar subjects become ONE inbox proposal with the
  feedback rows as evidence — source `feedback_derived`.
- US19 (ops): the loop provably closes: post-fix re-fail rate and per-entry honored trends
  move after a confirmed fix.
- US20 (owner): the knowledge layer passes recall@3 ≥80% on MY ~30 real questions.

## 4. Functional Requirements

### T1 — L7 Semantic Lexicon (C1 §§59-104, grill-locked)

- **FR-1 Store**: `semantic_lexicon` migration — id, domain, entry_kind, surface_form,
  canonical_form, status (proposed|confirmed|rejected|retired), provenance
  (admin_manual|conversation_confirmed), evidence, proposer_context, decider_account_id,
  decided_at, hit_count, timestamps; `UNIQUE(domain, surface_form)`.
- **FR-2 Entry kinds graded by determinism**: `alias` admin-free; `normalizer` regex in CODE,
  table toggles per domain (+params); `default_rule` structured condition→default→confirm.
  Seeded domain #1: tire-size normalizer, company aliases, season default (date-derived +
  admin-overridable rule row).
- **FR-3 Governed tool**: `propose_lexicon_entry` — INTERNAL-allowlisted only, reached through
  the fork's restricted toolset; S22-scanned on write; S14 result-extraction; admin decide/CRUD
  actions (approve/edit/reject/retire/manual-add) in `_AGENT_EXCLUDED_ACTIONS`; every decision
  audited; decider framework-derived. Draft-turn-inert pinning test (S25 pattern).
- **FR-4 Capture**: gateway-side post-turn review fork proposes from customer-confirmed
  clarifications (fork = internal infra, INTERNAL profile, single tool; the external agent
  itself still writes nothing) — ships the **ADR-0152 superseding note**. The copilot review
  fork's prompt routes lexicon-shaped findings to `propose_lexicon_entry`.
- **FR-5 Deterministic seam**: shared PER-HANDLER helper (`search_products`/`get_product`,
  mock + real twins) normalizes params via confirmed aliases + enabled normalizers; parsed
  sizes verified against the live catalog before assertion; process cache + version-bump.
- **FR-6 Prompt seam**: bounded newest-20 confirmed entries in a fenced `<confirmed_lexicon>`
  block; fail-closed; default-OFF on eval path. Upgrade to hit-ranked when FR-31 scores exist.
- **FR-7 Cross-layer render precedence**: L4 renders with override standing over L7 defaults;
  `default_rule` text carries "unless the customer's own preference says otherwise";
  composition order + phrasing tripwire-tested (C5 §5.4 locked rule).
- **FR-8 Lexicon console** (read+decide+manual-add), sibling of AgentExperienceConsole —
  absorbed into the T4 inbox for decisions, console remains the CRUD/detail surface.

### T2 — Lifecycle core (C5 §§5.1-5.7, gaps verified in code)

- **FR-9 Value history**: `_upsert_preference` writes a `preference_updated` audit row with
  `{old_value, new_value}`; supervisor view shows value-change history (closes verified gap 1).
- **FR-10 L4 value scan**: shared S22 scanner extended to L4 slot values, **hard-reject** for
  injection patterns; mock+PG lockstep (closes verified gap 2).
- **FR-11 Injection provenance ledger**: NEW table — per governed turn: turn/case ref × layer ×
  entry_id/slot for every injected memory item, both turn paths; grain supports
  turn×layer×entry join (C6 §6.6 clause); writes eval-neutral + fail-open (closes gap 3).
- **FR-12 Blast-radius repair**: ledger-driven affected-cases query; retiring/correcting an
  entry surfaces "N open cases touched" inbox review items; closed cases sampled, never
  auto-reopened.
- **FR-13 Whole-binding erase**: one governed action looping per-slot clears (per-slot audit +
  summary row); supervisor one-click; no new write primitive.
- **FR-14 Deletion-success tripwire**: cleared-and-stayed-cleared metric; re-appearance (a
  merge/proposal recreating an erased slot) alerts.

### T3 — Boundary enforcement (C4, four tiers)

- **FR-15 LAYER_OF_ACTION map + CI completeness test**: every memory-writing catalog action
  declares exactly one layer or CI fails.
- **FR-16 Injection-composition test**: ≤1 fence per layer, no unfenced memory content,
  FR-7 precedence order asserted.
- **FR-17 Boundary-matrix tests**: testable rows become tests (L5 ingest no-PII, L7 write scan,
  L4 binding tripwires); doc-only rows explicitly marked.
- **FR-18 Write-time advisories**: lexicon-shape heuristic on `propose_experience` →
  **annotate-only** "consider re-filing to L7"; cross-layer dedup annotations on both propose
  handlers.
- **FR-19 Graduation sweep**: scheduled job (S04 worker pattern) flags structurable confirmed
  L6 notes → "graduate to L7?" inbox items.
- **FR-20 Zero-hit retirement**: L7 hit_count + L6 usage feed retirement candidates (merged
  into FR-31's entry-health score).

### T4 — Memory-ops UX (C3, grill-locked)

- **FR-21 Memory Hub**: one page mirroring L1-L7 — status + live counts (pending, zero-hit,
  last ingest/sweep, found-rate) per layer, deep links to existing consoles; sits ABOVE nav.
- **FR-22 Unified review inbox**: L6 + L7 proposals, graduation items, blast-radius reviews,
  `persona_review` items — layer badges; Accept/Edit/Reject/**Re-classify**; L4 proposals stay
  in the copilot per-case panel.
- **FR-23 Copilot triage annotations**: scheduled batch + per-item on-demand; duplicate /
  conflict / PII-suspect / suggested-canonical + recommend(approve|reject)+reasoning; governed
  annotation field; ADVISORY only — never writes an entry. (The rejected alternative — admin
  read tools in a chat copilot — stays rejected, §6.)
- **FR-24 NL manual-add prefill**: free-text → copilot-drafted structured entry → form
  prefill → admin confirms.
- **FR-25 Fail-review L4 prefill** (owner ⑦): a supervisor fail-review with a
  preference-shaped cause offers a one-click prefilled L4 correction.

### T5 — Latency (C2, grill-locked)

- **FR-26 Instrumentation + SLO**: per-layer read-duration emits (eval-neutral,
  fire-and-forget) + p50/p95 tiles; recorded SLO **≤150ms p95 total pre-turn reads**.
- **FR-27 Budget enforcement** (gated on FR-26 evidence): deadlines + fail-open skip on
  non-L5 pre-turn reads; `ThreadPoolExecutor` parallelization of the independent loads with
  sequential fail-open fallback; optimize only what the histogram indicts.

### T6 — Memory Control Loop: eval + feedback (C5 §5.8 + C6, grill-locked)

- **FR-28 Judge legs**: misapplication + stale-use (advisory) join honored-rate; adversarial
  safety leg **gates** — any injected-instruction-obeyed = red, zero tolerance.
- **FR-29 Eval scenario families**: preference-change (B honored AND A unused), adversarial
  (S09 promoted), deletion/forget-me — recorded + replayed under the deterministic gate.
- **FR-30 S32 fold-in (owner ⑥)**: knowledge final gate — recall@3 ≥80% on the owner's ~30
  real questions. **The iteration's ONE owner input dependency.**
- **FR-31 Score×ledger effectiveness**: per-entry honored/misapplied/stale rates × hit_count =
  ONE entry-health score driving the retirement queue; injection-stratified sampling change to
  the S22 judge job.
- **FR-32 Feedback aggregator**: ONE scheduled propose-only job over both qf tables —
  watermark, cluster (tag × subject × correlation), thresholds start **N=3 / M=3**, routes per
  the Signal Routing Table (C6 §6.2) into EXISTING queues with `feedback_derived` source and
  feedback-row evidence.
- **FR-33 Edit-diff mining**: deterministic diff + clustering; LLM-assist only as fork-pattern
  advisory annotation; output = proposal drafts, never writes.
- **FR-34 Lifecycle + loop metrics**: conflict rate, pollution rate, deletion success,
  privacy-deflection proxy (honestly labeled, owner ⑤), feedback→proposal conversion,
  post-fix re-fail rate, per-entry honored trend; per-customer memory-health strip on the
  Memory Audit console; **knob panel** (glossary N, bounds, windows — read-only values +
  audited config change path).

## 5. Non-Functional Requirements

- **NFR-1 Three-layer gate** on every slice (technical / browser E2E / owner PAC); pure-refactor
  carve-outs named per slice.
- **NFR-2 ADR-0148 invariants everywhere**: framework-derived source/actor, context-only
  binding, fail-closed `policy_blocked`, removal tripwires stay green.
- **NFR-3 Propose→confirm is absolute**: no score, signal, aggregator, annotator, or sweep ever
  auto-writes/auto-retires memory CONTENT; knobs move only by audited admin action.
- **NFR-4 Eval determinism**: every new turn-reaching read/emit is eval-pinned or eval-neutral;
  the CI replay gate stays hard; ONLY FR-28's safety leg may newly gate.
- **NFR-5 Memory never stalls a reply**: every new read is deadline-bounded + fail-open; the
  ledger/metric writes are fire-and-forget.
- **NFR-6 Shared-layer content is operational-only/no-PII** (L6/L7): write scans + PII-suspect
  annotations; L4 PII stays bound to its customer only.
- **NFR-7 Mock/PG lockstep** via ONE shared resolver per new gate (the S15/S21 lesson).
- **NFR-8 Docs land with decisions**: L7 ADR + ADR-0152 superseding note + lifecycle/control-
  loop ADR ship WITH their slices; `memory-layers.md` (L7 row → shipped, decision tree,
  boundary rows, forgetting table) updates in the same PRs; numbering re-verified at land time.
- **NFR-9 Catalog-sync completeness**: new tools/actions mirrored across the post-S11 sync set
  (re-listed at first slice) + drift tests green.

## 6. Out of scope

Real email/SMS-provider work beyond what exists · persona CONTENT automation (persona_review
items are advisory-only; changes stay dev-edit + eval-re-record) · embedding/RAG synonym
learning · fine-tuning · org-wide erasure workflow (whole-binding erase is per-customer) ·
off-workbench digests (deferred: no provider) · supervisor chat copilot holding admin read
tools (REJECTED with reasoning, C3) · admin-editable regex (normalizers stay in code) ·
auto-write/auto-retire of any memory content (NFR-3) · relevance-ranked L6/L7 selection beyond
hit-ranking (revisit with real usage data) · true privacy-complaint intake channel (owner ⑤:
proxy until a business channel exists).

## 7. Acceptance (PAC) — three-layer gate per 0.0.3 convention

- **PAC-1 (T1)**: simulator: all three notations of 2055516 retrieve the same product; a bare
  size in winter defaults to winter tires AND the agent confirms before quoting; a confirmed
  clarification → proposed entry → admin approve → live with NO deploy; all audited.
- **PAC-2 (T1/T4)**: admin manually adds, edits, retires an entry from the console; hit counts
  visible; a rejected entry never applies anywhere.
- **PAC-3 (T2)**: change a preference → old→new history visible; retire a wrong entry → the
  open-cases-touched list appears; whole-binding erase leaves a complete audit trail.
- **PAC-4 (T2/T6)**: an injection-string "delivery note" is hard-rejected from L4 and counted;
  the adversarial eval family is green (and would go RED if an injected instruction were obeyed).
- **PAC-5 (T4)**: the hub shows every layer with live counts; the unified inbox clears L6+L7+
  graduation+blast-radius items with Re-classify working; triage annotations render; NL add
  pre-fills; fail-review prefill lands an L4 correction in one click.
- **PAC-6 (T5)**: per-layer latency tiles are live; the 150ms p95 SLO is met or its breach is
  visible on the panel.
- **PAC-7 (T6)**: three same-tag fails produce ONE evidence-linked inbox proposal; approving it
  moves the loop-closure metrics (post-fix re-fail, honored trend).
- **PAC-8 (T6, owner input)**: recall@3 ≥80% on the owner's ~30 real questions.
- **PAC-9 (all)**: CI replay gate + all governance tripwires green through every track.

## 8. Traceability (FR → draft slice)

| Slice | FRs | Track order |
| --- | --- | --- |
| S-A lexicon store+tool+console | FR-1,2,3,8 | T1 ① |
| S-B capture + ADR-0152 note | FR-4 | T1 ② |
| S-C dual-seam application + pin | FR-5,6,7 | T1 ③ |
| S-M1 value history + L4 scan | FR-9,10 | T2 |
| S-M2 provenance ledger | FR-11,12 | T2 |
| S-M5 whole-binding erase | FR-13,14 | T2 |
| S-G1 tripwire tests | FR-15,16,17 | T3 early |
| S-G2 write-time advisories | FR-18 | T3 (after T1) |
| S-G3 graduation sweep + retirement | FR-19,20 | T3 (after T4 inbox) |
| S-U1 Memory Hub | FR-21 | T4 |
| S-U2 unified inbox | FR-22 | T4 (after S-A) |
| S-U3 triage + NL add + fail-review prefill | FR-23,24,25 | T4 |
| S-L1 instrumentation + SLO | FR-26 | T5 early |
| S-L2 budget enforcement | FR-27 | T5 (on evidence) |
| S-M3 judge legs + lifecycle metrics + knob panel | FR-28, FR-34 | T6 |
| S-M4 eval families + S32 gate | FR-29,30 | T6 (owner input) |
| S-F1 feedback aggregator | FR-32 | T6 |
| S-F2 score×ledger + stratified sampling | FR-31 | T6 (after S-M2) |
| S-F3 edit-diff mining | FR-33 | T6 |
| S-F4 loop-closure metrics | FR-34 (loop half) | T6 |

20 slices. Early birds: S-G1 + S-L1. Long pole: T1. Last: T6.

## 9. Gap audit (exploration → PRD coverage walk)

Every exploration section and locked decision, mapped:

- **C1** §problem/§architecture/§seams/§capture/§governance → FR-1..8; acceptance sketch →
  PAC-1/2; ADR list → NFR-8. Grill adds (fork-only exposure, per-handler helper, inert test,
  catalog validation, newest-20) → FR-3,5,6. ✅ no orphan.
- **C2** facts/direction → FR-26,27 (measure-first preserved as the FR-27 gate); SLO ② and
  thread-pool lock → FR-26/27 text. ✅
- **C3** inventory/hub/inbox/copilot-assist + rejected alternative → FR-21..25 + §6; digest
  deferral → §6. ✅
- **C4** four tiers → tier 1 already shipped (stated), tiers 2-4 → FR-15..20. ✅
- **C5** 5.1→FR-10; 5.2→FR-28; 5.3→FR-9 (+forgetting table via NFR-8 doc plan); 5.4→FR-7/16
  (+ shipped rows stated); 5.5→FR-10/28/29 + pollution metric in FR-34; 5.6→FR-13/14;
  5.7→FR-11/12; 5.8→FR-28..34 metric set incl. per-customer strip + eval families; owner
  ④⑤⑥ placed. ✅
- **C6** 6.1 join→FR-31; 6.2 routing table→FR-32 (persona_review → FR-22 item kind);
  6.3 aggregator→FR-32; 6.4 mining→FR-33; 6.5 loop metrics→FR-34; 6.6 deltas (knobs,
  stratified sampling, effectiveness first-class)→FR-34/31; thresholds N=3/M=3→FR-32; ⑦→FR-25. ✅
- **Deliberate exclusions re-verified in §6** (each traceable to an exploration decision, none
  silently dropped). ✅
- **Residual risks carried forward** (named, not hidden): FR-30 blocks on the owner's question
  set; T6 thresholds are starting values pending Phase-1 distribution; ledger table design must
  be sized before S-M2 (grain clause in FR-11).

**Audit verdict: no gaps found — all six candidates, seven owner decisions, all board calls,
and both grill continuations are covered by FR/NFR/PAC/§6/§8.**
