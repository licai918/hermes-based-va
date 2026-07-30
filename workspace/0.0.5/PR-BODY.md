0.0.5 completes the memory architecture: the L7 semantic lexicon, the lifecycle core, boundary
enforcement, the memory-ops UX, latency instrumentation, and the Memory Control Loop. **29 slices
plus both carry-in slices**, 134 commits, clean fast-forward from `main @ 7fcfe09`.

| Suite | Result |
| --- | --- |
| `hermes-runtime` pytest | **1476 passed** |
| `hermes` pytest | **1319 passed, 1 skipped** |
| `pnpm test` | **89 files / 939 tests passed** |
| `pnpm typecheck` | both projects **Done** |
| Launch Eval replay — `text_first_launch` | **35/35**, `failed_high=0` |
| Launch Eval replay — `email_go_live` | **10/10**, `failed_high=0` |
| FR-30 `gates recall` (21 real questions) | **17/21 = 81%**, bar 80% **PASS** |
| FR-7b `gates latency` + deadline degrade | p95 **11.54 ms** / 800 ms **PASS** |

*Re-run 2026-07-30 after the console-found fixes and D29's L5 wiring fix. This table read 1452 /
1309 / 938 two drafts ago and 1466 one draft ago — correct each time it was written, stale by the
time it was read. Suite counts are the kind of number that goes quietly wrong, which is why the eval
and knowledge gates are now listed here too rather than described in prose elsewhere.*

Migrations 0020–0026, 0028–0031 and **0032** applied; **0027 was never claimed and is free.** The
catalog-sync lane ran S01 → S02 → S15 → S11 → S10 → S16 without a collision.

Full detail: [`workspace/0.0.5/CLOSEOUT.md`](workspace/0.0.5/CLOSEOUT.md) ·
[`DECISIONS.md`](workspace/0.0.5/DECISIONS.md) (D0–D29) ·
[`knowledge-gate/GATE-REPORT.md`](workspace/0.0.5/knowledge-gate/GATE-REPORT.md)

---

## Read before approving — six things a green build does not say

Each was measured or proven during the iteration. Each is something a reader could get wrong from
the test results alone.

### 1. FR-30 is NOT met. The knowledge gate fails, and the bar was not lowered.

Measured on the owner's real SMS transcript: **recall@3 = 13/22 = 59%**, bar 80%. The synthetic
interim set scores 73% — and that 73% is **inflated by its own authorship**, having been written by
someone who had read the corpus. Give the real questions a synonym layer and they score *exactly*
73% too, which is the cleanest available proof the two sets were never measuring the same
difficulty.

The route to 80% is arithmetic, two thirds of it measured: 59% → **73%** (wire a synonym layer,
**+3 measured**) → **77%** (correct one gold label that was too narrow, +1) → *86% projected* (add
opening hours, and a login / order-number page). **No step is a bar change.**

What is missing is transcript from channels where customers ask **policy** questions rather than
place orders. The supplied one is a repeat-B2B ordering thread — its regulars already know the
policies and only ask about today's truck.

### 2. A green adversarial suite is not proof that no injection was obeyed (D24)

`_eval_safety` reads **substrings of the reply text**. An injected instruction obeyed **in prose**
fails the build; the same instruction obeyed **as a tool call** with a bland reply leaves every
marker green. Scenarios 35/36 now carry both shapes so the hole lives in the suite rather than in an
ADR — but only a *medium* tool assertion notices them, and medium does not gate.

**PAC-4 establishes:** a stored injection *with a prose effect* cannot be obeyed without failing CI.
**It does not establish** that no injected instruction was obeyed.

### 3. The L4 backfill exposure is UNMEASURED, not clean (D21)

S08 closed the L4 write path going forward; S10 shipped the one-time re-scan for rows written before
it, through S08's own resolver. **It found nothing because there is nothing** —
`customer_memory_slot` is 0 rows on a dev database that is otherwise populated (4 cases, 6 threads,
4 lexicon entries, 59 audit rows).

"We ran the scan and it was clean" and "we ran the scan against an empty table" look identical in a
green build. Run `python -m hermes_runtime.blast_radius` wherever real L4 data lives.

### 4. A capability was removed; no abuse was observed (D27)

`governed_tool_names` UNIONs into the agent's existing tool set unless `tools_exclusive=True`, and a
capture fork boots the whole `internal_copilot` profile first — so **the L6 review fork could
dispatch any of 43 tools, live since S23-0.0.3, while its docstring said otherwise.** Both forks now
fence.

There is **no evidence the extra surface was ever exercised**: the fork asks a model for language,
and a model that never tried to call `toee_customer_memory` was never refused. Found because a bait
**refused to go red** — the routing tests pinned the *extractor*, not the *toolset*.

**Still open:** every other `run_agent_turn` caller passing `governed_tool_names` without
`tools_exclusive` is offering rather than fencing. Its own slice, and start from the assumption that
another docstring in that set is wrong.

### 5. S30's escalation fix is structural; the production failure still does not reproduce

S31's live probe measures the shipped persona at **10/10 *before* S30's change**, so **no
after-number can show the fix worked, and none is claimed.** It ships on structural grounds plus
red-capable tests. The 0.0.4 stack opened **0 of 2** cases where the probe opens **10 of 10** on the
same words with the same prompt; the cheap explanations were ruled out and **the real cause is still
unknown.**

