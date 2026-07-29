# 0.0.5 — NFR-1 layer ② (browser E2E): evidence

Captured 2026-07-29 against commit `f7ef529`, workbench served by `next dev` on
`localhost:3000` (the `workbench-ui` launch entry — **not** `pnpm dev`, which runs
`docker compose up --build`).

## Why there are no screenshots, for anyone

The slice acceptance blocks ask for screenshots. `computer{action:"screenshot"}` fails on this
machine with *"the Browser pane is not displayed, so the page is not compositing frames"* — retried
during this run and it still fails. **That clause is unsatisfiable here, for every slice, in every
session.** It is not a slice that skipped its homework.

What replaces it is deliberately stronger for an audit: a **re-runnable script** plus a record of
what a browser session showed. A screenshot can be looked at; a script can be executed again by
anyone and produce the same verdict.

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

## What this does NOT establish, stated rather than implied

* **The rep-403 leg was not exercised.** It needs a signed-in rep session and this run entered no
  credentials. Prior slices reported it; that report is not re-claimed here as evidence.
* **Nothing served by the dispatch containers is covered.** They run a baked image predating these
  slices. The workbench UI hot-reloads and is what was checked.
* **The populated review inbox is unverified.** The dev database has no review items, so the inbox
  correctly renders its empty state and the row rendering is covered by component tests only.
* **Screenshots do not exist and cannot be produced on this machine.**
