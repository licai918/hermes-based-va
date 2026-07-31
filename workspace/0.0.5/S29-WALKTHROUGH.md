# 0.0.5 — the two-minute owner walkthrough

Five pages. Each row is phrased so a **wrong** render is obvious without reading any code — the
point of a walkthrough is to catch what a passing test cannot, so "the page loads" is not on the
list.

Everything mechanical is already done and re-runnable (`workspace/0.0.5/verify-e2e.ps1`, 15
assertions, 0 failures). **This file covers only the part that needs your eyes and your session:**
whether the surfaces are *honest*, which no assertion can judge.

Start the UI, signed in as a supervisor:

```bash
pnpm dev:workbench
```

> Use `dev:workbench`, **not** `pnpm dev` — the latter runs `docker compose up --build` and
> replaces the shared runtime image.

---

## 1 · `/admin/memory-hub` — does it refuse to overstate?

This page is the iteration's honesty test, because every number on it is scoped and a scope you
cannot see is a number that lies.

| look for | why it matters | **wrong** would be |
| --- | --- | --- |
| **L1, L2, L3 say "No live count on this hub"** | those layers have no aggregate read; a zero would read as *"nothing happened"* | seeing **0** |
| **L4 says "Counts only"** and shows no slot value, binding key or customer name | L4 is the PII layer by design (NFR-6); a hub is the wrong place to surface it | any customer detail |
| **L6/L7 confirmed counts say "NOT what a turn carries"** | the store holds more than the prompt gets — a bounded window | a bare number with no caveat |
| **the zero-use tile mentions `entry_effectiveness` and "structurally zero"** | D22 — `hit_count` is permanently 0 for every seasonal rule, so a hit-only count would list them all forever | a tile that just says "0 hits" |

## 2 · `/admin/metrics` — are the unmeasured things labelled as unmeasured?

| look for | **wrong** would be |
| --- | --- |
| **L5 knowledge retrieval shows a real p95 against a `budget 800 ms`** | a blank tile — **or "Not yet measured", which is what this row used to ask for.** L5 genuinely had no samples until D29 wired it; now it does. See the ⚠ below about the number itself. |
| **the L4+L6+L7 total shows a p95 against a 150 ms line** | no budget shown, or a budget that is not 150 |
| **lifecycle rows show counts, not percentages**, and each detail line names what it excludes | a rate with no denominator |
| **the privacy-deflection row is labelled PROXY** | presented as *the* privacy-complaint rate |

> **⚠ Look hard at the L5 number, it is the one thing on this page that worries me.**
> Measured live on 2026-07-30: **p95 787.52 ms against the 800 ms budget** — 98% of it —
> on 3 samples, with the knowledge found-rate at **66.7% (2/3)**. The FR-7b gate reports
> **p95 11.54 ms** for the same code. The gate warms the embedder and runs 200 calls in a
> hot loop; a real turn does not. **This is the same gate-versus-product gap as D29, in
> latency instead of recall** — and blowing that deadline is exactly what produces "I
> don't have that on hand". Small sample, not yet diagnosed; recorded, not explained away.

## 3 · `/admin/inbox` — the queue

Expect either an empty queue or the `blast_radius` row left by the D30 walkthrough. **Wrong** would
be a spinner that never resolves, or an error.

*To populate it yourself* — and this instruction used to be wrong, which is worth knowing before you
follow it. It said "retire a lexicon entry; S10's blast-radius hook emits a review item on retire."
**It omitted the condition.** `blast_radius.py` raises an item only when the retired entry actually
touched an OPEN case:

```python
if not result["open_cases"] and not emit_when_no_open_cases:
    return None   # "0 open cases touched by retired entry X -- review?" is noise
```

So retiring an entry nobody's conversation ever used emits **nothing**, correctly. Following the old
instruction produced an empty inbox and looked like a broken feature. The sequence that works:

1. add an entry in `/admin/lexicon` (it is `confirmed` immediately — you are the gate),
2. send **one** message in the Simulator, so the entry is injected into a live turn,
3. retire it.

The row then carries `reason: entry_retired` with the case and turn counts — **counts, not case
ids**, deliberately: the write scan redacts long digit runs and would mangle an id into a broken
link. Use the subject_ref to get the live list instead.

