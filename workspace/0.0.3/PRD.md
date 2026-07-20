# PRD 0.0.3 — Land all of 0.0.3: knowledge, simulator, governance, growth

- **Status:** drafted from the grilled scope ([EXPLORATION.md](EXPLORATION.md) §"GRILLED SCOPE",
  8 locked decisions, 2026-07-20) + 2 seam confirmations (reply-sender gate, minimal email pipeline).
- **Architecture frame:** [docs/architecture/memory-layers.md](../../docs/architecture/memory-layers.md).
  Governance invariants of ADR-0148 hold everywhere. Spike evidence: [knowledge-spike/](knowledge-spike/).
- **Prior iterations:** 0.0.1 shipped L4 Customer Memory (PR #54); 0.0.2 hardened its governance
  (PR #55). This iteration lands **L5 (knowledge)**, **L6 (agent experience, mechanism)**, the
  **Conversation Simulator**, and the remaining exploration candidates.

---

## 1. Problem Statement

Toee Tire's VA can govern customer memory but still **knows nothing** (2-entry knowledge mock),
**cannot be exercised end-to-end** without real Textline traffic (no test surface — the owner
cannot role-play a customer or employee), **writes preferences autonomously** where governance
wants propose→confirm, is **blind to its own effectiveness** (no metrics, weak judge), leaks
scope at the edges (no retention sweep, no pooling, provisional memory trapped per-channel,
no transparency surface for supervisors or customers), and **never gets smarter with use**
(all Hermes learning mechanisms are off). 0.0.3 closes all of it, testably.

## 2. Solution

Eight tracks, one acceptance surface. Build the **Conversation Simulator** first — real
pipeline + simulated ingress — so every other track is provable from the front end by the
owner role-playing both sides. Then: the **L5 knowledge layer** (hybrid FTS+embedding over the
separate `toee_knowledge` DB, Shopify-sourced corpus); the **propose→confirm reversal** (draft
agent proposes, rep confirms); a **minimal email pipeline** + cross-channel provisional merge;
**transparency** (supervisor audit view + verified-customer self-service); the **L6 learning
loop** (Hermes's review-fork pattern, governed storage, confirm gate — validated on simulator
traffic); **measurement** (aggregate metrics + judge tuning); and **hygiene** (retention sweep,
connection pooling, tech debt). Every slice passes a three-layer gate: technical CI, browser
E2E (creating front-end entries where none exist), and owner PAC in the simulator.

## 3. User Stories

**Owner / tester (simulator)**
1. As the owner, I want to open a Conversation Simulator in the workbench and send an SMS as a simulated customer, so that I can test the real production turn pipeline without Textline.
2. As the owner, I want to pick an identity preset (verified customer / unknown caller / ambiguous match) and a fresh simulated phone number, so that each PAC scenario is reproducible.
3. As the owner, I want to see the agent's reply in the simulator thread (read back from the message store), so that the round-trip is visible without any real SMS being sent.
4. As the owner, I want a channel switcher (SMS / email) in the simulator, so that I can test the email pipeline the same way.
5. As the owner, I want to jump from a simulated conversation to its Human Intervention Case in the copilot view, so that I can role-play the employee side of the same conversation.
6. As the owner, I want to reset a simulated conversation and start a new one, so that state from one test never contaminates the next.
7. As the owner, I want every 0.0.3 feature reachable from some front-end entry, so that nothing is testable only by SQL or curl.

**Customer (external agent)**
8. As a customer, I want the agent to answer company/policy/product-education questions from real Toee Tire content with the source cited, so that answers are grounded, not invented.
9. As a customer, I want the agent to say it doesn't have an answer (rather than fabricate) when retrieval finds nothing, so that I can trust what it does say.
10. As a customer, I want my stated preferences remembered across conversations, so that I don't repeat myself. *(shipped 0.0.1 — regression-guarded here)*
11. As a verified customer, I want to ask "what do you remember about me" and get a short, safe summary, so that I know what's stored.
12. As a verified customer, I want to ask you to forget my preferences and have it actually happen (with an audit trail), so that I control my data.
13. As an unverified caller, I want memory self-service politely refused, so that my data can't be probed by whoever holds my phone number.
14. As a customer who moves from SMS to email, I want my provisional preferences to follow me once my identities are linked, so that channel switching doesn't reset the relationship.

**Rep (copilot)**
15. As a rep, I want the draft agent to **propose** memory writes instead of persisting them, so that nothing lands in customer memory without my confirmation.
16. As a rep, I want pending proposals rendered in the preferences panel with Accept / Dismiss, so that confirming is one click and my identity is attributed (`employee_confirmed` + my account).
17. As a rep, I want dismissed proposals to leave no memory trace (but an audit row), so that a bad guess can't quietly persist.
18. As a rep, I want the copilot draft grounded in the same knowledge corpus as the external agent, so that my drafts don't contradict the public site.
19. As a rep, I want the agent's learned operating notes (L6, confirmed only) applied to draft turns, so that the copilot improves as we use it.

**Supervisor / admin**
20. As a supervisor, I want a memory audit view per customer — slots, write history, `source`, `actor_account_id`, timestamps — so that "who changed this" is answerable in the UI, not SQL (closes the 0.0.2 PAC-1 caveat).
21. As a supervisor, I want to clear a customer's memory from that view (attributed + audited), so that deletion requests are honorable end-to-end.
22. As an admin, I want a knowledge panel showing corpus status (docs, chunks, last ingest) with a re-ingest button, so that knowledge refresh is an explicit, visible operation.
23. As an admin, I want an L6 review queue where the agent's proposed learnings sit until I confirm or reject them, so that the agent only "learns" what a human approved.
24. As an admin, I want a metrics panel (memory injection rate, honored rate, proposal accept rate, knowledge hit rate, merge/correction counts), so that we know whether memory and knowledge actually help.
25. As an admin, I want the retention sweep visible (last run, rows aged/deleted per class), so that ADR-0004 compliance is observable.

**Developer / CI**
26. As a developer, I want the retriever behind the existing `extra_drivers` seam with a driver-side deadline, so that a slow or dead knowledge DB degrades to `found=false` and never blocks a turn.
27. As a developer, I want ingestion/retrieval/gate harnesses as repeatable commands, so that the recall@3 gate can be re-run on demand.
28. As a developer, I want CI to provision Postgres so the datastore/E2E gate actually runs in CI, closing the 0.0.1 debt.
29. As a developer, I want the eval replay gate to stay deterministic (L6/memory pinned or excluded in eval), so that evolving memory can't flake CI.
30. As a developer, I want pooled connections in the dispatch servers and gateway store, so that parallel simulator load doesn't exhaust Postgres.

## 4. Functional Requirements

### T1 — Knowledge layer L5 (C1; decided Path Y-embed hybrid)
- **FR-1** Productionize the knowledge store: separate `toee_knowledge` DB (never the business DB), `knowledge_chunk` schema + FTS index, own migration path, `KNOWLEDGE_DATABASE_URL` env seam (lazy DSN, mirroring the datastore driver pattern).
- **FR-2** Ingestion: a repeatable job pulling pages / blog articles / shop policies from the **Shopify connector** (read-only; products/orders/PII excluded), HTML→text, chunk, embed, index. Idempotent re-ingest (truncate-and-reload is acceptable at this corpus size). **Boundary check at ingest** (audit finding 3): content that verbatim-duplicates a governed operational-policy slot or embeds live-fact patterns (prices/stock) is flagged into a human-review report, not silently indexed — enforcing the L5 boundaries table. *(Authoring/review-gate governance beyond this lint — who edits Shopify vs who reviews — is recorded as an open ADR question for the knowledge ADR, not silently decided.)*
- **FR-3** Hybrid retriever: lexical FTS + dense embedding (local model via fastembed/onnx — no torch, no per-call cost, queries stay local) fused by reciprocal-rank; returns top-k chunks with title+url provenance.
- **FR-4** Governed driver: `search_public_site` backed by the retriever via `extra_drivers`, behind a `knowledge_enabled()` gate; **driver-side deadline** → governed `found=false` (no tool-call timeout exists in-repo — this wiring is mandatory); retrieval queries sanitized in knowledge-store logs; `search_operational_policy` untouched. *(Config naming: `knowledge_enabled()` must be named/documented so it cannot be confused with `memory_enabled()` (=L4) or Hermes's `memory.memory_enabled` (=agent notes) — the collision the architecture map warns about.)*
- **FR-5** Injection on both surfaces: the external turn and the copilot draft turn can call the tool and ground replies on retrieved chunks (in-turn = retrieved chunks, never synthesis).
- **FR-6** Admin knowledge entry (front-end): corpus status (doc/chunk counts, last ingest time, per-type breakdown) + a re-ingest action, on the existing `/admin/knowledge` surface or a sibling.
- **FR-7** Quality gate harness: labelled-question runner reporting recall@3; runs on the synthetic set during dev; **final gate = recall@3 ≥ 80% on the ~30 owner-supplied real questions** (PAC-10); if it misses, tune (fusion weights, chunking, model) and re-run before sign-off. Both the recall report and the judge report (FR-29) surface on the admin eval/metrics entry, so the gates are front-end-visible.
- **FR-7b** **Hybrid latency gate** (audit finding 1 — the spike's S-LAT measured the rejected FTS rung only; the escalation rule "re-run S-LAT for the selected rung" was never executed): measure the **hybrid retriever's** in-turn p95 — *including per-query embedding inference* — at projected corpus size; gate p95 < 800 ms, and verify the FR-4 deadline still degrades correctly around the slower path.

### T2 — Conversation Simulator (new; grilled decision 2)
- **FR-8** A workbench Simulator page + nav entry: conversation thread view, message composer, identity/channel controls. Route-group and role-gating consistent with ADR-0093.
- **FR-9** Customer-side SMS ingress: the simulator posts the **flat-JSON Textline webhook** (id / conversation_id / from / body / received_at / type) with the **legacy HMAC signature** (`TEXTLINE_WEBHOOK_SECRET`) to the real gateway — identity match, memory, knowledge, live model all run the production path. Identity presets: verified customer (a Shopify-matched number), unknown caller (fresh number), ambiguous match.
- **FR-10** **Simulated reply sender** (confirmed seam): a `REPLY_SENDER=simulated` composition gate — skips the real Textline POST, still mirrors the reply into `message_turn`; the simulator reads the reply from there. Production default remains the real sender; misconfiguration fails closed.
- **FR-11** Channel switcher: SMS / email; the email option drives T4's ingress.
- **FR-12** Employee-side: a link from the simulated conversation to its case in the real copilot workbench (the copilot UI *is* the employee simulator — no parallel UI).
- **FR-13** Reset / new-conversation controls: fresh simulated identity or clean thread on demand, so PAC runs are repeatable without cross-contamination. Includes a **"link identity" control** (audit finding 10): simulate the ingress event that links the current simulated channel identity to a verified customer (or to another channel identity), so the FR-19 cross-channel merge is triggerable and observable from the simulator (PAC-4's E2E path).

### T3 — Propose→confirm (C2; S20 reversal CONFIRMED)
- **FR-14** Revert the draft turn's autonomous persist: the copilot draft turn no longer receives the datastore overlay for `toee_customer_memory` writes (reads stay governed). The 0.0.2 tests asserting the autonomous persist are updated deliberately, **and so are the eval-path artifacts** (audit finding 8): recorded scenarios exercising the draft-turn write are re-recorded against the propose-only contract; the no-inferred-write eval stays green; the `resolve_memory_write_source` unit seam keeps `copilot_agent` (the resolver mapping is unchanged — production simply no longer routes writes through it). The ADR recording the reversal ships with the build.
- **FR-15** Structured proposal envelope: the draft turn emits `proposals[]` (slot, value, evidence-turn) alongside `draft`; carried through the agent-turn API and BFF to the workbench.
- **FR-16** Proposal UI: the existing preferences panel renders pending proposals with **Accept / Dismiss**. Accept routes through the **existing** governed dispatch write (`upsert_preference`, actor-attributed → `employee_confirmed`). Dismiss persists nothing.
- **FR-17** Proposal audit: accepted/dismissed each leave an audit record (proposal, origin, decider, timestamp), **surfaced on the FR-20 supervisor view as a proposal-history section** (audit finding 14 — a dismissed proposal writes no slot, so slot history alone cannot show it).

### T4 — Minimal email pipeline + cross-channel merge (C5; confirmed scope)
- **FR-18** Minimal email pipeline, simulator-driven only (no real email provider): generalize the inbound channel type beyond `textline_sms`; an email ingress route accepting simulated inbound email ({from, subject, body}); **Email Sender Match** identity (ADR-0052/0054 semantics); an email turn running the same governed profile with memory read-injection; reply mirrored for the simulator; email-channel structural disclosures per existing eval rules.
- **FR-19** Cross-channel provisional merge: when the Identity Graph links a channel identity to a verified customer (or two channel identities to each other), provisional slots merge per a defined precedence (never overwriting verified slots — ADR-0112 invariant); merge audited; policy recorded as an ADR. The SMS→email continuity path is demonstrable in the simulator.

### T5 — Transparency & control (C6; supervisor + verified-only self-service)
- **FR-20** Supervisor memory audit view (admin surface): per-customer slots + full write history (`source`, `actor_account_id`, timestamps), with an attributed **clear** action. Closes the 0.0.2 PAC-1 caveat (the data shipped in 0.0.2; this is the UI + read BFF route).
- **FR-21** Customer self-service, **verified customers only**: "what do you remember about me" → customer-safe summary (slot values, no internal metadata); "forget me" → governed clear + audit; unverified callers receive a safe deflection. Both flows via governed tools on the external turn — no new write paths.
- **Deletion-honoring disposition** (audit finding 2 — C6's third possibility, resolved consciously): **no org-wide data-deletion process exists today to wire into** (SMS opt-out is consent state in the Identity Graph, not erasure). For v1, FR-20 (supervisor clear) + FR-21 (self-service clear) **are** the memory-deletion mechanism. Wiring into a future org-wide erasure workflow is out of scope (§9) and re-opens when one exists.

### T6 — Agent-experience memory L6 (C8; mechanism now, calibration post-launch)
- **FR-22** Learning loop: after a copilot turn, a bounded review pass (Hermes review-fork pattern, ported — not Hermes's own store) may emit **operational-learning proposals** (procedures, conventions, tool quirks — explicitly NOT customer facts/PII; the review prompt forbids person-specific data).
- **FR-23** Governed storage: an `agent_experience` store in the business datastore with `status` (`proposed` / `confirmed` / `rejected`), `source`, proposer context, decider + timestamp; injection-scanned on write (S09 discipline). **Decision recorded** (audit finding 4): v1 uses **one store** with a `kind` field (`note` | `procedure`) rather than Hermes's separate notes/skills stores — the volume doesn't justify two stores yet; the split is revisited in the L6 ADR when procedures outgrow flat entries.
- **FR-24** Confirm gate UI: an admin review queue listing proposals with Accept / Reject (reuses T3's proposal interaction pattern).
- **FR-25** Injection: **confirmed** entries only. Copilot draft turn first (build order); the **external turn also reads confirmed entries** — per the grilled decision's exact wording ("外部 agent 只读已确认条目": read-only over confirmed learnings, never proposing) — behind its own flag so it can be disabled independently. (Audit finding 5 resolved in favor of the grilled wording, not the PRD draft's stricter reading.)
- **FR-26** Eval determinism: L6 injection is pinned/disabled on the eval path; the replay gate stays green.
- **FR-27** Validation source: the mechanism is exercised with **simulator traffic**; the "observe a week of real proposals" calibration is explicitly deferred to post-launch (recorded in the ADR).

### T7 — Measurement (C7)
- **FR-28** Aggregate metrics + admin panel: memory injection rate, slots-populated distribution, **honored rate** (advisory, judge-sampled — the C7 core question "does the agent act on it"; audit finding 6), merge count, correction count, proposal accept/dismiss rate, knowledge `found` rate, self-service usage — computed from existing observability + new counters, rendered on an admin metrics entry. *(Which business outcome metric matters most — CSAT / handle time / repeat-contact — stays an owner question to answer during the iteration; the panel ships with the mechanical metrics regardless.)*
- **FR-29** Judge tuning: sharpened rubric/prompt, configurable stronger judge model, and a small labelled fixture set measuring the judge's own precision/recall (fixes the "2pm ETA vs after-2pm preference" conflation class); judge remains advisory, never gating.

### T8 — Hygiene (C3, C4, tech debt)
- **FR-30** Retention sweep (C3): a scheduled/manually-triggerable job aging out `customer_memory_slot` rows per ADR-0004/0116 classes (provisional vs verified windows); sweep results visible on an admin entry (last run, per-class counts).
- **FR-31** Connection pooling (C4): pooled Postgres connections at **all four connection sites** (audit finding 9): the dispatch servers, the gateway store, the **per-turn `extra_drivers` memory-driver connections** (C4's original motivation — ~2–3 connections per turn), and the new **knowledge-DB driver**; behavior verified under parallel simulator load.
- **FR-32** Copilot QBO link-check mirror (tech debt, XS): `_TOOL_PARAM_CONVENTIONS` documents the email-link-check workflow (`get_email_link_status` → `linked` before `get_invoice`/`get_ar_summary`).
- **FR-33** `_require_slot` near-duplicate consolidation (tech debt, XS).

## 5. Non-functional requirements

- **NFR-1 Three-layer gate on every slice:** ① technical (pytest/vitest, CI green); ② browser E2E from the front end, screenshot-evidenced, **creating a front-end entry if none exists**; ③ owner PAC in the simulator. All three green = done. **Carve-out** (audit finding 11): pure-refactor slices with no behavior change (e.g. FR-33) satisfy layer ① only, and must name the exemption in the slice; dev-harness outputs (FR-7 recall report, FR-29 judge report) satisfy ② via the admin panel that surfaces them.
- **NFR-2 Governance invariants (ADR-0148):** `source` / `actor_account_id` / binding keys are framework-derived, never model-supplied; unresolvable identity fails closed (`policy_blocked`); the removal tripwire stays green.
- **NFR-3 No PII in L5 or L6:** the knowledge DB carries no customer data; L6 entries are operational-only, injection-scanned, human-confirmed.
- **NFR-4 Simulator isolation:** simulated traffic never reaches real Textline (fail-closed reply gate), never uses a real customer's phone number, and simulator transcripts are never treated as real customer data.
- **NFR-5 Turn resilience:** knowledge retrieval and L6 injection degrade (governed `found=false` / skip) — the turn never fails on them; in-turn retrieval p95 must stay under the 800ms budget, **verified for the shipped hybrid rung by FR-7b** (the spike's 1.4ms measured the rejected FTS rung only — it is evidence the substrate is fast, not a certification of the hybrid).
- **NFR-6 Eval determinism:** the deterministic replay gate (ADR-0119) stays the CI hard gate; new capabilities are pinned/excluded there.
- **NFR-7 CI Postgres:** CI provisions Postgres so the datastore/E2E acceptance gate runs in CI (closes the 0.0.1 debt).
- **NFR-8 Doc maintenance:** per docs/agents/domain.md — ADRs shipped with builds: **the knowledge ADR** (records Path Y-embed hybrid + formally supersedes ADR-0001/0031's mechanisms + carries the authoring/review-gate question from FR-2), **the S20-reversal ADR**, **the cross-channel merge-policy ADR**, and **the L6 ADR** (one-store decision, operational-only rule, external read-only). Architecture map rows updated in the same PRs; glossary terms minted as they land (the dead-mechanism glossary supersessions already shipped 2026-07-20).

## 6. Product acceptance criteria (owner-tested in the simulator)

*PAC numbers are **iteration-scoped** (0.0.3 PAC-n). Prior iterations' PAC numbers (0.0.1
PAC-8 = grounded knowledge, 0.0.2 PAC-1 = supervisor attribution) are different lists — always
qualify cross-iteration references (audit finding 13).*

- **PAC-1 (knowledge):** as an unknown caller, ask a policy/brand/education question → grounded answer citing corpus content; ask something not in the corpus → honest "don't have that" (no fabrication).
- **PAC-2 (memory regression):** as a verified customer, state a preference; next simulated conversation honors it. (0.0.1 behavior, re-proven through the simulator.)
- **PAC-3 (propose→confirm):** draft agent proposes a preference from a copilot conversation; Accept persists `employee_confirmed` + actor (visible in the audit view); Dismiss persists nothing; **no autonomous draft-turn persist exists**.
- **PAC-4 (email + merge):** an email conversation reads the same memory; a provisional SMS preference follows to email after identity linking, per the merge policy.
- **PAC-5 (supervisor view):** the audit view answers "who wrote this slot, when, from where" for UI-, draft-, and merge-written rows; clear works and is audited.
- **PAC-6 (self-service):** verified customer gets a safe summary + honored deletion; unverified caller gets a deflection.
- **PAC-7 (L6):** a simulated copilot session yields a learning proposal; confirmed → visibly applied in a later draft turn; rejected → never applied.
- **PAC-8 (measurement):** the metrics panel reflects simulator activity; the judge fixture report shows the judge's own accuracy on the labelled set.
- **PAC-9 (hygiene):** retention sweep demonstrably ages seeded old rows per class; pooling holds under parallel simulator load.
- **PAC-10 (knowledge final gate):** recall@3 ≥ 80% on the ~30 owner-supplied real questions (tune-then-sign if missed).

## 7. Implementation decisions (seams — grounded 2026-07-20)

1. **Simulator ingress = the real webhook** (`POST /webhooks/textline`, flat-JSON + legacy HMAC). No bypass chat; the production pipeline is the thing under test. (Existing seam; a PS simulation script already proves the shape.)
2. **Reply egress = `REPLY_SENDER=simulated`** composition gate (confirmed): skip real POST, mirror to `message_turn`; simulator reads from the store. New, one-point seam in the composition root.
3. **Email = minimal new pipeline** (confirmed): generalize the channel literal, add a simulated-only email ingress; reuse the SMS pipeline shape end-to-end. Real provider integration is a later iteration.
4. **Retriever = `extra_drivers`** (existing, proven by L4): a knowledge driver behind `knowledge_enabled()`, deadline inside the driver.
5. **Proposal Accept = the existing governed dispatch write** (`upsert_preference` via BFF `dispatchWrite` with actor). No new write path; C2 and C8 share the propose→confirm interaction pattern.
6. **L6 storage = business datastore** (new governed table), NOT Hermes's `MEMORY.md`/state.db — we port the *loop*, not the *store* (ADR-0140 boundary intact; Hermes built-in memory stays off).
7. **Workbench surfaces:** Simulator under the authenticated copilot group; knowledge status, L6 review queue, metrics, sweep visibility under admin (route-derived profiles per ADR-0093).

## 8. Testing decisions

- Tests assert **external behavior at seams**, not implementation: webhook-in → reply-in-store (simulator path), tool-call → governed result (drivers), BFF route → dispatch payload (workbench), turn → persisted rows (datastore).
- **Prior art to follow:** 0.0.2's slice suites — driver unit seams (`hermes/tests`), datastore integration (`hermes-runtime/tests` with live Postgres), BFF route tests (vitest), eval replay fixtures, browser E2E via the built-in browser with screenshot evidence, and the removal-tripwire pattern for governance invariants.
- Each slice names its covering tests; the three-layer gate (NFR-1) is the slice's definition of done. E2E for backend-only slices goes through the nearest front-end entry (which the slice must create if missing — e.g. FR-6/FR-24/FR-28/FR-30 entries).
- The eval replay gate stays green throughout; recording sessions force mock backends (0.0.2 SECURITY discipline).

## 9. Out of scope

- **Voice** turn path (no substrate; parked).
- **Real email provider** integration (simulated ingress only this iteration).
- **gbrain** (rejected by spike) and any external vector-DB service.
- **Hermes built-in memory enablement** (`MEMORY.md`/state.db/session_search stay off; cross-profile recall stays locked out).
- **L6 proposing from the external turn** (only copilot turns generate proposals; the external turn is read-only over confirmed entries per FR-25) and **L6 real-traffic calibration** (post-launch).
- **Customer-facing web portal** for memory (SMS self-service only).
- Any change to **live facts** routing (always real-time Shopify/QBO reads).
- Cloud deployment changes (local-first per ADR-0142; CI Postgres is the only infra change).

## 10. Risks

- **RK-1** Real-question gate < 80% → tune-then-sign loop budgeted (fusion weights, chunking, short-doc handling); worst case the knowledge PAC extends past the other tracks.
- **RK-2** Owner inputs late (~30 questions, Shopify content gaps) → build proceeds; only PAC-10 blocks on them. Content gaps also cap achievable recall (hours/FAQ/payment are unanswerable until filled).
- **RK-3** S20 reversal churn: 0.0.2 tests asserting autonomous persist must be rewritten deliberately (not deleted); the reversal ADR prevents "why is this off" archaeology.
- **RK-4** Email pipeline scope creep → hard-fenced to simulated ingress; any real-provider work is a new iteration.
- **RK-5** L6 poisoning / PII capture → operational-only review prompt, injection scanning, human confirm gate, copilot-only injection; the S09 hardening is the floor.
- **RK-6** Simulator realism gaps (fake numbers, no real Textline quirks) → accepted: it tests our pipeline, not Textline's; live-channel smoke stays a launch activity.
- **RK-7** Live-model cost/nondeterminism in simulator sessions → acceptable for a test surface; eval remains the deterministic gate.
- **RK-8** Pool introduction changes connection semantics under concurrency → verified under parallel simulator load (PAC-9) before sign-off.

## 11. Traceability — completeness check (every grilled decision → requirement)

| Grilled decision / source | Lands in |
| --- | --- |
| G1 all 8 candidates | C1→T1 · C2→T3 · C3→FR-30 · C4→FR-31 · C5→T4 · C6→T5 · C7→T7 · C8→T6 |
| G2 simulator, real pipeline + simulated ingress | FR-8..13, NFR-4, seams 1–2 |
| G3 knowledge gate in parallel | FR-7, PAC-10, RK-1/RK-2 |
| G4 three-layer gate + entry rule | NFR-1, §8, entries FR-6/24/28/30 |
| G5 C2×S20 reversal | FR-14..17, PAC-3, RK-3, ADR (NFR-8) |
| G6 C8 via simulator | FR-22..27, PAC-7, RK-5 |
| G7 C5 email + merge, voice parked | FR-18..19, PAC-4, §9 |
| G8 C6 incl. verified-only self-service | FR-20..21, PAC-5..6 |
| Seam confirms (reply gate / email minimal) | FR-10 / FR-18, §7.2–7.3 |
| Tech debt: QBO mirror, `_require_slot`, CI Postgres | FR-32, FR-33, NFR-7 |
| Tech debt: §6.4 audit-model wording divergence | **Accepted as-is** (audit finding 7): FR-20's view builds on the shipped model (slot metadata + merge-audit table + structured logs); no schema change; the divergence stays on record from S13/S14 |
| Tech debt: 0.0.2 Candidate-5 cleanup seeds | **Verified shipped in 0.0.2** (S06–S08) — nothing was descoped; no carry-forward |
| 0.0.2 caveats: PAC-1 supervisor view, judge tuning | FR-20, FR-29 |
| Spike deliverables carried: deadline wiring, corpus source, content gaps | FR-4, FR-2, RK-2 |
| Doc-maintenance mechanism | NFR-8 |

**Check result:** the author's traceability pass was then **independently audited** (adversarial
fresh-context review against EXPLORATION, the spike docs, and the architecture map). The audit
found **4 gaps, 2 drifts, 3 ambiguities, 5 notes — all 14 resolved in this document** (marked
"audit finding N" inline): the hybrid latency gate (FR-7b), deletion-honoring disposition (T5),
ingestion boundary check (FR-2), the L6 one-store decision (FR-23), the external-read
interpretation corrected to the grilled wording (FR-25), honored-rate metric (FR-28), the §6.4
divergence row (above), eval-artifact scope of the S20 reversal (FR-14), pooling sites (FR-31),
the identity-link control (FR-13), the NFR-1 carve-out, the ADR list (NFR-8), PAC scoping note
(§6), and the dismissal audit surface (FR-17). Every candidate C1–C8, all 8 grilled decisions,
both seam confirmations, all tech-debt items, both 0.0.2 caveats, all spike "kept" deliverables
(including the escalation re-run rule), and every test-gate rule now map to a requirement;
intentional exclusions are in §9 with reasons.

## 12. Further notes

- **Build order intent** (dependency, not mandate): T2 simulator early (it is the acceptance
  surface for everything else) alongside T1 knowledge; T3 next (small, high-governance value);
  T4–T6 after (T6 reuses T3's pattern); T7–T8 fill in; PAC-10 last (owner inputs).
- **Owner's parallel inputs:** the ~30 real questions (gates PAC-10) and the Shopify content
  fills ([knowledge-spike/CONTENT-GAPS.md](knowledge-spike/CONTENT-GAPS.md)) — hours, FAQ,
  payment methods — which directly raise achievable recall.
- **Iteration size** is a deliberate step up from 0.0.2 (~2× scope). The three-layer gate per
  slice is the guard against a big-bang integration at the end; the simulator makes each track's
  progress visible to the owner continuously.
