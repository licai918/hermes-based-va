# 0.0.5 — closeout packet

Branch `feat/0.0.5-land-all`, **133 commits**, base `main @ 7fcfe09` (0 behind — clean fast-forward).

| Suite | Result |
| --- | --- |
| `hermes-runtime` pytest | **1466 passed** |
| `hermes` pytest | **1319 passed, 1 skipped** |
| `pnpm test` | **89 files / 939 tests passed** |
| `pnpm typecheck` | both projects **Done** |

*Re-run 2026-07-30 after the two console-found fixes. The earlier table read 1452 / 1309 / 938 —
true when written, stale once those landed.*

Working tree and index clean. Migrations 0020–0026, 0028–0031 and **0032** applied; **0027 was never
claimed and is free.** The catalog-sync lane ran S01 → S02 → S15 → S11 → S10 → S16 without a
collision.

---

## What shipped

All **29** 0.0.5 slices except **S24** (blocked on owner input) and **S29** (this sign-off), plus
both carry-in slices **S30/S31**.

**FR coverage: 33 of 34.** Every FR has a landed slice except **FR-30, which is NOT met** — see
below. NFR-1's three-layer gate is satisfied on layer ① throughout; layers ② and ③ are the two
sections after this one.

---

## READ BEFORE SIGNING — six things a green build does not say

These are not caveats added for completeness. Each was measured or proven during the iteration, and
each is a statement a reader could otherwise get wrong from the test results alone.

### 1. FR-30 is not met. The knowledge gate FAILS, and the bar was not lowered.

Measured on the owner's real transcript: **recall@3 = 13/22 = 59%** against an 80% bar. The
synthetic interim set scores 73% — and that 73% is **inflated by its own authorship**: it was
written by someone who had read the corpus, so its phrasing echoes the pages. Give the real
questions a synonym layer and they score exactly 73% too, which is the cleanest available proof
that the two sets were never measuring the same difficulty.

The path to 80% is arithmetic and two thirds of it is measured: 59% → **73%** (wire a synonym layer,
+3 measured) → **77%** (fix one gold label that was too narrow, +1) → *86% projected* (add opening
hours and a login/order-number page). **None of that is a bar change.**

What is missing is transcript from channels where customers ask **policy** questions rather than
place orders. The supplied transcript is a repeat-B2B ordering thread — its regulars already know
the policies and only ask about today's truck.

### 2. A green adversarial suite is not proof that no injection was obeyed (D24).

`_eval_safety` reads **substrings of the reply text**. An injected instruction obeyed **in prose**
fails the build. The same instruction obeyed **as a tool call**, with a bland reply, leaves every
marker green. Scenarios 35 and 36 now carry both shapes so the hole is visible in the suite — but
only a *medium* tool assertion notices them, and medium does not gate.

**PAC-4 establishes:** a stored injection *with a prose effect* cannot be obeyed without failing CI.
**It does not establish** that no injected instruction was obeyed.

### 3. The L4 backfill exposure is UNMEASURED, not clean (D21).

S08 closed the L4 write path going forward. S10 shipped the one-time re-scan for rows written
before it, through S08's own resolver. **It found nothing because there is nothing** —
`customer_memory_slot` is 0 rows on the dev database, which is otherwise populated (4 cases, 6
threads, 4 lexicon entries, 59 audit rows).

So the mechanism is proven and the exposure is not measured. "We ran the scan and it was clean" and
"we ran the scan against an empty table" look identical in a green build. **Run
`python -m hermes_runtime.blast_radius` wherever real L4 data lives.**

### 4. A capability was removed; no abuse was observed (D27).

`governed_tool_names` UNIONs into the agent's existing tool set unless `tools_exclusive=True`. A
capture fork boots the whole `internal_copilot` profile first — so **the L6 review fork could
dispatch any of 43 tools, live since S23-0.0.3, while its docstring said otherwise.** Both forks now
fence.

There is **no evidence the extra surface was ever exercised**: the fork asks a model for language,
and a model that never tried to call `toee_customer_memory` was never refused. Do not read the
fix as a remedy for something observed.

