# quality-feedback — PAC checklist (NFR-1 layer ② / ③)

The four owner walkthroughs for the quality-feedback module, plus what an
automated run already proved.

**Status:** every PAC's *behaviour* has been executed against a live local stack
(real Next.js BFF → real dispatch server → real Postgres) and asserted by
reading the rows back out of Postgres. The **browser DOM layer** has since been
executed too — see [The browser pass](#the-browser-pass).

**PAC-1 step 2** — the simulator-driven subject — failed on the first run for a
real reason rather than an environmental one: nothing in the running system ever
marked a turn `auto_handled`, so the auto-handled audit list could only contain
fixtures. That has since been fixed; see
[Why PAC-1 step 2 failed, and what fixed it](#why-pac-1-step-2-failed-and-what-fixed-it).
The fix ships with tests that drive the real writers, but the **live re-run is
still owed** — the gateway and turn worker run from a baked
`toee-hermes-runtime:local` image, so proving it end to end again needs that
image rebuilt.

---

## Bring the stack up

```bash
pnpm install
pnpm dev
```

`pnpm dev` starts Postgres, both dispatch servers (8091/8092), the gateway, both
workers, and the workbench on <http://localhost:3000>.

Seeded logins (from `0005_dev_bootstrap`, local dev only — password
`Workbench123!` for all three): `rep`, `supervisor`, `admin`.

> **No `OPENROUTER_API_KEY` needed.** Without one the runtime uses its
> deterministic keyless completion, so drafts still generate — canned, and
> therefore reproducible. Set a key only if you want live-model wording.

> **If `pnpm dev` fails with "container name already in use"**, a Postgres from
> another worktree owns the name. Stop that stack first (`docker compose down`
> in the other checkout). Alternatively run the app tier on the host against the
> already-running Postgres — see [Host-tier fallback](#host-tier-fallback).

---

## PAC-1 — score an auto-handled conversation

**Goal:** a supervisor can record a fail verdict with reason tags on an
auto-handled interaction, and it is attributed to them.

1. Sign in as **supervisor**.
2. Open **`/copilot/simulator`**. Pick the *verified customer* preset, send an
   inbound SMS the agent can answer on its own (e.g. *"Do you carry 225/65R17
   winter tires?"*). Wait for the reply in the thread.
   *(This is the step that needs the gateway + turn worker. It produces the
   auto-handled record PAC-1 scores.)*
3. Open **`/copilot/audit/auto-handled`** and click into that record.
4. In the review bar: click **Fail**. The external reason-tag chips expand.
5. Select **Factual error** and **Should have escalated**, type a comment, submit.

**Expect**
- [ ] The bar accepts the verdict; no error banner.
- [ ] Submit is refused until at least one tag is picked (fail requires a tag).
- [ ] The conversation itself is unchanged (audit views stay read-only).
- [ ] A `workbench_audit_log` row exists with action `interaction_review_submitted`
      and *your* account id.

---

## PAC-2 — sampling coverage is visible

**Goal:** the list shows what has already been sampled.

1. Go back to **`/copilot/audit/auto-handled`** (the list).
2. Find the record you just scored, and any other record.

**Expect**
- [ ] The scored record shows **Reviewed**.
- [ ] The other record still shows **Not reviewed**.
- [ ] Repeat on **`/copilot/audit/sales-outreach`** — its column behaves the same
      and a review on one list never marks a row on the other.

---

## PAC-3 — rate a copilot draft

**Goal:** a rep can say *why* a draft was wrong, in two clicks, without it ever
interfering with customer work.

1. Sign in as **rep**. Open `/copilot`, **claim** a case (feedback requires you
   to hold the case).
2. Click **Draft SMS**. A draft card appears.
3. Click **👎**. The internal reason-tag chips expand.
4. Pick **Too verbose** and **Wrong tone**, optionally comment, submit.

**Expect**
- [ ] 👍 submits immediately with no tag step; 👎 requires at least one tag.
- [ ] The chips are the *internal* set (`wrong_tone`, `too_verbose`, …) — the
      external set (`tone_inappropriate`, …) must NOT appear here.
- [ ] The draft stays editable and sendable throughout.
- [ ] **Rating failure never blocks the send:** the draft remains sendable even
      if the rating call errors.

---

## PAC-4 — the send outcome records itself

**Goal:** the highest-signal measurement costs the rep nothing.

1. On the same claimed case, generate a draft and **send it untouched**.
2. Generate another draft, **edit the text**, then send.

**Expect**
- [ ] Neither send shows any extra prompt — capture is silent.
- [ ] The untouched send records `sent_as_is` (no ratio).
- [ ] The edited send records `sent_edited` with an edit-distance ratio.
- [ ] A rating and an outcome for the *same* draft share one
      `draft_correlation_id` — two rows, one draft.
- [ ] **A failing capture never fails the send** — the customer's message goes
      out regardless.

---

## PAC-5 — governance (do this one deliberately)

- [ ] Sign in as **rep** and open `/copilot/audit/auto-handled` → access is
      refused. Reps cannot review; only supervisor/admin can.
- [ ] Feedback on a case you do **not** hold is refused.

---

## Verify the rows (optional, definitive)

```sql
SELECT subject_kind, subject_id, verdict, reason_tags, reviewer_account_id
FROM interaction_review ORDER BY created_at DESC LIMIT 5;

SELECT outcome, verdict, reason_tags, edit_distance_ratio, rep_account_id,
       draft_correlation_id
FROM draft_feedback ORDER BY created_at DESC LIMIT 5;
```

Both tables are **append-only** — re-reviewing appends a row, it never
overwrites. That is intended: the history of judgments is the audit trail.

---

## What an automated run already proved

Executed against a live stack (workbench 3000 → dispatch 8091/8092 → Postgres),
with every assertion made by reading the row back out of Postgres:

| Check | Result |
| --- | --- |
| PAC-1 review persists with tags, comment, framework-derived reviewer | PASS |
| PAC-1 `workbench_audit_log` row (`interaction_review_submitted`, correct actor) | PASS |
| PAC-2 list flips to Reviewed; sibling subject stays Not reviewed | PASS |
| PAC-3 rating persists `down` + both internal tags, attributed to the rep | PASS |
| PAC-4 `sent_edited` + ratio; rating and outcome share one correlation id | PASS |
| Rating row carries no ratio; outcome row carries no verdict | PASS |
| **Rep refused the review route (403)** | PASS |
| **No-actor write → `policy_blocked` AND zero rows, zero audit rows** | PASS |

The last two are the governance guarantees: the supervisor-only boundary exists
only at the BFF route gate, and *the AI cannot score itself* — a write with no
framework-resolved employee persists nothing.

### A real bug this run caught

`GET /api/copilot/audit/auto-handled` returned **HTTP 500** the moment a real
auto-handled record existed: `_build_auto_handled_record` returned
`last_activity_at` as a raw `datetime`, which is not JSON-serializable, so the
dispatch server's encode raised. Pre-existing (reconstructing the pre-S05 return
shape fails identically) and invisible until now because a fresh dev DB has no
auto-handled records at all — the list is always empty, so nothing ever
serialized. Fixed with the house `serialize_row` helper plus a regression test
that calls `json.dumps`, verified red-capable.

---

## The browser pass

Run against a **production build** (`next build` + `next start`) of the merged
0.0.4 tip, driving the assembled page in a real browser. Every control below was
operated through the page, and every result read back out of Postgres.

| Check | Result |
| --- | --- |
| Login, session, role-scoped nav | PASS |
| PAC-1 review bar: Fail expands the EXTERNAL tag set only | PASS |
| PAC-1 Submit is disabled until a tag is picked; enabled after two | PASS |
| PAC-1 submit → `POST /api/copilot/audit/review` 200, row + audit row, reviewer derived server-side | PASS |
| Append-only: re-reviewing appended a second row, the first intact | PASS |
| **US-7**: reopening shows the prior verdict, tags and comment, with *Edit review* | PASS |
| PAC-2: scored subject reads *Reviewed*, sibling reads *Not reviewed* | PASS |
| PAC-2: sales-outreach list carries the same column and was NOT cross-marked | PASS |
| Sales-outreach Pass submits with no tag step and stores zero tags | PASS |
| PAC-3: 👎 expands the INTERNAL set; none of the external-only tags appear | PASS |
| PAC-3: 👍 submits immediately, no tag step, zero tags stored | PASS |
| PAC-3: the draft stays editable and sendable throughout | PASS |
| PAC-4: untouched send → `sent_as_is`, no ratio; rating + outcome share one `draft_correlation_id` | PASS |
| PAC-4: edited send → `sent_edited` with a ratio | PASS |
| PAC-4: neither send showed any extra prompt — capture is silent | PASS |
| **PAC-4: a capture that throws SYNCHRONOUSLY never fails the send** | PASS |
| PAC-5: rep is bounced off the review route, and the BFF answers 403 | PASS |
| PAC-5: feedback on a case the rep does not hold → `policy_blocked` | PASS |

The synchronous-capture row is the one worth keeping: `window.fetch` was patched
to *throw* (not reject) for `/api/copilot/feedback`, which is precisely what a
bare `.catch()` would have missed. The capture was attempted once and died; the
customer's message still went out and landed in the thread, the modal closed
clean, and no error surfaced to the rep. No outcome row was written — the
capture really did fail. That is the double-send hole, shut.

---

## Why PAC-1 step 2 failed, and what fixed it

Driving a real conversation through the simulator works end to end — the gateway
accepts the tokened webhook, the turn worker runs the turn, and the agent answers
on its own. But the resulting turns are written with `auto_handled = FALSE`, so
the conversation never appears in the auto-handled audit list and there is
nothing to score.

That is not a fixture problem. **All three production inserts into
`message_turn` hardcode `FALSE`:**

- `postgres_gateway_store.py` — the inbound customer turn
- `postgres_gateway_store.py` — the outbound agent-reply mirror
- `datastore/handlers/cases.py` — the workbench send

The column defaults to `FALSE`, there is no `UPDATE … SET auto_handled`
anywhere in the repo, and `feat/0.0.5-land-all` is identical. `_list_auto_handled`
requires `bool_and(auto_handled) IS TRUE`, so **no real conversation can ever
appear in that list.** The only rows that qualify are the hand-written `TRUE`
values in `0005_dev_bootstrap` and the PAC fixtures.

The intended meaning is not in doubt: the dev seed marks the agent-only segment
`TRUE` and the escalated segment `FALSE`, and `cases.py` reads
`active_case_segment = not auto_handled`. The writer side was simply never
implemented.

This is **pre-existing** — the auto-handled audit list predates this module
(ADR-0037, ADR-0085), and the quality-feedback module only added the review bar
and the `Reviewed` column on top of it. But it decides whether the external-facing
(对外) half of this module has any subjects at all in production, so it belongs
to whoever owns the gateway write path, and it should be closed before the
external mechanism is considered live.

It is also exactly the defect the automated run could not have caught: that run
*created its subject as a fixture with `auto_handled = true`*. Only driving a real
conversation exposes it — which is why this step was left for a human pass.

### The fix

The flag is now written rather than hardcoded, and the signal it reads is the
one already present in the data: **the gateway's per-inbound case is a
placeholder and carries no `contact_reason`; a real escalation always has one.**
So `auto_handled` is "no *triaged* case is open on this thread", which keeps the
placeholder — and therefore keeps every conversation visible in the rep queue.
Nothing about queue behaviour changes.

Three things had to move together:

1. Both gateway writers compute the flag instead of hardcoding `FALSE`. The
   outbound writer decides it, because the escalation happens *during* the turn —
   at inbound the agent has not run yet, so it would always read "not escalated".
2. When the turn did escalate, the inbound that triggered it is settled to
   `FALSE` too. Otherwise the customer's message reads auto-handled while the
   reply escalating it does not, and `active_case_segment` hides the very turn
   that opened the case.
3. `create_case` now attaches to the thread it was raised from (via the
   ADR-0107 turn binding on the context). It previously dropped the link
   entirely — the mock twin accepted `channelThreadId` and the Postgres handler
   ignored it — so an agent escalation was invisible to every thread-scoped
   read. Without this, fixing only the writers would have made escalated
   conversations show up *as auto-handled*, which is worse than the original bug.

`contact_reason` is not a required parameter, so an escalation raised from a
live turn without one is recorded as `unspecified` rather than being left
indistinguishable from the placeholder.

This reproduces the `0005_dev_bootstrap` seed exactly: `thread_ar`'s April pair
is auto-handled, and both June turns — after `case_ar_urgent` opened with
`contact_reason = 'order_status'` — are not.

Six of the seven behaviours above are pinned by tests that drive the **real**
writers (`test_postgres_gateway_store.py`), each verified to go red when its own
part of the fix is reverted. Every pre-existing test in the tree seeds
`auto_handled` by hand, which is precisely how the writer stayed unimplemented
from the first Postgres port until a live acceptance run went looking.

---

## Host-tier fallback

If another worktree's Postgres owns the container name, run the app tier on the
host against the Postgres that is already up:

```bash
# migrations + demo accounts/cases into the running DB
cd hermes-runtime && HERMES_APPLY_DEV_SEED=1 uv run python -m hermes_runtime.datastore.migrate

# one per terminal (or backgrounded)
TOEE_HERMES_PROFILE=internal_copilot DISPATCH_API_TOKEN=dev-copilot-token TOOL_BACKEND=datastore \
  uv run uvicorn hermes_runtime.tool_dispatch_composition:build_tool_dispatch_app --factory --host 127.0.0.1 --port 8091
TOEE_HERMES_PROFILE=supervisor_admin DISPATCH_API_TOKEN=dev-admin-token TOOL_BACKEND=datastore \
  uv run uvicorn hermes_runtime.tool_dispatch_composition:build_tool_dispatch_app --factory --host 127.0.0.1 --port 8092

pnpm dev:workbench   # from the repo root
```

This covers everything except the gateway-dependent simulator step (PAC-1 step 2).