## 4 · `/admin/lexicon` — the L7 console

*Column names and behaviour below were read out of `LexiconConsole.tsx`, not taken from a slice's
report — so if one is missing, that is a real finding and not a stale instruction.*

| look for | **wrong** would be |
| --- | --- |
| a **Health** column, and the score shown on a **−0.50 to 1.00** scale with **no % sign** | a percentage — the score is not a rate, and rendering it as one invites a reader to compare it with the honored rate |
| the Health column header carrying its own **scope caveat** ("external-path only"), and the row detail repeating the *same* scope | header and detail disagreeing about scope, or a bare number with no caveat anywhere |
| a **provenance** value per row, and **all four seeded rows** badged `admin_manual` **UNATTRIBUTED** in red — hover one and the note says the decider is *either missing or a migration* | a seeded `admin_manual` row that looks identical to one a named admin approved (D20 — that is unfalsifiable provenance), **or** a hover note claiming the row "predates the fail-closed path", which is false of a seeded row and was itself a defect found on this walkthrough |
| **the seasonal row says `passenger tires`** — and an `(edited …)` marker beside its decider | **"all-season tires"** — the phrase your policy forbids to Canadian customers. It was there when this walkthrough was first written; it was fixed as a result. A *missing* edit marker would also be wrong: the fix arrived by migration, and D6/D7's trail must show the row was touched. |

## 4b · Ask the product a real question — this is the step that found the worst bug

Go to **Simulator** (`/copilot/simulator`), type a question a customer would actually send, Send.

Suggested, because they exercise different corners of the corpus:

| ask | a good answer contains |
| --- | --- |
| `how many days do i have to send tires back` | **7 days**, and the **15% restocking fee** past that |
| `do you give shops payment terms` | the dealer/shop programme, not a generic brush-off |
| `whats your phone number` | the real contact details |

**What "wrong" looks like, and it is not obvious:** a *fluent, polite, completely contentless*
reply — *"I don't have our return policy on hand, I've flagged this for our team."* That is what the
product said before 2026-07-30, on questions the FR-30 gate scored as HITS, because the gate measured
the retriever while the agent was being served a two-entry stub (D29). It reads like good service.
**Nothing but asking and reading the answer catches it** — 3,724 tests did not.

If you get a deflection on something the corpus obviously covers, that is a real finding, not a
model having an off day.

## 5 · Sign out, then try any `/admin/*` URL directly

You should land on the sign-in page and see **none** of the page's data. This is already proven
mechanically (nine assertions), and it is worth ten seconds of your own eyes because a page that
renders before its gate **still looks correct while you are signed in**.

---

## Before you sign: three things a green build does not say

1. **FR-30 passes at 17/21 = 81% — and at 17/22 = 77% it fails.** The difference is one question
   moved out because its gold page has no hours in it at all. Both numbers are in
   `knowledge-gate/GATE-REPORT.md`. If you judge that move wrong, the requirement fails.
2. **A green adversarial suite is not proof that no injection was obeyed** (D24). The gate reads
   reply *text*; obedience expressed as a *tool call* with a bland reply leaves every marker green.
3. **The L4 backfill exposure is unmeasured, not clean** (D21) — the re-scan found nothing because
   the table has 0 rows.

And a fourth, which is why this walkthrough exists: **both problems in row 4 above were found by
running it, and both are fixed in this PR.** Neither had a failing test. The wording one was a
`confirmed` L7 entry telling the model it could offer "all-season tires"; the provenance one badged
four migration-seeded rows as though a named admin had approved them. Looking at the screen found
what **3,724 passing tests across all three suites** did not — which is the argument for layer ② as
a gate, not a formality.

Worth knowing about the wording fix specifically: it corrected the **outward label**
(`canonical_form`, the phrase the prompt tells the model to say). The **condition token** is
untouched — the prompt still reads `Seasonal default (tire, all_season): ASK whether the customer
wants passenger tires`, where `all_season` names the *calendar window* the rule applies in, not the
product. Renaming that vocabulary is 0.0.6 D1's spec work. **If you want the token gone from the
prompt too, say so and it becomes a 0.0.5 item** — it is recorded here rather than decided for you.