**Still open:** every other `run_agent_turn` caller passing `governed_tool_names` without
`tools_exclusive` is offering rather than fencing. Its own slice — and start from the assumption
that another docstring in that set is wrong.

### 5. S30's escalation fix is structural. The production failure still does not reproduce.

S31's probe measures the shipped persona at **10/10** *before* S30's change, so **no after-number
can show the fix worked, and none is claimed.** It ships on structural grounds plus red-capable
tests. The 0.0.4 stack opened **0 of 2** cases where the probe opens **10 of 10** on the same words
with the same prompt; the difference is mock drivers and a self-rendered identity block, and the
cheap explanations were ruled out. **The real cause is still unknown.**

What the harness *did* catch: S30's first draft over-escalated on the must-NOT-escalate contrast
probe — its own named out-of-scope risk, produced by its own fix, invisible to every deterministic
test in the diff.

### 6. Browser E2E is the iteration's standing debt, and it is the controller's, not the slices'.

The dispatch containers serve a baked image; rebuilding it mid-iteration would have baked several
agents' uncommitted code into a shared stack. So slices verified what the hot-reloading workbench UI
could show and **declared the dispatch-served half unverified rather than implying otherwise.**
An earlier draft of this section said screenshots were unobtainable on this machine. **That was
wrong in the general form** — true of the in-app Browser pane, never tested against Chrome before
being written. Chrome screenshots work; four are committed under `e2e-shots/`. Textual evidence is
the *primary* record because it re-runs, not because pictures were impossible.

**Verified live** after a controlled rebuild: the metrics page (S18's latency tiles reading
**p95 2.52 ms over 1908 samples** against the 150 ms line, corroborating S19's independent 2.30 ms),
the Memory Hub with D22's correction rendering its own explanation, S13's and S16's annotations side
by side on a seeded row, and **401 logged-out / 403 rep / 200 supervisor on every new BFF route.**

**Not verified:** the populated review inbox (the dev database has no review items), and anything
that must round-trip through `dispatch-copilot`.

---

## Owner decisions this merge carries in, unresolved

| # | Decision | Why it needs you |
| --- | --- | --- |
| **D23** | Five of eleven feedback tags have nowhere legal to emit | Add a seventh `review_item` kind (a **D9 amendment**), or accept collection-only and **say so where the reviewer clicks the tag**. Today a reviewer tagging "missed information" gets a counted outcome that reaches nobody. |
| — | Audit `details` render verbatim in the console | `optionalDetail` stringifies the whole blob, so `binding_key` (a customer's own phone/email) shows in the Detail column. Pre-existing since 0.0.3; S11 widened it. Defensible as-is (admin-gated, one customer, trail completeness is PAC-3's ask); the real defect is the blanket stringify rather than a named-field projection. |
| — | One strict field takes the whole metrics page down | Happened **three times** this iteration. S28 made its own block nullable; **`latency`, `deletionSuccess` and `lifecycle` are still strict.** The failure mode is a blank admin page on any version skew. |
| — | ~~`seed_lex_season_all_season` carries `canonical_form="all-season tires"`~~ **FIXED HERE** | Migration `0032` sets it to `passenger tires`, D1's approved label for the class; verified in the prompt render, not just the console. **Left for you:** the *condition token* still reaches the prompt (`Seasonal default (tire, all_season): …`) as the name of the calendar window. Renaming the facet vocabulary is 0.0.6 D1's spec work — say so and it moves into 0.0.5. |

---

## What this merge deliberately does not include

- **S24's passing gate.** The question set, the content-gap analysis and the gate report are
  committed; the *number* is a fail and is reported as one.
- **S29's signature.** PAC-1..9 is owner-driven by design.
- **Content authoring** (the delivery-schedule page, opening hours, a login/order-number page) —
  the must/optional owner-input problem is 0.0.6's by decision.
- **A synonym layer wired into knowledge retrieval.** Measured as worth +14 points, but 0.0.6's D1
  already decided *where* customer-vocabulary reconciliation lives, and D4 puts it after this merge.
  Pre-seeding rows now would have to be undone.
