# 0.0.5 — NFR-1 layer ② (browser E2E): evidence

Captured 2026-07-29 against commit `f7ef529`, workbench served by `next dev` on
`localhost:3000` (the `workbench-ui` launch entry — **not** `pnpm dev`, which runs
`docker compose up --build`).

## Screenshots — an earlier claim here was wrong, and this is the correction

**What this section used to say:** that `computer{action:"screenshot"}` fails on this machine, and
therefore the screenshot clause was *"unsatisfiable here, for every slice, in every session."*

**That generalisation was false.** It was true of exactly one surface — the in-app **Browser pane**,
which returns *"the Browser pane is not displayed, so the page is not compositing frames"*. It was
never established for **Chrome**, which was never tried before the claim was written. Chrome
screenshots work. Four gate PNGs live in `e2e-shots/`, and 2026-07-30's console walkthrough was
witnessed and captured through Chrome.

Recorded rather than quietly patched, because the shape of the error matters more than the fact:
**one tool failed, and the conclusion was written about every tool.** The honest sentence was "the
Browser pane cannot screenshot" — a claim about a tool. What got written was a claim about the
machine, which then propagated into five other documents in this directory.

The re-runnable script below is still the better *primary* evidence, and that part of the original
reasoning stands: a screenshot can be looked at; a script can be executed again by anyone and
produce the same verdict. It is the *substitute-of-necessity* framing that was wrong — the
screenshots were available all along.

**One real limit, stated narrowly this time:** a native `title` tooltip is drawn by the browser's
own UI layer rather than the page, so it does not appear in a CDP screenshot. Tooltip text is
therefore evidenced by reading the `title` attribute off the live DOM, which pins the exact string
rather than a picture of it. This is a claim about native tooltips and CDP capture — nothing wider.

---

## Part 1 — mechanical, no credentials, anyone can re-run

```
pwsh -File workspace/0.0.5/verify-e2e.ps1
```

**Result: PASS — 15 assertions, 0 failures, exit 0.**

### Every 0.0.5 admin BFF route refuses an unauthenticated caller

| route | expected | got |
| --- | --- | --- |
| `/api/admin/metrics` | 401 | **401** |
| `/api/admin/memory-hub` | 401 | **401** |
| `/api/admin/inbox` | 401 | **401** |
| `/api/admin/lexicon` | 401 | **401** |
| `/api/admin/agent-experience` | 401 | **401** |
| `/api/admin/memory-audit` | 401 | **401** |

This is the check that catches a new admin route shipped without its gate: such a route answers
**200 with data**.

### The pages do not render their data before the session check

Each admin page, fetched without a session, returns the sign-in affordance and **none** of its own
content — nine assertions, all passing. This one matters more than it looks: a page that renders
before its gate leaks to anyone who curls the URL **and still looks correct in a signed-in
browser**, so no manual walkthrough would ever catch it.

> **The check was wrong before it was right.** It began as `contains` assertions and failed six
> times. The app was fine; the harness was asking an unauthenticated fetch to show authenticated
> content. Asserting *absence* is what that fetch can actually prove. Recorded because "suspect the
> harness before the code" is the discipline that found the real defects in this iteration too.

---

## Part 2 — through an authenticated browser session (not re-derivable without one)

Read out of the live DOM via `javascript_tool`, so these are the strings the page actually
rendered, not a description of them.

### `/admin/memory-hub` — 2705 chars of `<main>`, five invariants present

| invariant | slice | present |
| --- | --- | --- |
| `No live count on this hub` | S14 — L1–L3 are *stated*, not shown as a zero | **true** |
| `Counts only` | S14 — L4 is the PII layer, counts only (NFR-6) | **true** |
| `entry_effectiveness` | **D22** — the zero-use tile reads effectiveness, not `hit_count` | **true** |
| `structurally zero` | **D22** — the tile explains *why*, in the label | **true** |
| `NOT what a turn carries` | S06/S26 — store count ≠ what the prompt gets | **true** |

### `/admin/metrics` — served with live data

Rendered `Memory injection rate 48.3% · 2020 / 4179 turns`, S18's per-layer latency tiles against
the 150 ms SLO line, and S22's lifecycle block. The L5 tile reads **"Not yet measured"** rather
than `0` — the honest-labelling property S18 and S22 both pinned.

---

## What the 2026-07-29 run did NOT establish, and which gaps closed on 2026-07-30

The four limits below were true of the 07-29 `next dev` run. Three were closed the next day by the
owner-witnessed Chrome session against the **containers**; they are kept rather than deleted, so the
record shows what was open and what shut it.

* ~~**The rep-403 leg was not exercised.**~~ **CLOSED 07-30.** A signed-in rep session was driven by
  the owner, and all four admin routes answered **403** — not 401, not 200. This was the specific gap
  listed as uncovered, and it is now the leg with the strongest evidence: an authenticated request
  that is *refused by role* proves more than an anonymous one refused by absence of a session.
* ~~**Nothing served by the dispatch containers is covered.**~~ **CLOSED 07-30.** The 07-29 run
  checked hot-reloaded `next dev`, which is why the note existed. The 07-30 session ran against
  `dispatch-admin` after `docker compose up -d --build`, so what was verified is the built image.
  This distinction turned out to be load-bearing, not pedantic: a server-derived flag passed its unit
  tests and did **not** change on screen, because the container still held the pre-fix image. The
  fix was only real after the rebuild.
* **The populated review inbox is still unverified.** The dev database has no review items, so the
  inbox correctly renders its empty state and the row rendering is covered by component tests only.
  **Still open** — no run has exercised it.
* ~~**Screenshots do not exist and cannot be produced on this machine.**~~ **WRONG WHEN WRITTEN**, in
  the general form. See the correction at the top: the Browser pane cannot screenshot; Chrome can,
  and did.