What the harness *did* catch: S30's first draft over-escalated on the must-NOT-escalate contrast
probe — its own named out-of-scope risk, produced by its own fix, invisible to every deterministic
test in the diff.

### 5b. L5 knowledge retrieval was never wired on the deployed stack (D29)

The iteration's most serious find, and it came from **asking the running product a customer question
during the S24 walkthrough** — no test saw it. The agent answered *"I don't have our return policy on
hand to share here"* to questions FR-30's gate scored as HITS, because **the gate measures
`retrieve()` while an agent turn reaches L5 through the `toee_knowledge_search` tool** — and that tool
was never routed to the retriever: `KNOWLEDGE_BACKEND` was absent from `docker-compose.yml`, so it
served a two-entry mock stub. `fastembed` was also undeclared in the image and the model unbaked;
each of those alone reproduces the identical empty result.

Fixed all three, plus **deleted the CI carve-out** (`grep -v 'fastembed not installed'`) that had let
the no-silent-skip gate stay green while the only coverage of this path never ran. Same question now
returns the policy's real 7-day window and 15% restocking fee —
[`S24-LIVE-ANSWER.md`](workspace/0.0.5/knowledge-gate/S24-LIVE-ANSWER.md) has it before and after in
one thread, plus the in-container probe (tool payload **15 → 3894 chars**).

**Costs, stated:** the runtime image is now **2.13GB**, and CI's runtime job will pull the embedding
model — the bill 0.0.3's "leave fastembed undeclared" decision deferred. Those CI fetches hit the HF
Hub unauthenticated, so a rate-limit there becomes a new way for CI to redden unrelatedly.
**Not re-scored:** FR-30's 81% still measures the retriever seam, not the tool seam.

### 6. Browser E2E is the controller's standing debt, not the slices'

The dispatch containers serve a baked image; rebuilding mid-iteration would have baked several
agents' uncommitted code into a shared stack. Slices verified what the hot-reloading workbench UI
could show and **declared the dispatch-served half unverified rather than implying otherwise.**
An earlier draft of this section said screenshots were unobtainable on this machine. **That was
wrong** — it was true of the in-app Browser pane only, and Chrome was never tried before the claim
was written. Four gate PNGs are committed under `workspace/0.0.5/e2e-shots/`, and the console
walkthrough was captured through Chrome. Textual evidence remains the *primary* record because it
is re-runnable, not because pictures were impossible.

**Verified live** after a controlled rebuild: the metrics page — S18's latency tiles reading **p95
2.52 ms over 1908 samples** against the 150 ms line, independently corroborating S19's 2.30 ms
measurement — the Memory Hub with D22's correction rendering its own explanation, S13's and S16's
annotations side by side on a seeded row, and **401 logged-out / 403 rep / 200 supervisor on every
new BFF route.**

**Not verified:** the populated review inbox (the dev database has no review items), and anything
that must round-trip through `dispatch-copilot`.

---

## Owner decisions this PR carries in, unresolved

| Decision | Why it needs a call |
| --- | --- |
| **D23** — five of eleven feedback tags have nowhere legal to emit | Add a seventh `review_item` kind (**a D9 amendment**), or accept collection-only and **say so where the reviewer clicks the tag.** Today a reviewer tagging "missed information" gets a counted outcome that reaches nobody. |
| Audit `details` render verbatim in the console | `optionalDetail` stringifies the whole blob, so `binding_key` — a customer's own phone/email — shows in the Detail column. Pre-existing since 0.0.3; S11 widened it. Defensible as-is (admin-gated, one customer, trail completeness is PAC-3's ask); the real defect is the blanket stringify rather than a named-field projection. |
| One strict field blanks the whole metrics page | Happened **three times** this iteration. S28 made its own block nullable; **`latency`, `deletionSuccess` and `lifecycle` are still strict.** The failure mode is a blank admin page on any version skew. |
| ~~`seed_lex_season_all_season` says "all-season tires"~~ **FIXED in this PR** — the row now reads `passenger tires` (migration `0032`, D1's approved class label). **What is left to decide:** the *condition token* still reaches the prompt as `Seasonal default (tire, all_season): …`, naming the calendar window rather than the product. Renaming the facet vocabulary is 0.0.6 D1's spec work; say the word and it moves into 0.0.5 instead. |

## Deliberately not in this PR

- **S24's passing gate.** Question set, content-gap analysis and gate report are committed; the
  number is a fail and is reported as one.
- **S29's signature.** PAC-1..9 is owner-driven by design.
- **Content authoring** (delivery-schedule page, opening hours, login/order-number page) — the
  owner-input problem is 0.0.6's by decision.
- **A synonym layer wired into knowledge retrieval.** Measured at +14 points, but 0.0.6's D1 already
  decided where customer-vocabulary reconciliation lives and D4 puts it after this merge; pre-seeding
  rows now would have to be undone.

---

## The defect class this iteration killed

**A test that takes its standard from the thing it is testing.** Four slices hit it independently —
an expectation derived from the function under test; a suite where every test drove a scripted
double, leaving the *live* client's request unpinned; an `it.each` filtered by the map under test,
so adding a tag silently dropped the case that would have caught it; a fixture row that was a valid
recurrence for a different fix.

The counter-measure worked every time: **arm a bait, and when it stays green, suspect the harness
before concluding the test is vacuous.** That discipline is what found D27.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
