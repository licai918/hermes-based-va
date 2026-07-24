# quality-feedback slices (0.0.4 module)

Ten slices implementing [the module PRD](../PRD.md) Phase 1 — human scoring of AI
output, captured under governance. Governance decisions:
[ADR-0154](../../../../docs/adr/0154-manual-scoring-feedback-mechanisms.md).

**Module-scoped numbering.** These `S01`–`S10` are *this module's*, parallel to
the durable-substrate `workspace/0.0.4/issues/S01`–`S25`. Qualify them as
`quality-feedback S0n` when referenced from outside. `FR-`/`NFR-`/`PAC-` numbers
are likewise module-scoped.

**Slice style follows the repo, not a generic template**: backend write paths and
their UI ship as separate slices (as the durable-substrate tool and UI slices do),
each carrying the three-layer gate — ① technical, ② E2E (browser), ③ product PAC.

## Dependency graph

```
S01 (spec correction, docs only)
 └── S02 (toee_feedback tool shell)
      ├── S03 (interaction_review table + write) ──── S04 (review bar + BFF) ──── S05 (status column)
      ├── S06 (draft_feedback table + rating write) ─┬─ S07 (thumbs UI + BFF route)
      │                                              └─ S08 (outcome write) ──── S09 (send capture)
      └── S10 (list_feedback read)   [also needs S03 + S06]
```

After **S02**, track T2 (S03→S04→S05) and track T3 (S06→S07/S08→S09) run in
parallel. **S05**'s E2E needs S04's write to exist to produce data. **S09** shares
the route S07 adds — whichever lands first creates it.

## Slices

| # | Title | Track | Size | Depends on | Delivers |
|---|-------|-------|------|-----------|----------|
| [S01](S01-spec-correction-allowlist-and-numbering.md) | Spec correction: dispatch-only pattern + numbering | T1 Foundation | XS | — | corrects FR-1/3 |
| [S02](S02-toee-feedback-tool-shell.md) | `toee_feedback` shell: catalog, schemas, allowlists, model exclusion | T1 Foundation | S | S01 | FR-3, FR-2, FR-11 |
| [S03](S03-interaction-review-write-path.md) | Interaction Review table, gate, handlers | T2 External | M | S02 | FR-1, FR-2, FR-4 |
| [S04](S04-review-bar-ui-and-bff-route.md) | Review bar on audit detail + review BFF route | T2 External | M | S03 | FR-5, FR-10 |
| [S05](S05-review-status-column.md) | Reviewed / Not-reviewed column on the audit lists | T2 External | M | S03 | FR-6 |
| [S06](S06-draft-rating-write-path.md) | Draft Feedback table + explicit rating write | T3 Internal | M | S02 | FR-1, FR-2, FR-4 |
| [S07](S07-draft-rating-ui-and-bff-route.md) | Thumbs rating on the draft card + feedback route | T3 Internal | M | S06 | FR-8, FR-10 |
| [S08](S08-draft-outcome-write-path.md) | Implicit outcome write path | T3 Internal | S | S06 | FR-1, FR-4, FR-9 |
| [S09](S09-implicit-send-outcome-capture.md) | Sent-as-is vs sent-edited capture at the governed send | T3 Internal | M | S08 | FR-7, FR-9 |
| [S10](S10-list-feedback-read.md) | `list_feedback` read on Supervisor Admin | T4 Read | S | S03, S06 | FR-3 |

## NFR traceability

| NFR | Where it lives |
|-----|----------------|
| NFR-1 three-layer gate | **Cross-cutting** — every slice carries the ①/②/③ block; not any one slice's deliverable |
| NFR-2 live, not mock | S03, S06, S08, S10 — every persistence assertion SELECTs back from Postgres |
| NFR-3 eval neutrality | **S02** — the replay gate must stay green *unchanged*, which is what proves the tool never reached the model surface |
| NFR-4 no new governance surface | **Phase 2 constraint** — held by the out-of-scope line below, not by a Phase 1 slice |
| NFR-5 migration safety | S03, S06 — additive tables, no backfill |
| NFR-6 docs | S01 (ADR + PRD accuracy); the four CONTEXT.md glossary terms already landed |

NFR-1 and NFR-4 are deliberately uncited in any slice's `Delivers` line: one is a
convention every slice obeys, the other constrains work this phase does not do.

## PAC scenarios

| PAC | Scenario | Proven by |
|-----|----------|-----------|
| PAC-1 | Simulator conversation auto-handles → score it fail with tags from the audit view → row + audit entry | S04 |
| PAC-2 | The scored record shows Reviewed in the list; an unsampled sibling shows Not reviewed | S05 |
| PAC-3 | Drive a case to a copilot draft → thumbs-down with a tag → row | S07 |
| PAC-4 | Edit and send that draft → `sent_edited` + ratio, sharing one correlation id with the rating | S09 |
| PAC-5 | A rep sees no review controls; a dispatch with no acting employee persists nothing | S03, S04, S06 |

## Seam findings folded into these slices

The slice set was audited across five seams; each finding is absorbed by a named
slice rather than left as a note.

| Seam | Finding | Absorbed by |
|------|---------|-------------|
| Structural | "registered in no allowlist" makes the tool **unreachable** — the dispatch gate *is* the allowlist. Correct pattern: allowlist **+** agent-excluded set | S01 |
| Structural | Allowlisting is per **tool**, not per action — an action's profile restriction is enforced by which BFF route exists | S10 |
| Technical | Migration number is **0016** (0012 taken; branch at 0015); ADR-0154 already landed | S01 |
| Technical | TS and Python tool catalogs are dual-source and must move together | S02 |
| Technical | Implicit capture must swallow its own errors, mirroring the existing metric emitter | S09 |
| Product | The status column needs a **new list-read field** — a real backend dependency, not a UI bolt-on | S05 (split out for this) |
| Product | Email and note drafts have no send event → implicit capture is SMS-only | S09 |
| Logical | No draft correlation id exists, and the send modal cannot see the original draft | S09 |
| Logical | Supervisor-only review is enforced at the **BFF prefix gate**, not in Tool Gate (no role column in the datastore) — must be tested, not assumed | S04 |
| Logical | Re-review appends; "reviewed" on the list means *any* review exists, resolved latest-per-subject | S05 |
| Test | The "AI cannot score itself" guarantee needs an explicit no-actor → `policy_blocked` **+ zero rows** test | S03, S06 |
| Test | A registration test must prove no `toee_feedback` action reaches the model surface | S02 |
| Test | Every backend slice asserts "model-supplied verdict/actor ignored" and "rejection persists nothing" | S03, S06, S08, S10 |

## Out of scope for all ten

Phase 2 — aggregation, **Improvement Proposal** generation, and routing into the
existing L6 review queue, the Knowledge Publish Eval Gate, and the metrics panel.
Phase 1 is capture only, and by decision Phase 2 builds **no** new proposal
pipeline, approval queue, or dashboard.
