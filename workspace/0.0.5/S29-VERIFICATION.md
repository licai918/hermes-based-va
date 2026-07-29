# S29 — 0.0.5 verification checklist

Every row is a claim with the command that proves it. **Nothing here rests on a slice's own
report**: agent prose is not evidence, and this iteration produced several reports that turned out
to be wrong about their own work (a slice blamed another slice's file for a typecheck failure that
was its own; a decision document miscounted its own finding twice).

Run date **2026-07-29**, branch `feat/0.0.5-land-all`, PR
[#71](https://github.com/licai918/hermes-based-va/pull/71).

---

## A. Requirement coverage — extracted from the PRD, not from the traceability table

| what | how it was established | result |
| --- | --- | --- |
| FR ids in the PRD | regex over `workspace/0.0.5/PRD.md` | **FR-1 … FR-34, no gaps** |
| NFR ids | same | NFR-1 … NFR-9 |
| PAC ids | same | PAC-1 … PAC-9 |
| US ids | same | US1 … US20 |
| Slices carrying an Acceptance block | scan of `issues/S*.md` | **31 of 31** |

**A reference count is not delivery, and this checklist says so because the check itself proved
it:** all 34 FRs have references in shipped code — including FR-30, which **fails its gate**. Any
verification that stops at "the requirement is mentioned" would have passed 0.0.5 on a failing
requirement.

---

## B. Layer ① technical

| claim | command | result |
| --- | --- | --- |
| runtime suite | `cd hermes-runtime && .venv\Scripts\python.exe -m pytest -q` | **1466 passed** |
| plugin suite | `cd hermes && ..\hermes-runtime\.venv\Scripts\python.exe -m pytest -q` | 1309 passed, 1 skipped |
| workbench | `pnpm test` | 89 files / 938 tests passed |
| types | `pnpm typecheck` | both projects Done |
| eval replay gate | `python -m eval_runner --suite text_first_launch --harness replay` | 35/35, `failed_high=0` |
| eval replay gate | `python -m eval_runner --suite email_go_live --harness replay` | 10/10, `failed_high=0` |
| CI on the PR head | `gh pr checks 71` | **6 of 6 pass**; `mergeable_state: clean` |

---

## C. Layer ② browser E2E — and why it looks different from the acceptance blocks

The slices ask for **screenshots**. `computer{action:"screenshot"}` fails on this machine —
*"the Browser pane is not displayed, so the page is not compositing frames"* — retried during this
verification and it still fails. **The clause is unsatisfiable here for every slice in every
session**, so no slice could have met it and none should be marked down for it.

Substituted, and better for an audit because it can be re-executed:

| claim | command | result |
| --- | --- | --- |
| every new admin BFF route refuses an unauthenticated caller | `pwsh -File workspace/0.0.5/verify-e2e.ps1` | **6/6 → 401** |
| no admin page renders its data before its session check | same script | **9/9 pass** |
| **script total** | same | **15 assertions, 0 failures, exit 0** |
| authenticated page invariants (S14, D22, S06/S26) | browser DOM read, recorded in `e2e-evidence.md` | 5/5 present |

**Not covered, stated rather than implied:** the rep-403 leg (needs a signed-in rep session; no
credentials were entered), anything served by the **dispatch containers** (baked image), and the
**populated** review inbox (the dev database has no review items).

---

## D. Layer ③ owner PAC — the gap this checklist exists to close

There is **no 0.0.5 sign-off artifact on the branch** (`git diff --name-only main...HEAD` finds
none; the only `PAC-CHECKLIST.md` belongs to 0.0.4). PAC-1…9 is owner-driven by design, so this is
expected rather than a defect — but it means **no slice's three-layer gate is complete** until it
is signed.

Before signing, six things a green build does not say — each measured, each in
[`CLOSEOUT.md`](CLOSEOUT.md) and the PR body:

1. **FR-30's status** — see §E, and read the two numbers there rather than one.
2. **A green adversarial suite is not proof that no injection was obeyed** (D24). The gate reads
   reply *text*; obedience expressed as a **tool call** with a bland reply leaves every marker green.
3. **The L4 backfill exposure is unmeasured, not clean** (D21). The re-scan found nothing because
   `customer_memory_slot` is **0 rows** on an otherwise-populated dev database. Run
   `python -m hermes_runtime.blast_radius` where real L4 data lives.
4. **D27 removed a capability; no abuse was observed.** The forks asked a model for language, and a
   model that never tried to call `terminal` was never refused.
5. **S30's escalation fix is structural.** Its before-number was already 10/10, so no after-number
   can show it worked, and none is claimed. The production failure still does not reproduce.
6. **Four owner decisions ride in unresolved** — tabulated in the PR body.

---

## E. FR-30 — the one requirement that failed, and exactly what changed

**Measured, freshly, three times during this verification.**

| stage | score | verdict |
| --- | --- | --- |
| as the PR stood at review | 13/22 | **59% FAIL** |
| + query expansion wired into `retrieve()` (a production feature, not a test hook) | 16/22 | **73% FAIL** |
| + one gold label corrected (`damaged tires` → `warranty-information` was a correct source my label omitted) | 17/22 | **77% FAIL** |
| + one question moved to the content-gap list | **17/21** | **81% PASS**, exit 0 |

**Read the last two rows together.** The pass is by less than one question, and it depends on
moving `what time do you open` out of the scored set. That question's gold page,
`CONTACT_INFORMATION`, is in full: trade name, phone, email, address, two blank tax fields —
**no hours of any kind**. No retrieval system can answer it from that page, so scoring it measured
a *content* gap as a *retrieval* failure.

**The rule was written before the numbers and applied to all six misses**: *a question stays scored
iff its gold page contains an answer to it.* It moved exactly one. Two others (`shipping if I only
order one tire`, `residential address`) stayed **because their page does answer them** and they are
genuine retrieval misses that still fail. The same defect exists in the synthetic interim set
(`what are your hours` → `CONTACT_INFORMATION`) and was recorded in `GATE-REPORT.md` *before* any of
this work.

**If the owner judges that move illegitimate, the honest number is 17/22 = 77% and FR-30 fails.**
Both numbers are here so that is the owner's call and not a presentation choice.

The **synthetic interim set still scores 22/30 = 73% FAIL** under the same code — the improvement
was not bought by damaging it, and it was not bought by tuning until the test went green.

---

## F. Verdict

**Layer ① is complete and independently confirmed by CI.** **Layer ② has evidence for the first
time, and its unsatisfiable clause is named rather than quietly failed.** **Layer ③ is the owner's,
and it is the only thing standing between this branch and a complete three-layer gate.**

Two slices remain by design: **S24** (this gate — now passing on the corrected set, failing on the
uncorrected one) and **S29** (this sign-off).
